---
name: lighter-call-autoexec
description: >-
  Use when BTC/gold setup calls must also be placed as real Lighter orders by a VPS
  executor (or when one fails to place): deliver each call to the server's inbox
  with acks and retries, size it at the configured risk, put stop and TP1/TP2 on the
  exchange, cancel or move orders when the call changes, and keep it from fighting
  the autopilot.
---
# Lighter call auto-execution

Templates: degen-desk repo `calls/` (`push_calls.py` box side, `calls_exec.py` server side, README), deployed per
`vps-bot-deploy`. Live only after the owner explicitly asked for calls to be traded live (`CALLS_LIVE=1`); otherwise practice.
Every call is real money once live: post it carefully. Not financial advice.

## Delivery (box -> server)
1. Post the call per `btc-gold-setup-calls`, then write it to the call log (`open_calls.json`: id, instrument
   BTC-USDT-SWAP / XAU-USDT-SWAP, side, entry, stop, tp1, tp2, expiry ISO, status NEW) within 10 minutes.
2. `trade_signal.py --send` starts `push_calls.py watch` (10 min) when `DD_PUSH_CALLS` is set; every tracker run also
   starts with `push_calls.py sync` (catch-up + acks).
3. Protocol: one JSON message per change, written atomically (tmp + rename) into `calls/inbox/` over SFTP, named
   `<id>__open|update__<levels hash>` / `<id>__cancel`. The executor acks in `calls/ack/<msg>.json`; duplicates are
   re-acked without acting. Unacked -> resend every 90 s; unacked after 5 min, or ack ok=false -> `ALERT` line,
   exit code 2: report it to the owner as a blocker.
4. Price offset: the box samples the OKX price at send time (`okx_ref` + timestamp); the server shifts entry/stop/TPs
   by Lighter mid minus that price (falls back to a live OKX read, refuses if basis > 0.3%).

## Execution (server)
- Checks first: STOP file, daily-loss halt, drawdown pause, expiry, one active call per market, no foreign position
  on the market, levels consistent, price not already past stop or TP1.
- Size = configured risk (e.g. 2%) of equity / stop distance, floored to the lot, capped by per-market leverage
  (e.g. BTC 10x, gold 15x; if the cap binds, risk is lower, never higher) and by total open risk (calls + autopilot)
  <= 4%. Below the venue minimum -> not placed + ALERT. State the real risk % in the update.
- Entry = GTT limit at the call entry, split in two OTOCO groups: half -> TP1, half runner -> TP2, each with a reduce-only
  exchange stop at the call stop (worst-price limit 0.5% beyond). No break-even move unless the call rules say so.
- Unfilled entry cancelled at expiry or when price tags TP1 first. Call CANCELLED/INVALIDATED -> its orders are cancelled
  (flatten only if the message says close_if_filled). Changed levels on an unfilled call -> cancel + re-place. Changed stop
  on a filled call -> new exchange stop placed first, old one cancelled. Missing stop -> re-placed, else flatten.
- Conflict rule: calls take priority over the autopilot. A BTC call is not placed while the autopilot holds a trade or a
  resting entry (ALERT); while a call is active the executor writes `calls/busy_<SYM>` and the autopilot opens nothing new
  and leaves that position alone.
- Alerts: FILLED / TP1 HIT / TP2 HIT / STOPPED to the approved Telegram chat with the auto-trade footer; practice mode labels
  them "PRACTICE TRADE, no real money". Never post balances publicly.

## Testing and journaling
- Test the path with a far-off dummy call (`test: true`, entry far from price) and a cancel before the first real call.
- Journal the real fill and exit from the executor log next to the call's paper result, and feed both into the
  self-improvement loop (`btc-gold-setup-calls`).
