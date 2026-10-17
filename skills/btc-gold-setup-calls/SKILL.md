---
name: btc-gold-setup-calls
description: >-
  Use when the owner asks for BTC or gold (XAU) trade setups/calls, or when the
  30-minute call-tracking routine fires: find clean multi-timeframe setups, post
  them with mandatory reasoning to chat and the approved Telegram groups, and
  post TRIGGERED / TP HIT / STOPPED / CANCELLED updates for open calls.
---
# BTC and gold setup calls

Calls are research and education by default. They become real orders only when the owner has turned on live auto-execution (`lighter-call-autoexec`); then every call is real money. Other trading goes through `lighter-perps` with explicit approval.

## Finding a setup
1. Read structure top-down on public candles (BTC: Hyperliquid/OKX; gold: XAU perp or spot feed): 4h bias (last broken high/low, higher-low or lower-high), 15m pullback into a zone, 1-3m confirmation (structure flip).
2. Only call a **clean** setup: clear 4h bias, a defined pullback zone, a confirmation trigger, stop beyond the zone, at least ~2R to TP1. If nothing is clean, say "no trade" plainly. Never force a call.
3. Gold: the backtested BTC rules lose money on gold. Gold calls are judgment calls and must say so. Weekend: the market is closed; give a conditional plan for the reopen instead.

## Every call must include (mandatory)
- Direction and whether it's conditional (wait for dip + confirmation) or active.
- Entry (zone + trigger), stop, TP1 (partials; move stop to breakeven unless aggressive mode is on), TP2, approximate R for each.
- **Reasoning:** the higher-timeframe bias and why, which setup it is, why the entry, stop and targets sit where they do (zones, highs/lows, liquidity).
- Invalidation ("skip it if ...") and the main risk (thin weekend volume, news, chop).
- "Not financial advice."

## Posting
1. Post in chat, then to Telegram with `telegram/trade_signal.py --status NEW --setup ... --reason ... --send` and `SIGNAL_FOOTER="Manual call · Not financial advice"` (see `telegram-report-delivery`). It goes to the approved groups only.
2. Record each call (id, time, instrument, side, entry zone, stop, TPs, invalidation, expiry, status) in a calls log file so the tracker can follow it.

## 30-minute tracker (routine)
1. Load open calls. For each, read candles since the last check (closed bars only):
   - entry zone hit with confirmation -> **TRIGGERED**; TP1/TP2 reached -> **TP HIT** (state R); stop reached -> **STOPPED**; invalidation or expiry before entry -> **CANCELLED**. If stop and target hit inside one bar, assume the stop.
2. Post each status change once (chat + Telegram card: `--status FILLED` for TRIGGERED, else `TP HIT`/`STOPPED`/`CANCELLED`, with `--exit` and `--r-multiple`), update the log, never repost an unchanged status.
3. Then look for one new clean BTC or gold setup and post it per the rules above.
4. If nothing changed and there's no new setup, stay silent.

## Live scorecard
- Every closed call in `/workspace/calls/open_calls.json` must carry `r` (R multiple at exit: stop = -1, BE after TP1 = R banked on partials, TP2 = blended R). CANCELLED/NOT_TRACKED keep `r` absent.
- After any status change is recorded, run `python3 /workspace/calls/scorecard.py sync` (also fills 24h/7d returns for trenches picks). It writes `/workspace/calls/scorecard.json`.
- Weekly recap (win rate, total R, best/worst for calls; 24h up-rate, avg, best/worst for picks): `python3 /workspace/calls/scorecard.py sync && python3 /workspace/calls/scorecard.py recap --out /workspace/calls/recap_latest.md`. It only prints/writes; sending to Telegram is a separate, approved step.

## Aggressive mode (when the owner turns it on)
- Minimum reward is 1.5R to TP1, down from 2R.
- Entry: take the 3m structure break straight away, with no wait for the 15m two-candle pullback. Keep the 4h bias filter and the stop beyond the last swing.
- Runners: take partials at TP1 but do NOT move the stop to breakeven; hold the rest to TP2 or the original stop.
- Risk per trade: the owner's setting (e.g. 2%); state it on each call.
- Still no repeats: one call per zone and direction, and no re-entry in a zone that just stopped out.

## Self-improvement loop
- After every call closes (TP, stop or cancel), write a short post-mortem in /workspace/calls/LESSONS.md: what the setup was, what price actually did, whether it was a fakeout or stop hunt, and one concrete lesson.
- Before posting any new call, read LESSONS.md and check the setup against every active rule there. If a lesson says skip, skip.
- Post-mortem template: call id, setup type, market, session, entry/stop/TPs, what price did (MFE/MAE in R), fakeout or stop hunt?, filled live or not (and the real fill vs the call), result in R, one lesson.
- Keep LESSONS.md in sections: Active rules (checked before every call), Post-mortems (newest first), Stats by setup / market / session (filled, wins, net R). Re-rank setups weekly from the stats and say in the weekly scorecard what changed.
- When the same mistake shows up twice, promote it to a hard rule in the Active rules section of LESSONS.md.
- Track results by setup type, market and session in LESSONS.md, and favor the setups that are working.

## Live auto-execution (when the owner turned it on)
When live auto-execution is on, every BTC and XAU call is also a real order placed by the VPS call executor; follow
`lighter-call-autoexec` for delivery, sizing and alerts. Server, account and chat details live in memory, not here.
- Write every call to the call log (id, instrument BTC-USDT-SWAP / XAU-USDT-SWAP, side, entry, stop, tp1, tp2, expiry ISO,
  status NEW) within 10 min of posting; `trade_signal.py --send` starts the push watcher. Status CANCELLED/EXPIRED/INVALIDATED
  sends a cancel; changed levels on a NEW call re-place it; a changed stop on a filled call moves the exchange stop.
- Every tracker run starts with `push_calls.py sync`. Any `ALERT` line or exit code 2 is a blocker: report it in chat.
- Expect real risk at or below the call's stated risk (leverage caps, 4% total open-risk cap); unfilled entries cancel at
  expiry or when price tags TP1 first. One position per market: calls take priority over the autopilot.
- Keep posting the manual call cards; the executor posts the FILLED / TP1 / TP2 / STOPPED auto-trade cards. Journal the real
  fill and exit too, and use them in the post-mortem.
