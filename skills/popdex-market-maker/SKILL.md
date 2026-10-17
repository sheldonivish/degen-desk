---
name: popdex-market-maker
description: >-
  Use when the owner wants to build trading volume on PopDEX with a small BTC (or
  ETH) market-making bot, or asks about its cost, status or approval: shadow first,
  owner-signed trade-only agent key, one tiny test order, then live post-only quotes
  with a volume target and a cost cap, safe on an account the owner also trades.
---
# PopDEX volume market maker

Template: degen-desk repo `popdex-mm/` (README, mm.py, live.py, live_prep/), deployed per `vps-bot-deploy`.
Docs: https://popdex.xyz/docs (WebSocket, smart-contract Order/Account, agent-key, nonces). Not financial advice.

## 1. Set expectations (before building)
It costs money; it does not earn it. Maker fee (VIP 0 ~0.010%, lower at higher tiers) usually exceeds the BTC spread, so
cost per $100k = 100000 x maker_fee + adverse-selection loss: about $8 to $35 per $100k. Give the owner the math for
their volume goal (e.g. $1M ~ $100 to $350) and ask for a volume target and a fee budget.

## 2. Shadow (default)
Public WS (books5 + publicTrade), simulated post-only quotes with queue-aware fills, no key. Run 24-48 h on the server,
report volume, fills, fees, markouts and cost per $100k.

## 3. Agent key (owner signs, main key never leaves their wallet)
- Ask for the owner's PopDEX wallet address (public) and confirm the USDT deposit is credited.
- On the server: `approve_agent.py --gen` (new key, chmod 600, never printed; never reuse one), then `--html <wallet>` to
  render the approval page. Send it; the owner opens it in the browser with MetaMask/Rabby (serve it from localhost on their
  computer if the extension won't inject into file://), switches to Morph Tachyon chain 2184 (gasless, gas price 0) and
  confirms approveAgent. Verify via `GET /api/v1/account/<wallet>/agents`. The agent can trade but not withdraw; the owner
  can revoke anytime.

## 4. Shared-account safety (the owner may trade the same account)
- Check position mode (`/config/position-mode`). In one-way mode positions net per symbol: never use reduce-only, never
  cancelAll/closeAll, cancel only own orders by clientOrderId, flatten only own inventory with post-only orders.
- Tag every order: clientOrderId must be **ASCII text** (`DDMM` + ms hex + random hex, zero-padded to 32 bytes); raw bytes
  are rejected ("Client order ID format invalid").
- Own ledger only, from the exchange: fills = filledQty deltas of own orders in order history + open orders (not WS guesses).
- Reconcile account BTC position vs own ledger every 30 s; 2 mismatches -> pause + alert (a manual trade). Ask the owner not
  to trade BTC manually while it runs. Margin floor pause. Never touch their other positions.

## 5. Tiny test order (needs the owner's yes)
Before every send check tick (1.0), lot (0.0001 BTC) and min notional ($10): the smallest valid order is 0.0002 BTC.
`test_order.py`: one post-only buy ~5% below the bid, confirm it rests, cancel by own id, confirm positions unchanged.
A rejected order creates nothing: read the revert reason, fix, and ask before retrying.

## 6. Live (owner says "go live")
- Config: `mode: live`, `mm_alloc_usd` (sizing/loss caps vs this, not account equity), `order_usd` small to start
  ($50, then $100 a side after clean fills), `inv_cap_usd`, `daily_loss_pct`, `volume_target_usd`, `run_cost_cap_usd`
  (~2x the expected cost), `maker_fee` = their tier, `live_run_start_ms` = now. Install the `POPDEX_LIVE=1` drop-in, restart.
- At the target it cancels quotes, unwinds own inventory with post-only orders and stops (DONE); cost cap -> halt.
- Watch the first fills closely, then check every couple of hours and message only on DONE, pause, halt or losses past a
  threshold the owner agreed. Report volume, P&L incl. fees and cost per $100k.
