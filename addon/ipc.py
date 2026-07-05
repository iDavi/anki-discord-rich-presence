"""A tiny, dependency-free Discord IPC (Rich Presence) client.

This talks to the local Discord client over its IPC socket. It is written to
work on Windows (named pipes), macOS and Linux (Unix domain sockets), including
the various sandboxed layouts used by Flatpak/snap on Linux.

Only the small subset of the protocol needed for setting a rich-presence
activity is implemented, so we don't need to bundle ``pypresence`` or any other
third-party package inside the add-on.
"""

from __future__ import annotations

import json
import os
import socket
import struct
import sys
import time
from typing import Optional

# IPC op-codes as defined by Discord's IPC protocol.
OP_HANDSHAKE = 0
OP_FRAME = 1
OP_CLOSE = 2
OP_PING = 3
OP_PONG = 4


class DiscordIPCError(Exception):
    """Raised when the IPC connection fails or misbehaves."""


def _ipc_candidate_paths() -> list:
    """Return the list of socket paths Discord might be listening on.

    On Windows these are named pipes; on macOS/Linux they are Unix domain
    sockets living under a temp directory. Discord numbers the sockets
    ``discord-ipc-0`` .. ``discord-ipc-9``.
    """
    if sys.platform == "win32":
        return [r"\\?\pipe\discord-ipc-%d" % i for i in range(10)]

    # POSIX (macOS + Linux). Discord picks the first writable of these env
    # vars as its runtime dir; fall back to /tmp when none are set.
    base_dirs = []
    for var in ("XDG_RUNTIME_DIR", "TMPDIR", "TMP", "TEMP"):
        value = os.environ.get(var)
        if value:
            base_dirs.append(value)
    base_dirs.append("/tmp")

    # Sandboxed Discord installs nest the socket in a sub-directory.
    sub_dirs = [
        "",
        "app/com.discordapp.Discord",
        "snap.discord-canary",
        "snap.discord",
        ".flatpak/dev.vencord.Vesktop/xdg-run",
    ]

    paths = []
    seen = set()
    for base in base_dirs:
        for sub in sub_dirs:
            directory = os.path.join(base, sub) if sub else base
            for i in range(10):
                path = os.path.join(directory, "discord-ipc-%d" % i)
                if path not in seen:
                    seen.add(path)
                    paths.append(path)
    return paths


class DiscordIPC:
    """Minimal blocking Discord IPC client.

    All methods raise :class:`DiscordIPCError` on failure. The caller is
    expected to run this off the UI thread and to reconnect on error.
    """

    def __init__(self, client_id: str, timeout: float = 2.0) -> None:
        self.client_id = str(client_id)
        self.timeout = timeout
        self._sock: Optional[socket.socket] = None
        self._pipe = None  # Windows file handle

    # -- connection lifecycle -------------------------------------------------

    @property
    def connected(self) -> bool:
        return self._sock is not None or self._pipe is not None

    def connect(self) -> None:
        if self.connected:
            return
        last_error: Optional[Exception] = None
        for path in _ipc_candidate_paths():
            try:
                if sys.platform == "win32":
                    self._open_pipe(path)
                else:
                    self._open_unix_socket(path)
                self._handshake()
                return
            except (OSError, DiscordIPCError) as exc:
                last_error = exc
                self._reset()
                continue
        raise DiscordIPCError(
            "could not connect to Discord IPC socket (is Discord running?): %s"
            % last_error
        )

    def _open_unix_socket(self, path: str) -> None:
        if not os.path.exists(path):
            raise DiscordIPCError("no socket at %s" % path)
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        sock.connect(path)
        self._sock = sock

    def _open_pipe(self, path: str) -> None:
        # Named pipes behave like files on Windows.
        self._pipe = open(path, "r+b", buffering=0)

    def _handshake(self) -> None:
        self._send(OP_HANDSHAKE, {"v": 1, "client_id": self.client_id})
        op, _ = self._recv()
        if op == OP_CLOSE:
            raise DiscordIPCError("Discord rejected the handshake")

    def close(self) -> None:
        if not self.connected:
            return
        try:
            self._send(OP_CLOSE, {})
        except Exception:
            pass
        self._reset()

    def _reset(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None
        if self._pipe is not None:
            try:
                self._pipe.close()
            except Exception:
                pass
            self._pipe = None

    # -- framing --------------------------------------------------------------

    def _write(self, data: bytes) -> None:
        if self._sock is not None:
            self._sock.sendall(data)
        elif self._pipe is not None:
            self._pipe.write(data)
            self._pipe.flush()
        else:
            raise DiscordIPCError("not connected")

    def _read_exact(self, size: int) -> bytes:
        chunks = []
        remaining = size
        while remaining > 0:
            if self._sock is not None:
                chunk = self._sock.recv(remaining)
            elif self._pipe is not None:
                chunk = self._pipe.read(remaining)
            else:
                raise DiscordIPCError("not connected")
            if not chunk:
                raise DiscordIPCError("connection closed by Discord")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def _send(self, op: int, payload: dict) -> None:
        data = json.dumps(payload).encode("utf-8")
        header = struct.pack("<II", op, len(data))
        self._write(header + data)

    def _recv(self):
        header = self._read_exact(8)
        op, length = struct.unpack("<II", header)
        data = self._read_exact(length) if length else b""
        try:
            payload = json.loads(data.decode("utf-8")) if data else {}
        except ValueError:
            payload = {}
        return op, payload

    # -- high level -----------------------------------------------------------

    def set_activity(self, activity: Optional[dict]) -> None:
        """Set (or clear, when ``activity`` is ``None``) the rich presence."""
        payload = {
            "cmd": "SET_ACTIVITY",
            "args": {"pid": os.getpid(), "activity": activity},
            "nonce": "%d" % time.time_ns(),
        }
        self._send(OP_FRAME, payload)
        # Discord replies to every frame; read and discard it so the socket
        # buffer doesn't fill up. Failures here just mean a stale connection.
        self._recv()
