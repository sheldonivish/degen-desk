# Arcus BTC autopilot (optional, runs on your own VPS)

The Degen Desk BTC autopilot (setups A + G + RIMC, the same logic as `autopilot/` for Lighter) trading **BTC-USD perps on
[Arcus](https://arcus.xyz)** (dYdX Labs, Robinhood Chain, collateral USDG). Practice mode (`--dry-run`) by default; live only
when you switch it yourself. No key, wallet, IP or account id is stored in this folder. Not financial advice.

Docs: https://docs.arcus.xyz · REST `https://api.arcus.xyz` · WS `wss://api.arcus.xyz/v1/ws` · testnet `api.testnet.arcus.xyz`.

## Files
| File | What |
|---|---|
| `autopilot.py` | the loop: signals on closed 1m bars, sizing, guards, reconciliation, `status/pause/resume/stop/start` |
| `exchange_arcus.py` | Arcus adapter: Ed25519 signing, setLeverage, IOC/entryTpsl/positionTpsl orders, scheduleCancel, reads |
| `exchange.py` | PaperExchange (practice), Meta, log redaction |
| `trade_signal.py` | Telegram chart cards with the "Arcus" headline |
| `config.default.json` | defaults (Telegram off; set your own approved chat id) |
| `setup.sh` | assembles `/opt/arcus-desk` from this folder + `../autopilot` (strategy, course engine, feed, notify) and a venv |
| `systemd/degen-arcus.service`, `systemd/arcus-live.conf` | practice unit + the live drop-in |
| `backtests/` | scalping, 5m/15m and autopilot-on-Arcus-fees summaries |

## Setup
1. VPS per [`vps/README.md`](../vps/README.md). Run `vps/geo_check.sh`: Arcus `/health` and `/v1/markets` must answer 200 and
   your location must be allowed by the Arcus Terms (restricted: US, Canada, UK, sanctioned regions). Never use a VPN.
2. At app.arcus.xyz/api-keys create an API key for **one subaccount**, valid up to 180 days. It is an Ed25519 pair: the
   "API Key" is the public half, the "API Signing Key" the private half (shown once). Trading needs the signing key, your
   wallet address and the subaccount index. Rotate it before it expires.
3. `sudo bash arcus/setup.sh`, then write `/opt/arcus-desk/.env` (chmod 600, owner `degen`):
   `ARCUS_API_KEY=`, `ARCUS_SIGNING_KEY=`, `ARCUS_ADDRESS=`, `ARCUS_ACCOUNT_INDEX=`. Optional `telegram.env` with `TELEGRAM_BOT_TOKEN=`.
4. `cp arcus/systemd/degen-arcus.service /etc/systemd/system/ && systemctl daemon-reload && systemctl enable --now degen-arcus`.
   It starts in practice: PaperExchange on live data, signing key stripped from the environment, Telegram off.
5. Live (your decision): install `arcus-live.conf` as `/etc/systemd/system/degen-arcus.service.d/live.conf`, restart. Run one
   live copy per account only.

## Settings (`config.json`; hard caps in code)
- 1% equity risk per trade (hard cap, config can't raise it), leverage cap 10x, exchange leverage set to 10x cross with a
  signed `setLeverage` at startup and before every entry (accounts often default to the exchange max).
- One position. Margin floor (free collateral after initial margin ≥ `margin_floor_usd`). Daily loss stop −3% (UTC day),
  drawdown pause −10% from peak (manual `resume`). Max hold 24 h. Entry slippage cap 10 bp, stop worst fill 0.5%, basis guard
  0.3% (Arcus mid vs the Binance candle feed).
- **Combined risk** with a Lighter desk on the same signals (`lighter_home`): total open risk ≤ `combined_risk_cap` (2%) of
  combined equity; Arcus size = min(1% equity, remaining budget). Unreadable or stale (>15 min) Lighter files → Lighter is
  assumed at its full 2%. `risk_ledger.json` is written every loop for the other desk to read.

## How orders work on Arcus (verified live)
- Signing: headers `X-API-Key`, `X-Timestamp` (ns, ±30 s), `X-Signature` (ed25519). Orders sign canonical compact JSON with
  price/size in integer ticks/steps; cancelAll/setLeverage/WS auth sign timestamp + action + canonical body. Every order needs
  `goodTilTime` ≥ 1 month ahead (even IOC); MARKET must be IOC within 10% of mark. Placement is async (202).
- **Market setups (A, RIMC):** LIMIT IOC at ref ± 10 bp. Once the position shows (≤5 s) a `positionTpsl` batch goes out:
  SL = MARKET with stopPrice and a ±0.5% price bound, TP = LIMIT; reduce-only, size "0" (whole position), auto-cancel when
  flat. Stop not placed after 3 tries → close at market. `POSITION_TPSL_ALREADY_EXISTS` counts as protected.
- **G setup:** `entryTpsl` bundle (GTT limit entry + SL/TP children that cascade-cancel with the entry). Legs are non-atomic:
  a TP already past the oracle (wrong side) is **rejected → deferred and added right after the fill**. SL child rejected →
  entry cancelled.
- Every 10 s loop: reconcile the position, re-place a missing SL/TP, orphan positions get a 1.5% stop.
- **Dead-man switch:** `scheduleCancel` (deadline now+240 s, refreshed every 60 s) is armed **only while a G limit rests and
  no position is open** (it would also cancel the position's SL/TP). Arcus allows ~10 auto-fires per UTC day.
- Single instance via `autopilot.lock`. A `GEO_RESTRICTED` rejection pauses the bot.

## Commands
```bash
cd /opt/arcus-desk
sudo -u degen AUTOPILOT_HOME=/opt/arcus-desk ./venv/bin/python autopilot.py status   # equity, position, guards, trades
sudo -u degen AUTOPILOT_HOME=/opt/arcus-desk ./venv/bin/python autopilot.py pause    # no new entries (SL/TP stay)
sudo -u degen AUTOPILOT_HOME=/opt/arcus-desk ./venv/bin/python autopilot.py resume   # clear pause + reset DD peak
sudo -u degen AUTOPILOT_HOME=/opt/arcus-desk ./venv/bin/python autopilot.py stop     # KILL: close BTC, cancel orders
journalctl -u degen-arcus -n 50 ; tail -f /opt/arcus-desk/log.jsonl
curl -s "https://api.arcus.xyz/v1/account?address=<wallet>&accountIndex=<n>"        # public read check
```
Editing `config.json` + `systemctl restart degen-arcus` is safe with a position open (it reconciles; SL/TP live on the exchange).

## Troubleshooting
- `fatal` at start: key expired/revoked, Arcus unreachable or no candle feed (systemd retries every 15 s).
- `entry_aborted` "leverage update failed": a signed write failed; check the key via `GET /v1/apiKeys?address=`.
- `stop_replace_failed_closing`: the stop couldn't be re-placed, so the position was closed on purpose.

## Expectations (backtest with Arcus fees, 1 bp slip; see `backtests/`)
OOS Apr–Oct 2026: 57 trades, PF 2.07, +41%, max DD −3.8%; true OOS Jun–Oct: 39 trades (~2.4/week), PF 2.30 (1.94 at 4 bp
slip). About one signal every 2–3 days, gaps of a week possible. Scalping and new 5m/15m setups **failed** the same tests.
Past results don't guarantee future ones.
