"""Fire-and-forget Discord webhook notifications.

Used to announce in a Discord channel that a study session finished. The
network call runs on a short-lived background thread so it never blocks Anki's
UI, and every failure is swallowed (and logged) rather than surfaced.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from typing import Optional

from .log import log

_TIMEOUT = 10.0


def _looks_like_webhook(url: str) -> bool:
    url = (url or "").strip()
    return url.startswith("https://") and "/api/webhooks/" in url


def send_webhook(
    url: str,
    content: str,
    username: Optional[str] = None,
    avatar_url: Optional[str] = None,
    on_done=None,
) -> None:
    """Post ``content`` to a Discord webhook on a background thread.

    ``on_done`` (if given) is called with ``(ok: bool, message: str)`` when the
    request finishes. It runs on the worker thread, so callers that touch the UI
    must marshal back to the main thread themselves.
    """
    if not _looks_like_webhook(url):
        if on_done:
            on_done(False, "The webhook URL doesn't look like a Discord webhook.")
        else:
            log("refusing to send: invalid webhook URL")
        return

    payload = {"content": content[:2000]}
    if username:
        payload["username"] = username[:80]
    if avatar_url:
        payload["avatar_url"] = avatar_url
    # Don't let a message accidentally ping @everyone / roles.
    payload["allowed_mentions"] = {"parse": ["users"]}

    data = json.dumps(payload).encode("utf-8")

    def worker() -> None:
        request = urllib.request.Request(
            url.strip(),
            data=data,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "anki-discord-rich-presence",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=_TIMEOUT) as resp:
                status = getattr(resp, "status", resp.getcode())
            ok = 200 <= status < 300
            msg = "Webhook sent." if ok else ("Discord returned HTTP %s." % status)
            log("webhook status %s" % status)
            if on_done:
                on_done(ok, msg)
        except urllib.error.HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode("utf-8", "replace")[:200]
            except Exception:
                pass
            log("webhook HTTPError %s %s" % (exc.code, body))
            if on_done:
                on_done(False, "Discord returned HTTP %s. %s" % (exc.code, body))
        except Exception as exc:  # noqa: BLE001 - never let this crash Anki
            log("webhook failed: %s" % exc)
            if on_done:
                on_done(False, "Could not reach Discord: %s" % exc)

    threading.Thread(target=worker, name="DiscordWebhook", daemon=True).start()
