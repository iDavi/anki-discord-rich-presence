# anki-discord-rich-presence

Tell everyone which Anki cards you're reviewing!!!1111111

A lightweight [Anki](https://apps.ankiweb.net/) add-on that shows your current
study session as a **Discord Rich Presence** on your profile, and can post a
message to a **Discord channel** (via a webhook) whenever you finish a session.

Works on **Windows, macOS and Linux** — the Discord IPC socket is discovered
across all three platforms (including sandboxed Flatpak/snap installs on Linux),
with no third-party Python dependencies to install.

## Features

- 🎴 **Rich Presence** while reviewing — shows the deck name, cards reviewed and
  a live elapsed timer on your Discord profile.
- 💤 **Idle status** when you step away from the reviewer (optional).
- 📣 **Session webhooks** — announce in a Discord channel when you finish a
  session, including deck, card count and time studied.
- 🧩 Fully **configurable** message templates and images, right from Anki's
  add-on config screen.
- 🍎 **macOS first-class support** (and Windows/Linux too).

## Installation

### From a release (recommended)

1. Download `anki-discord-rich-presence.ankiaddon` from the
   [latest release](https://github.com/iDavi/anki-discord-rich-presence/releases/latest).
2. In Anki: **Tools → Add-ons → Install from file…** and pick the downloaded
   file, or simply double-click the `.ankiaddon` file.
3. Restart Anki. Make sure the **Discord desktop app** is running.

### Build it yourself

```bash
python build.py
# → dist/anki-discord-rich-presence.ankiaddon
```

## First-time setup (required for Rich Presence)

Discord only shows Rich Presence for a registered application, so you set an
**Application ID** once. It takes about two minutes:

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications)
   → **New Application**. Name it whatever should appear on your profile
   (e.g. "Anki").
2. *(Optional)* Under **Rich Presence → Art Assets**, upload an image named
   `anki` so an icon shows next to your status.
3. Copy the **Application ID** from **General Information**.
4. In Anki: **Tools → Add-ons → Discord Rich Presence → Config**, paste it into
   `client_id`, and **Save**.

Until an Application ID is set, the webhook still works but the on-profile Rich
Presence stays off (Anki will remind you once on startup).

## Usage

With an Application ID set and the Discord desktop app running, start reviewing
any deck — your Discord profile will show what you're studying. Quick actions
live under **Tools → Discord Rich Presence** (enable/disable, reconnect, send a
test webhook).

### Set up the session webhook

1. In your Discord server: **Server Settings → Integrations → Webhooks → New
   Webhook**, choose a channel, and **Copy Webhook URL**.
2. In Anki, open the add-on **Config** and set:
   - `webhook_enabled` → `true`
   - `webhook_url` → the URL you copied
3. Finish a review session — everyone in that channel gets a message like:

   > **davi** just finished a study session! 🎉
   > 📚 Deck: **Spanish::Verbs**
   > 🎴 Cards reviewed: **42**
   > ⏱️ Time studied: **15m 3s**

Use **Tools → Discord Rich Presence → Send test webhook** to check it without
finishing a real session.

## Configuration reference

Every option is documented inline on the add-on's config screen. See
[`addon/config.md`](addon/config.md) for the full list, including all message
template placeholders (`{deck}`, `{reviewed}`, `{duration}`, `{user}`).

## How it works

- `addon/ipc.py` — a tiny, dependency-free Discord IPC client that finds and
  talks to the local Discord socket on every OS.
- `addon/presence.py` — a background worker that owns the connection, coalesces
  rapid updates and respects Discord's rate limit, so the Anki UI never blocks.
- `addon/webhook.py` — fire-and-forget webhook posting on a background thread.
- `addon/__init__.py` — wires Anki's review hooks to presence + session
  tracking.

## License

[MIT](LICENSE)
