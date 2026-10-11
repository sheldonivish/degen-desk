# Telegram signals from the autopilot (optional, off by default)

Every autopilot trade event can post a chart card to one approved Telegram group through your own bot.
If any Telegram step fails, trading continues unchanged (sends run on a background thread; errors go to notify.log).

| autopilot event | card |
|---|---|
| G limit placed | NEW (pending limit, expiry) |
| position opened | FILLED |
| closed at target / stop / time | TP HIT / STOPPED (exit, USD, R) |
| limit expired or cancelled | CANCELLED |

Operational messages (started, paused, daily-loss stop, kill switch) are not posted unless `"ops": true`.
Account equity is always stripped. Without matplotlib, or if the candle fetch fails, a text card is sent instead.

## Setup (on the computer running the autopilot)
1. Stop the bot cleanly (exchange stop/TP stay resting): `launchctl unload ~/Library/LaunchAgents/com.degendesk.autopilot.plist`
2. Optional, for charts: `~/.degen-desk/autopilot/venv/bin/python3 -m pip install "matplotlib>=3.7"`
3. Store your bot token in the Keychain (paste at the prompt; never in a file or chat):
   `security add-generic-password -U -s degen-desk-telegram -a telegram -w`
4. In `~/.degen-desk/autopilot/config.json`:
   `"telegram": {"enabled": true, "chat_id": <YOUR_GROUP_CHAT_ID>, "thread_id": null, "ops": false}`
5. Test without trading: `venv/bin/python3 trade_signal.py --side long --entry 82000 --stop 81800 --tp 82500 --status NEW`
   (writes a PNG under ./signals).
6. Start again: `launchctl load ~/Library/LaunchAgents/com.degendesk.autopilot.plist`; check notify.log for `sendPhoto ok`.

Off switch: set `"enabled": false` and restart, or `security delete-generic-password -s degen-desk-telegram -a telegram`.
Footer text: set `SIGNAL_FOOTER` (default "Auto-traded by Degen Desk · Not financial advice"; manual calls use e.g.
"Manual call · Not financial advice"). If you also post manual calls, don't double-post a trade the autopilot placed.
