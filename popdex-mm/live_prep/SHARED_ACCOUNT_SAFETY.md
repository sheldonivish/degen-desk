# Shared-account rules for the PopDEX MM (live)
- Allocation: mm_alloc_usd = 1000 (config). Daily loss cap, inventory cap and sizing are computed vs this, not account equity.
- Own inventory only: MM inventory = sum of fills on orders whose clientOrderId starts with "DDMM" (adapter.TAG),
  from the fill WS channel / order fills API. It never reads the account position to decide size.
- Never call cancelAllOrders or closeAllPositions. Cancel only by our own clientOrderId (adapter.cancel_own refuses others).
- The account is ONE-WAY mode (GET /config/position-mode = Oneway), so a BTCUSDT position is netted per symbol.
  An MM fill on BTC would net against a manual BTC position, and a "reduce-only" MM order could shrink YOUR position.
  Rules: (1) MM never uses reduce-only; it flattens its own inventory with plain post-only orders sized from its own ledger.
  (2) Kill/stop on the MM only cancels MM orders and reports MM inventory; it does not flatten the account.
  (3) Before quoting, and every 30s, check positions: if BTCUSDT size != MM ledger inventory (tolerance 1 lot), a manual BTC
      position exists -> MM pauses, cancels its own orders, alerts. Do not hold manual BTC positions while the MM runs.
  Hedge mode exists (PositionMode.Hedge, positionSide byte[7]). Switching it likely affects the whole account
  and usually requires no open positions. Not recommended while you hold manual positions.
- Cross margin: MM losses come out of the same collateral that backs the manual positions, and vice versa.
  Margin guard: pause if account availableMargin < 2x MM max notional, or if any position's liq distance shrinks fast.
