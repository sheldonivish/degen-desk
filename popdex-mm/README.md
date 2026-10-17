# PopDEX BTC market maker (volume bot)

Keeps one small post-only bid and one ask on PopDEX BTCUSDT perps, leans its quotes against its own inventory and
takes small spreads to build **volume**. It is a cost centre, not a profit engine: on BTC the spread is usually
tighter than the maker fee, so expect to pay roughly the maker fee plus small adverse-selection losses
(about $8 to $35 per $100k of volume depending on VIP tier and volatility). Not financial advice.

## Modes
- **shadow** (default, `config.json` mode "shadow"): public WebSocket feed only, simulated queue-aware fills, no key.
- **live**: `mode: "live"` **and** env `POPDEX_LIVE=1` (systemd drop-in `live.conf`). Anything else refuses to start.

Path to live, one owner "yes" per step: shadow 24-48 h -> agent key approved by the owner (`live_prep/APPROVE_AGENT.md`)
-> one tiny test order placed and cancelled (`test_order.py`) -> live with a volume target and a cost cap.

## Live guardrails (shared account safe)
- Post-only quotes (tif 4); tick 1.0, lot 0.0001 BTC, $10 min notional checked before every send.
- clientOrderId is **ASCII text** `DDMM<ms hex><random hex>`, zero-padded to 32 bytes (raw bytes are rejected on-chain).
- Touches only its own DDMM orders. Never cancelAll / closeAll, never reduce-only (one-way accounts net per symbol).
- Fills come from the exchange (order history + open orders, filledQty deltas), not from the WebSocket guess.
- Reconciles the account BTC position vs its own ledger every 30 s: 2 mismatches -> pause (a manual BTC trade).
- Margin floor (`min_avail_margin_usd`), daily loss cap, `run_cost_cap_usd` (halt), `volume_target_usd`
  (cancel quotes, unwind own inventory with post-only orders, then DONE), STOP file, SIGTERM cancels own quotes.

## Files
`mm.py` engine · `live.py` live executor + guards · `live_prep/adapter.py` signing (agent key, ms-timestamp nonce,
gas price 0) · `live_prep/order_params.py` orderParams packer · `live_prep/approve_agent.py` agent key + approval page ·
`test_order.py` one-time test order · `config.example.json` · `../vps/systemd/degen-popdex-mm.service` + `popdex-mm-live.conf`.

Setup on the server: `python3 -m venv .venv && .venv/bin/pip install websockets web3 eth-account`, copy
`config.example.json` to `config.json`, start the service in shadow mode, read `data/status.json`.
Fee math: cost per $100k = 100000 x maker_fee + markout loss. Keep `data/rec_*.jsonl` recordings 7 days (cron in `../vps/`).
