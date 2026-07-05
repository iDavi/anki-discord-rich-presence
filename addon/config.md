# Discord Rich Presence — configuration

After changing anything here, click **Save**. Most changes apply immediately;
if Rich Presence doesn't update, use **Tools → Discord Rich Presence →
Reconnect to Discord**.

## Rich Presence

- **enabled** — master switch for showing your status on Discord.
- **client_id** — the *Application (Client) ID* of a Discord application. The
  bundled default works out of the box, but the app name/icon shown on your
  profile belong to whoever owns that application. To use your own name and
  artwork, create an app at <https://discord.com/developers/applications>,
  upload art under *Rich Presence → Art Assets*, and paste its Application ID
  here.
- **details_template** / **state_template** — the two lines shown under your
  name. Available placeholders: `{deck}`, `{reviewed}`, `{duration}`.
- **show_elapsed_time** — show a live "elapsed" timer for the current session.
- **large_image_key** / **small_image_key** — names of art assets uploaded to
  your Discord application. Leave blank to show no image. `*_text` is the
  tooltip shown when hovering the image.
- **show_idle** — when `true`, keep a presence up (using **idle_details** /
  **idle_state**) even when you're not actively reviewing. When `false`, the
  presence is cleared as soon as you leave the reviewer.

## Session webhook (announce in a channel)

- **webhook_enabled** — when `true`, post a message to a Discord channel every
  time you finish a review session.
- **webhook_url** — a channel webhook URL. In Discord: *Server Settings →
  Integrations → Webhooks → New Webhook → Copy Webhook URL*.
- **webhook_username** / **webhook_avatar_url** — override the name/avatar the
  message is posted under (optional).
- **webhook_min_cards** — only announce sessions with at least this many cards,
  so quick peeks don't spam the channel.
- **webhook_display_name** — the name used for `{user}` in the message. Leave
  blank to use your Anki profile name.
- **webhook_message_template** — the message body. Placeholders: `{user}`,
  `{deck}`, `{reviewed}`, `{duration}`. `@everyone`/`@here` are intentionally
  not pinged.
