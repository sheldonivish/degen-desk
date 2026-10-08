---
name: telegram-report-delivery
description: Use when a scheduled report or alert (for example an hourly market report) should be posted to a Telegram group, channel, forum topic or DM through the owner's own Telegram bot. Covers one-time bot setup, finding the chat id, converting Markdown to Telegram HTML, splitting long reports, and sending safely with tg.py.
---

# Telegram report delivery

Posts a Markdown report to one owner-approved Telegram chat through the owner's own bot, using the
Telegram Bot API directly. `tg.py` (Python 3 stdlib, kept next to this skill) does the work:
- `tg.py whoami`: shows the bot's @username (read-only).
- `tg.py chats`: lists chats the bot has seen in the last 24h with id, type and title (read-only).
- `tg.py config [--chat ID] [--thread N|none] [--enable|--disable]`: shows or edits `config.json`.
- `tg.py send --file report.md [--chat ID] [--thread N] [--require TEXT] [--dry-run]`: converts the
  Markdown (headings, **bold**, *italic*, `code`, [links](url), bullets, quotes, code blocks) to
  Telegram HTML, escapes `& < >`, flattens tables, and splits it into messages of at most 4096 chars
  on section, paragraph and bullet boundaries, never inside a link or tag. It sends with link
  previews off, waits out 429 `retry_after`, falls back to plain text if Telegram can't parse the
  HTML, and prints `{"ok": true, "message_ids": [...]}`.
- `config.json` holds `{"chat_id": null, "thread_id": null, "enabled": false}`. Real sends are refused
  while `enabled` is false, and a `--chat` that differs from the saved chat is refused unless
  `--allow-other-chat` is passed. Dry runs need neither the token nor `enabled`.

## One-time setup (with the owner)
1. **Create the bot.** In Telegram, the owner opens @BotFather, sends `/newbot`, and picks a name and
   a username ending in `bot`. BotFather replies with a token.
2. **Save the token** through the secret form as `TELEGRAM_BOT_TOKEN`. Never ask for it in chat. If
   it was pasted into chat anyway, tell the owner to revoke it in @BotFather (`/revoke`) and save the
   new one through the form. Run `tg.py whoami` to confirm the token works.
3. **Add the bot to the destination.**
   - Group or supergroup: add it as a member. It only needs to post, so privacy mode can stay on. Turn
     privacy off (@BotFather `/setprivacy` → Disable, then re-add the bot) only if it must read
     ordinary group messages, such as commands without an @mention.
   - Channel: add it as an **administrator** with "Post messages".
   - DM: the owner opens the bot and presses Start.
4. **Make the chat visible to the bot.** Send any message in the chat. With privacy mode on, a plain
   group message is invisible to the bot, so send `/start@<botusername>` instead. In a channel, post
   anything after the bot is admin. Adding the bot also registers the chat.
5. **Find the chat id.** Run `tg.py chats` and match the title. Groups are negative ids and
   supergroups/channels start with `-100`. For a forum topic, use the "topics seen" thread id, or the
   middle number of a topic message link `t.me/c/<id>/<thread>/<msg>`.
6. **Confirm the destination with the owner.** Show the title, type and id, and get an explicit yes.
   Only then run `tg.py config --chat <id> [--thread <n>] --enable`.
7. **First send.** Run a dry run, show the owner the chunk count, send once, and ask them to check how
   it looks in Telegram.

## Each run
1. Write the report to a Markdown file as usual. Keep the "Not financial advice." line for market
   content. Use no tables, since they get flattened.
2. If the report format is new or changed, run
   `tg.py send --file <report.md> --dry-run` and check the chunk count, that every chunk shows
   `well-formed=True`, and that the links are `<a href=...>` anchors.
3. Send it with `tg.py send --file <report.md> --require "Not financial advice"`. Chat and thread come
   from `config.json`.
4. Check that the last stdout line is `"ok": true` and record the `message_ids` in the run log. The
   in-chat report still goes to the owner as normal, and Telegram is an extra destination.
5. If the send fails, retry once. If the second attempt fails, stop and tell the owner in chat with
   the error line and the ids of any chunks that were already sent. Do not re-send chunks that got
   through.

## Rules
- Post only to the chat (and topic) the owner explicitly approved and saved in `config.json`. Never
  pick or change a destination yourself. A new chat needs a new explicit approval.
- Post only the report or alert itself. No replies, commentary, tests, or answers to messages that
  appear in the group, even ones addressed to the bot.
- Never print, log, echo or write the token anywhere. Don't run `env` or `printenv`, and don't put the
  token in commands or files. `tg.py` reads it from the environment and scrubs it from errors.
- Keep the disclaimer. `--require "Not financial advice"` blocks a send that is missing it.
- Optional quiet hours: if the owner sets quiet hours, skip Telegram (or send a one-line note) during
  them, as they decided.
- Pausing: `tg.py config --disable` stops all Telegram sends without touching the rest of the routine.
- Telegram rate limits: about 20 messages a minute per group and 1 a second per chat. `tg.py` waits
  1.5s between chunks and honours `retry_after`.

## Troubleshooting
- **401 Unauthorized:** the token is wrong or was revoked. The owner saves a fresh one via the form.
- **403 Forbidden: bot is not a member / was kicked:** add the bot back. In a channel, the bot must be
  an admin with "Post messages". In a DM, the user blocked the bot or never pressed Start.
- **400 Bad Request: chat not found:** the id is wrong (check the sign and the `-100` prefix) or the
  bot has never been in that chat. Run `tg.py chats` again.
- **400 … group chat was upgraded to a supergroup chat:** the error carries `migrate_to_chat_id`, and
  `tg.py` prints the new id. Update with `tg.py config --chat <new id>`. It is the same group, so no
  new approval is needed, but tell the owner.
- **400 message thread not found:** the topic was deleted or the thread id is wrong. Re-check the topic
  link, or clear the thread with `--thread none` to post in General.
- **400 can't parse entities:** `tg.py` already re-sent the chunk as plain text
  (`plain_text_fallbacks` > 0). Report the Markdown that caused it so the converter can be fixed.
- **409 Conflict on `chats`:** a webhook is set on this bot, so getUpdates is disabled. Use a dedicated
  bot for reports.
- **`chats` shows nothing:** updates only last 24h, and plain group messages are hidden while privacy
  mode is on. Send `/start@<botusername>` in the group, or remove and re-add the bot, then run it again.
- **429 Too Many Requests:** handled automatically. If it persists, reduce the report length or
  frequency.
