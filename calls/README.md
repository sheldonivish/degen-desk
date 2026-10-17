# Call auto-execution (box -> VPS -> Lighter)

Every BTC / XAU setup call the bot posts can also become a real Lighter order, placed by `calls_exec.py` on a VPS.
PRACTICE by default (`CALLS_LIVE=1` to send). Not financial advice; every call can lose its full risk.

**Box side, `push_calls.py`**: reads the call log `open_calls.json` (id, instrument, side, entry, stop, tp1, tp2,
expiry ISO, status), writes one JSON message per change atomically into the server's `calls/inbox/` over SFTP
(`open` / `update` / `cancel`, file name = message id, versioned by a hash of the levels), samples the OKX price at send
time (`okx_ref`) so the server can shift levels by the OKX->Lighter basis, waits for `calls/ack/<msg>.json`, resends
unacked messages every 90 s, and prints `ALERT` (exit 2) when a message is unacked after 5 min or the executor
refused it. `trade_signal.py --send` starts `push_calls.py watch` for 10 min when `DD_PUSH_CALLS` points to it.

**Server side, `calls_exec.py`**: duplicate-safe inbox (seen list, re-ack), then per call: GTT limit at entry,
split into two OTOCO groups (half -> TP1, half runner -> TP2), each with a reduce-only exchange stop at the call stop,
no break-even move. Size = configured risk of equity, floored to the lot, capped by per-market leverage and by total
open risk (calls + autopilot) <= `max_total_risk`; below the venue minimum = not placed + ALERT. Unfilled entries
are cancelled at expiry or when price tags TP1 first. A changed stop on a filled call moves the exchange stop; a
cancelled/invalidated call cancels its orders. Missing stop -> replaced, or the position is flattened.
Guards: STOP file (flatten), daily loss stop, drawdown pause, one position per market. Conflict rule with the
autopilot: a BTC call is not placed while the autopilot holds a trade or resting entry, and while a call is active the
executor writes `calls/busy_BTC` so the autopilot opens nothing new and leaves that position alone.
Posts FILLED / TP1 HIT / TP2 HIT / STOPPED to the approved Telegram chat.
