"""Discord Rich Presence for Anki.

Shows what you're reviewing on your Discord profile and (optionally) announces
finished study sessions in a Discord channel via a webhook.

Works on Windows, macOS and Linux. All network/IPC work happens off the UI
thread and every failure is contained so it can never crash Anki.
"""

from __future__ import annotations

import time
from typing import Optional

from aqt import gui_hooks, mw
from aqt.qt import QAction, qconnect
from aqt.utils import openLink, tooltip

from .log import log
from .presence import PresenceManager
from .webhook import send_webhook

GITHUB_URL = "https://github.com/iDavi/anki-discord-rich-presence"

# Shipped as the default so the config is valid JSON, but it is not a real
# Discord application. Rich Presence stays dormant until the user sets their own
# Application ID (see the setup guide / config.md).
PLACEHOLDER_CLIENT_ID = "1234567890123456789"

# Every recognised config key with its default. Real config is merged on top of
# this so upgrades that add keys keep working with old saved configs.
DEFAULTS = {
    "enabled": True,
    "client_id": "1234567890123456789",
    "details_template": "Reviewing {deck}",
    "state_template": "{reviewed} cards reviewed",
    "show_elapsed_time": True,
    "large_image_key": "anki",
    "large_image_text": "Anki",
    "small_image_key": "",
    "small_image_text": "",
    "show_idle": True,
    "idle_details": "Taking a break",
    "idle_state": "In the deck browser",
    "webhook_enabled": False,
    "webhook_url": "",
    "webhook_username": "Anki",
    "webhook_avatar_url": "",
    "webhook_min_cards": 1,
    "webhook_display_name": "",
    "webhook_message_template": (
        "**{user}** just finished a study session! \U0001f389\n"
        "\U0001f4da Deck: **{deck}**\n"
        "\U0001f3b4 Cards reviewed: **{reviewed}**\n"
        "⏱️ Time studied: **{duration}**"
    ),
}


def _format_duration(seconds: float) -> str:
    seconds = int(max(0, seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return "%dh %dm" % (hours, minutes)
    if minutes:
        return "%dm %ds" % (minutes, secs)
    return "%ds" % secs


def _render(template: str, values: dict) -> str:
    """Fill a ``{placeholder}`` template, tolerating unknown/typo'd keys."""
    class _Safe(dict):
        def __missing__(self, key):  # noqa: D401 - keep unknown tokens literal
            return "{%s}" % key

    try:
        return str(template).format_map(_Safe(values))
    except Exception:
        return str(template)


def _clip(text: str, limit: int = 128) -> str:
    text = text or ""
    return text if len(text) <= limit else text[: limit - 1] + "…"


class DiscordAddon:
    def __init__(self) -> None:
        self.config = self._load_config()
        self.presence = PresenceManager(self.config["client_id"])
        # Per-session tracking, used both for presence and the webhook.
        self._session_active = False
        self._session_start = 0.0
        self._session_reviewed = 0
        self._session_deck = ""
        self._enabled_action: Optional[QAction] = None
        self._warned_setup = False

    # -- config ---------------------------------------------------------------

    def _load_config(self) -> dict:
        merged = dict(DEFAULTS)
        try:
            saved = mw.addonManager.getConfig(__name__) or {}
            merged.update({k: v for k, v in saved.items() if v is not None})
        except Exception as exc:
            log("could not read config, using defaults: %s" % exc)
        return merged

    def _save_config(self) -> None:
        try:
            mw.addonManager.writeConfig(__name__, self.config)
        except Exception as exc:
            log("could not save config: %s" % exc)

    def on_config_changed(self, *args) -> None:
        old_client = self.config.get("client_id")
        self.config = self._load_config()
        if self._enabled_action is not None:
            self._enabled_action.setChecked(bool(self.config["enabled"]))
        if self.config["client_id"] != old_client:
            self.presence.set_client_id(self.config["client_id"])
        self.refresh_presence()

    # -- lifecycle ------------------------------------------------------------

    def setup(self) -> None:
        self.presence.start()
        self._build_menu()
        self._register_hooks()
        try:
            mw.addonManager.setConfigUpdatedAction(__name__, self.on_config_changed)
        except Exception:
            pass
        # Reflect the initial state once the profile is ready.
        gui_hooks.profile_did_open.append(self._on_profile_open)
        gui_hooks.profile_will_close.append(self._on_profile_close)

    def _has_valid_client_id(self) -> bool:
        cid = str(self.config.get("client_id", "")).strip()
        return cid.isdigit() and 17 <= len(cid) <= 20 and cid != PLACEHOLDER_CLIENT_ID

    def _register_hooks(self) -> None:
        gui_hooks.state_did_change.append(self._on_state_change)
        gui_hooks.reviewer_did_show_question.append(self._on_show_question)
        gui_hooks.reviewer_will_end.append(self._on_reviewer_end)
        if hasattr(gui_hooks, "reviewer_did_answer_card"):
            gui_hooks.reviewer_did_answer_card.append(self._on_answer_card)

    # -- Anki hooks -----------------------------------------------------------

    def _on_profile_open(self) -> None:
        self._maybe_warn_setup()
        self.refresh_presence()

    def _maybe_warn_setup(self) -> None:
        if self._warned_setup:
            return
        if self.config.get("enabled") and not self._has_valid_client_id():
            self._warned_setup = True
            tooltip(
                "Discord Rich Presence: set your Discord Application ID in the "
                "add-on config to start showing your reviews.",
                period=6000,
            )

    def _on_state_change(self, new_state: str, old_state: str) -> None:
        if new_state == "review" and not self._session_active:
            self._start_session()
        self.refresh_presence(new_state)

    def _on_show_question(self, card) -> None:
        if not self._session_active:
            self._start_session()
        self.refresh_presence("review")

    def _on_answer_card(self, reviewer, card, ease) -> None:
        self._session_reviewed += 1
        deck = self._deck_name_for_card(card)
        if deck:
            self._session_deck = deck
        self.refresh_presence("review")

    def _on_reviewer_end(self) -> None:
        self._finish_session()

    def _on_profile_close(self) -> None:
        # If Anki is closed mid-session, still honour the "session finished"
        # announcement before tearing everything down.
        self._finish_session()
        self.presence.clear()

    # -- session bookkeeping --------------------------------------------------

    def _start_session(self) -> None:
        self._session_active = True
        self._session_start = time.time()
        self._session_reviewed = 0
        self._session_deck = self._current_deck_name()

    def _finish_session(self) -> None:
        if not self._session_active:
            return
        self._session_active = False
        reviewed = self._session_reviewed
        duration = time.time() - self._session_start
        deck = self._session_deck or self._current_deck_name()
        self._maybe_send_webhook(deck, reviewed, duration)

    def _current_deck_name(self) -> str:
        try:
            return mw.col.decks.current()["name"]
        except Exception:
            return "Anki"

    def _deck_name_for_card(self, card) -> str:
        try:
            return mw.col.decks.name(card.current_deck_id())
        except Exception:
            try:
                return mw.col.decks.name(card.did)
            except Exception:
                return ""

    # -- presence -------------------------------------------------------------

    def refresh_presence(self, state: Optional[str] = None) -> None:
        if not self.config.get("enabled") or not self._has_valid_client_id():
            # Nothing to show, and connecting with a bogus id would just fail
            # in a loop. Webhooks are independent and keep working.
            self.presence.clear()
            return
        if state is None:
            state = self._current_state()

        if state == "review" and self._session_active:
            activity = self._build_review_activity()
        elif self.config.get("show_idle"):
            activity = self._build_idle_activity()
        else:
            self.presence.clear()
            return
        self.presence.update(activity["_activity"], key=activity["_key"])

    def _current_state(self) -> str:
        try:
            return mw.state
        except Exception:
            return ""

    def _placeholders(self) -> dict:
        return {
            "deck": self._session_deck or self._current_deck_name(),
            "reviewed": self._session_reviewed,
            "duration": _format_duration(time.time() - self._session_start)
            if self._session_active
            else "0s",
        }

    def _assets(self) -> Optional[dict]:
        assets = {}
        if self.config.get("large_image_key"):
            assets["large_image"] = self.config["large_image_key"]
            if self.config.get("large_image_text"):
                assets["large_text"] = _clip(self.config["large_image_text"])
        if self.config.get("small_image_key"):
            assets["small_image"] = self.config["small_image_key"]
            if self.config.get("small_image_text"):
                assets["small_text"] = _clip(self.config["small_image_text"])
        return assets or None

    def _build_review_activity(self) -> dict:
        values = self._placeholders()
        details = _clip(_render(self.config["details_template"], values))
        state = _clip(_render(self.config["state_template"], values))
        activity = {}
        if len(details) >= 2:
            activity["details"] = details
        if len(state) >= 2:
            activity["state"] = state
        if self.config.get("show_elapsed_time") and self._session_active:
            activity["timestamps"] = {"start": int(self._session_start)}
        assets = self._assets()
        if assets:
            activity["assets"] = assets
        key = "review|%s|%s|%s" % (details, state, int(self._session_start))
        return {"_activity": activity, "_key": key}

    def _build_idle_activity(self) -> dict:
        details = _clip(self.config.get("idle_details", ""))
        state = _clip(self.config.get("idle_state", ""))
        activity = {}
        if len(details) >= 2:
            activity["details"] = details
        if len(state) >= 2:
            activity["state"] = state
        assets = self._assets()
        if assets:
            activity["assets"] = assets
        if not activity:
            activity["details"] = "Using Anki"
        return {"_activity": activity, "_key": "idle|%s|%s" % (details, state)}

    # -- webhook --------------------------------------------------------------

    def _maybe_send_webhook(self, deck: str, reviewed: int, duration: float) -> None:
        if not self.config.get("webhook_enabled"):
            return
        try:
            min_cards = int(self.config.get("webhook_min_cards", 1))
        except (TypeError, ValueError):
            min_cards = 1
        if reviewed < max(1, min_cards):
            return
        self._post_session(deck, reviewed, duration)

    def _post_session(self, deck: str, reviewed: int, duration: float, notify=False) -> None:
        user = self.config.get("webhook_display_name") or self._profile_name()
        content = _render(
            self.config["webhook_message_template"],
            {
                "user": user,
                "deck": deck or "Anki",
                "reviewed": reviewed,
                "duration": _format_duration(duration),
            },
        )
        on_done = self._webhook_feedback if notify else None
        send_webhook(
            self.config.get("webhook_url", ""),
            content,
            username=self.config.get("webhook_username") or None,
            avatar_url=self.config.get("webhook_avatar_url") or None,
            on_done=on_done,
        )

    def _webhook_feedback(self, ok: bool, message: str) -> None:
        def show():
            tooltip(message, period=4000)

        try:
            mw.taskman.run_on_main(show)
        except Exception:
            log(message)

    def _profile_name(self) -> str:
        try:
            return mw.pm.name or "Someone"
        except Exception:
            return "Someone"

    # -- menu -----------------------------------------------------------------

    def _build_menu(self) -> None:
        menu = mw.form.menuTools.addMenu("Discord Rich Presence")

        enabled = QAction("Enabled", mw, checkable=True)
        enabled.setChecked(bool(self.config.get("enabled")))
        qconnect(enabled.triggered, self._toggle_enabled)
        menu.addAction(enabled)
        self._enabled_action = enabled

        reconnect = QAction("Reconnect to Discord", mw)
        qconnect(reconnect.triggered, self._reconnect)
        menu.addAction(reconnect)

        menu.addSeparator()

        test = QAction("Send test webhook", mw)
        qconnect(test.triggered, self._send_test_webhook)
        menu.addAction(test)

        menu.addSeparator()

        help_action = QAction("Help / Setup guide", mw)
        qconnect(help_action.triggered, lambda: openLink(GITHUB_URL))
        menu.addAction(help_action)

    def _toggle_enabled(self, checked: bool) -> None:
        self.config["enabled"] = bool(checked)
        self._save_config()
        self.refresh_presence()
        tooltip("Discord Rich Presence %s" % ("enabled" if checked else "disabled"))

    def _reconnect(self) -> None:
        self.presence.set_client_id(self.config["client_id"])
        self.refresh_presence()
        tooltip("Reconnecting to Discord…")

    def _send_test_webhook(self) -> None:
        if not (self.config.get("webhook_url") or "").strip():
            tooltip("Set a webhook URL in the add-on config first.")
            return
        deck = self._current_deck_name()
        self._post_session(deck, reviewed=42, duration=15 * 60, notify=True)
        tooltip("Sending test webhook…")

    def shutdown(self) -> None:
        self.presence.shutdown()


def _init() -> None:
    if mw is None:
        return
    addon = DiscordAddon()
    addon.setup()
    # Keep a reference alive and tidy up on exit.
    mw._discord_rich_presence = addon  # noqa: SLF001
    try:
        from aqt import qt

        qt.QApplication.instance().aboutToQuit.connect(addon.shutdown)
    except Exception:
        pass


_init()
