---
name: arcus-autopilot
description: >-
  Use when the owner wants to trade BTC perps on Arcus (arcus.xyz, Robinhood Chain) with the Degen Desk
  BTC autopilot, asks about its status, keys, leverage, stops or risk, or asks for a scalper or 5m/15m
  strategy there: API key pair setup, signing, practice mode by default, live only on the owner's yes, 1% risk.
---
# Arcus BTC autopilot

Code: degen-desk repo `arcus/` (autopilot.py, exchange_arcus.py adapter, config.default.json, systemd template,
README runbook, backtests/). Runs 24/7 on the owner's own VPS per `vps-bot-deploy`. Not financial advice.
Docs: https://docs.arcus.xyz (index `/llms.txt`). REST `https://api.arcus.xyz`, WS `wss://api.arcus.xyz/v1/ws`;
testnet `api.testnet.arcus.xyz` (same paths and signing).

## 1. What Arcus is
- Perps DEX on Robinhood Chain: off-chain matching, non-custodial, collateral USDG. BTC-USD trades 24/7.
- Fees (base tier): maker 0, taker ~0.0225% (5% less with a referral code). Stops and market entries are taker.
- No spot gold: gold trades as GLD-USD (the ETF) in US market hours; its price is not XAU, so map levels by ratio.
- Geo: check `/health`, `/markets` and the Terms from the server first (restricted: US, Canada, UK, sanctioned).
  A `GEO_RESTRICTED` rejection is final: pause, never a VPN or another region.

## 2. Keys (owner creates them; collect only through the secure secret form)
- At app.arcus.xyz/api-keys the owner makes an API key for one subaccount (0-9), trade only, max 180 days.
- It is an Ed25519 pair: "API Key" = public half, "API Signing Key" = private half (shown once). Trading needs the
  **signing key** + the owner's **wallet address** + the **subaccount index**. No CEX-style secret or passphrase.
- Check offline that the private key derives to the public key, then `GET /v1/apiKeys?address=` for status and
  expiry. Remind the owner to rotate before expiry. Store as `ARCUS_API_KEY`, `ARCUS_SIGNING_KEY`, `ARCUS_ADDRESS`,
  `ARCUS_ACCOUNT_INDEX` in a chmod-600 `.env` on the server. Never print, log or commit them.
- Reads (`/v1/account`, `openOrders`, `fills`, `leverages`, `bbo`) are public by `?address=`; writes are signed.

## 3. Signing quirks
- Headers `X-API-Key` (public), `X-Timestamp` (ns, ±30 s), `X-Signature` (ed25519).
- place/cancel/modify: sign canonical compact JSON with price/size in integer ticks/steps. cancelAll, setLeverage,
  WS auth: sign timestamp + action + canonical JSON body.
- Every order needs `goodTilTime` ≥ 1 month ahead (even IOC). MARKET must be IOC within 10% of mark.
  Placement is async (202): confirm via `openOrders`/positions or WS `orders`/`userFills`.
- Verify signing with a harmless signed GET before any order. Respect rate limits (IP weight bucket; setLeverage
  is heavy; cancelAll costs a lot from the cancel pool).

## 4. Order handling (verified live)
- **Leverage:** don't trust the account default (often exchange max). Signed `setLeverage` to the cap (e.g. 10x
  cross BTC) at startup and again before every entry; abort the entry if it fails.
- **Market setups:** LIMIT IOC at ref ± ~10 bp. Once the position shows, send a `positionTpsl` batch: SL = MARKET
  with stopPrice and a worst-price bound; TP = LIMIT. Reduce-only, size "0" (whole position), auto-cancel when flat.
  Stop not placed after 3 tries -> close at market. `POSITION_TPSL_ALREADY_EXISTS` = already protected (OK).
- **Resting limit setups:** `entryTpsl` bundle (GTT entry + SL/TP children that cascade-cancel with the entry).
  Legs are non-atomic: **a TP already past the oracle (wrong side) is rejected -> defer it and add it right after
  the fill.** SL child rejected -> cancel the entry.
- Post-only (ALO) where possible for maker 0; never rely on it for stops.
- Every loop: reconcile the position from the account, re-place any missing SL/TP, protect orphan positions with a
  wide stop.
- **Dead-man switch** (`scheduleCancel`, per market, deadline ~240 s, refresh every 60 s): arm only while a limit
  entry rests and no position is open. It would also cancel the position's SL/TP, so disarm once filled (protection
  is then the exchange SL/TP + systemd restart). Max ~10 auto-fires per UTC day.
- Single instance: file lock; a second `run` refuses to start.

## 5. Risk (defaults; hard caps in code)
- 1% equity risk per trade (hard cap; raising it needs a code change and the owner's explicit OK), leverage cap
  10x, one position, margin floor, -3% daily loss stop, -10% drawdown pause (manual resume), max hold 24 h,
  entry slippage cap, basis guard vs the candle feed.
- **Combined risk ledger:** if another desk (e.g. the Lighter autopilot or call executor) trades the same signals,
  cap total open risk across venues (e.g. 2% of combined equity). Each bot publishes `risk_ledger.json`; size =
  min(1% equity, remaining budget). Unreadable or stale (>15 min) other-venue files -> assume it is at its full cap.

## 6. Practice -> live
1. Deploy per `vps-bot-deploy` with `run --dry-run` (PaperExchange, signing key stripped, Telegram off) on live data.
2. Report status after a day: equity read, guards, any paper signals.
3. Live only when the owner says so for this account: set leverage, place one tiny test trade (~0.0001 BTC) to
   confirm SL/TP attach, then switch ExecStart to `run --live`. One live copy per account.
4. Commands: `autopilot.py status | pause | resume | stop` (stop = close position, cancel orders, stay stopped).
   Changing config.json + restart is safe with a position open (it reconciles; SL/TP live on the exchange).
5. Trade cards only to the owner's approved Telegram chat; message the owner only on fills, exits, pauses, blockers.

## 7. What the backtests said (Oct 2026, Arcus fees, 27 months of BTC 1m data)
- **Scalping failed:** 5 families (VWAP/BB fade, EMA pullback, range-break retest, session-open fade,
  liquidity-sweep reclaim), 12,672 configs: 0 passed in-sample, 0 profitable in and out of sample, walk-forward
  negative. Tight stops make the taker fee + slip cost 0.2-0.45R per loser; maker entries are adversely selected.
- **5m/15m setups failed:** 5 families (trend pullback, range-break retest, sweep reclaim, London/NY opening-range
  breakout, Donchian breakout), 1,716 configs: nothing robust (the opening-range breakout's good OOS was luck: flat
  in-sample, negative walk-forward).
- **What held up:** the slower BTC autopilot book (A + G + RIMC, ~2 trades/week): OOS PF ~2.1, max DD ~-4%,
  PF ~1.9 with 4 bp slip. So if asked for a scalper on Arcus, show these results and recommend the autopilot.
  Past results don't guarantee future ones.
