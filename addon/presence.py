"""Background worker that owns the Discord IPC connection.

Anki hooks fire on the UI thread. Talking to a socket there could briefly
freeze the UI, and reconnect loops would make that worse, so all IPC work
happens on a dedicated worker thread. The UI side just pushes the latest
desired activity; the worker coalesces rapid updates and respects Discord's
rate limit (roughly 5 updates / 20s).
"""

from __future__ import annotations

import threading
import time
from typing import Optional

from .ipc import DiscordIPC, DiscordIPCError
from .log import log

# Discord rate-limits activity updates. Keep a comfortable minimum gap and
# coalesce anything that arrives in between into a single trailing update.
_MIN_UPDATE_INTERVAL = 5.0
# How long to wait between reconnection attempts when Discord isn't reachable.
_RECONNECT_BACKOFF = 30.0

_CLEAR = object()  # sentinel meaning "clear the presence"
_STOP = object()  # sentinel meaning "shut the worker down"


class PresenceManager:
    def __init__(self, client_id: str) -> None:
        self._client_id = str(client_id)
        self._ipc: Optional[DiscordIPC] = None
        self._pending = None  # latest desired activity, _CLEAR, or None
        self._has_pending = False
        self._cond = threading.Condition()
        self._thread: Optional[threading.Thread] = None
        self._stop = False
        self._last_send = 0.0
        self._last_connect_attempt = 0.0
        self._current_key = None  # cheap de-dupe of identical activities
        self._force_reconnect = False

    # -- public API (called from the UI thread) -------------------------------

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop = False
        self._thread = threading.Thread(
            target=self._run, name="DiscordPresence", daemon=True
        )
        self._thread.start()

    def set_client_id(self, client_id: str) -> None:
        client_id = str(client_id)
        if client_id == self._client_id:
            return
        # A different application id needs a fresh connection.
        with self._cond:
            self._client_id = client_id
            self._current_key = None
            self._force_reconnect = True
            # Re-send whatever we last showed under the new connection.
            if self._pending is not None:
                self._has_pending = True
            self._cond.notify_all()

    def update(self, activity: dict, key: Optional[str] = None) -> None:
        """Queue a new activity. ``key`` lets us skip redundant updates."""
        with self._cond:
            if key is not None and key == self._current_key:
                return
            self._current_key = key
            self._pending = activity
            self._has_pending = True
            self._cond.notify_all()

    def clear(self) -> None:
        with self._cond:
            self._current_key = "__cleared__"
            self._pending = _CLEAR
            self._has_pending = True
            self._cond.notify_all()

    def shutdown(self) -> None:
        with self._cond:
            self._stop = True
            self._pending = _STOP
            self._has_pending = True
            self._cond.notify_all()
        thread = self._thread
        if thread:
            thread.join(timeout=3.0)

    # -- worker thread --------------------------------------------------------

    def _run(self) -> None:
        while True:
            with self._cond:
                while not self._has_pending:
                    self._cond.wait()
                item = self._pending
                self._has_pending = False

            if item is _STOP or self._stop:
                break

            # Coalesce: enforce a minimum gap, then grab the very latest
            # value that arrived while we were waiting.
            gap = _MIN_UPDATE_INTERVAL - (time.time() - self._last_send)
            if gap > 0 and item is not _CLEAR:
                self._sleep_or_wake(gap)
                with self._cond:
                    item = self._pending if self._has_pending else item
                    self._has_pending = False
                    if item is _STOP or self._stop:
                        break

            try:
                self._apply(item)
                self._last_send = time.time()
            except (DiscordIPCError, OSError) as exc:
                log("presence update failed: %s" % exc)
                self._drop_connection()

        self._drop_connection()

    def _sleep_or_wake(self, seconds: float) -> None:
        # Sleep, but wake early if a stop is requested.
        deadline = time.time() + seconds
        with self._cond:
            while True:
                remaining = deadline - time.time()
                if remaining <= 0 or self._stop:
                    return
                self._cond.wait(timeout=remaining)

    def _apply(self, item) -> None:
        if item is _CLEAR:
            if self._ipc is not None:
                self._ipc.set_activity(None)
            return
        self._ensure_connected()
        if self._ipc is not None:
            self._ipc.set_activity(item)

    def _ensure_connected(self) -> None:
        if self._force_reconnect:
            self._force_reconnect = False
            self._drop_connection()
        if self._ipc is not None and self._ipc.connected:
            return
        now = time.time()
        if now - self._last_connect_attempt < _RECONNECT_BACKOFF and self._ipc is not None:
            raise DiscordIPCError("waiting before next reconnect attempt")
        self._last_connect_attempt = now
        self._ipc = DiscordIPC(self._client_id)
        self._ipc.connect()
        log("connected to Discord")

    def _drop_connection(self) -> None:
        if self._ipc is not None:
            try:
                self._ipc.close()
            except Exception:
                pass
            self._ipc = None
        self._current_key = None
