# Lighter on Robinhood Chain: market maker (shadow mode only)

Lighter on Robinhood Chain (`api.rh.lighter.xyz`) is a separate deployment from regular Lighter: own chain,
USDG collateral, separate accounts and API keys. Markets are mostly tokenized stocks/stock perps plus BTC.

**Phase 1 is shadow-only.** The bot reads the real order book, simulates post-only two-sided quotes and fills,
and records markouts. It places no orders. `--live` exists only as a guarded stub that raises; real order
placement is intentionally not implemented until shadow results justify it and the owner approves.

    cp config.example.json config.json          # edit markets/sizes; leave account fields null for shadow
    python3 mm.py --feed ws                      # websocket feed (preferred)
    python3 mm.py --feed poll                    # REST polling fallback (slower; results less reliable)

Status: `data/status.json` · recordings: `data/rec_*.jsonl` · stop: `touch STOP` or Ctrl-C.

Quoting: inventory-skewed quotes around mid, spread = max(fee + buffer, vol_k x short-term vol), requote
threshold, per-market and total exposure caps, max leverage. Guardrails: daily loss limit (cancel all + stop),
stale-feed stop, reject counter, STOP file.

Going live later (not implemented): needs `--live --feed ws`, a dedicated API key stored in the OS keychain
(never in files or chat), account and key indexes in config.json, a funded USDG account, and tiny size.
Some regions are blocked by the exchange; never use a VPN or proxy to get around that.
