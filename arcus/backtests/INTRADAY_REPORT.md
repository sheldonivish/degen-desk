# Arcus BTC intraday (5m/15m) backtest — research only, no orders
Run 2026-10-18. 

## Verdict
**None of the 5 new 5m/15m setups has a robust edge on Arcus costs. The existing BTC autopilot book (A+G+RIMC) does, and it survives Arcus fees -> use that for the Arcus bot (practice mode first).**
- 1,716 new configs. Only the 15m Donchian breakout passed the IS rule (13 configs) and **all 13 failed OOS** (best OOS PF 0.77). Walk-forward: every family negative overall (Donchian closest: PF 0.97, -6R).
- London opening-range retest had OOS PF 1.62 (+35%) but IS PF 0.99 and WF -> regime luck, not evidence. Don't trade; at most watch in practice.
- Autopilot with Arcus taker 0.0214% + 1 bp slip, 1% risk, 10x cap: OOS Apr 1 - Oct 9 2026 57 trades, PF 2.07, +41%, max DD -3.8%, Sharpe 2.8. Its *true* OOS (after its selection window, Jun 19 - Oct 9) 39 trades, PF 2.30, +32%, DD -3.8%. With 4 bp slip PF still 1.94. 8 of 9 quarters since Jul 2024 positive (Q3 2025 flat: PF 1.0, 0.84 at 4 bp).

## Setup
- Data: Binance USD-M BTCUSDT 1m Jul 2024 -> 16 Oct 2026 resampled to 5m/15m/1h/4h; signals only on closed bars; executed on 1m.
- IS 2024-07-08 -> 2026-03-31, OOS 2026-04-01 -> 2026-10-16; IS rule: >=80 trades, PF>1.1, >=3/4 half-years positive, rank IS Sharpe.
- Walk-forward: 12-month train -> next quarter, 5 folds (Jul 2025 - Oct 2026), pick best trailing Sharpe with >=40 trades and PF>1.
- Costs: maker 0, taker 0.0214%; market entries next 1m open +1 bp; limits fill only on 1 bp trade-through; stops taker +1 bp. Stress: 3 bp slip + 2 bp trade-through.
- 1% risk, 10x cap, ~$200 compounding, one position, -4R daily stop.

## Results (best-IS config per family; ~$200 compounding)
| strategy | IS tr/wk | IS win | IS avgR | IS PF | IS ret | IS maxDD | IS Sharpe | OOS tr/wk | OOS win | OOS avgR | OOS PF | OOS ret | OOS maxDD | OOS Sharpe | OOS stress PF | WF trades | WF tr/wk | WF PF | WF sum R |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 15m trend + 5m EMA pullback | 19.3 | 36% | -0.03 | 0.96 | -47% | -71% | -0.6 | 19.6 | 34% | -0.10 | 0.87 | -44% | -52% | -2.2 | 0.78 | 261 | 3.9 | 0.80 | -37.8 |
| 15m range-break retest | 5.8 | 31% | +0.06 | 1.07 | +24% | -29% | 0.6 | 5.2 | 23% | -0.27 | 0.65 | -34% | -38% | -2.9 | 0.61 | 381 | 5.6 | 0.71 | -86.0 |
| 15m sweep reclaim + 4h bias | 3.1 | 34% | +0.03 | 1.02 | +3% | -19% | 0.2 | 3.4 | 32% | -0.29 | 0.64 | -25% | -30% | -2.5 | 0.55 | 62 | 0.9 | 0.46 | -28.4 |
| London/NY opening-range breakout | 3.3 | 37% | 0.00 | 0.99 | -2% | -20% | 0.0 | 3.1 | 49% | +0.35 | 1.62 | +35% | -6% | 3.0 | 1.41 | 175 | 2.6 | 0.83 | -20.6 |
| 15m Donchian/ATR breakout (passed IS) | 3.9 | 39% | +0.12 | 1.19 | +44% | -14% | 1.2 | 3.9 | 36% | -0.14 | 0.76 | -15% | -18% | -1.6 | 0.69 | 407 | 6.0 | 0.97 | -6.0 |
| **Autopilot A+G+RIMC (Arcus fees, 1 bp)** | 2.1 | 35% | +0.32 | 1.44 | +78% | -9.8% | 1.6 | 2.1 | 46% | +0.63 | 2.07 | +41% | -3.8% | 2.8 | 1.81 (4 bp) | fixed config, no re-fit; 8/9 quarters positive | | | |

Autopilot IS shown for Jul 2024 - Mar 2026 (full Feb 2022 - Mar 2026: 264 trades, PF 1.41, +106%, DD -19%, Sharpe 1.1). Autopilot data ends Oct 9 (research2 cache). Quarterly table: results/autopilot_arcus.csv.
Params: results/final_table.csv; WF picks: results/wf_picks.csv; grids: results/grid_*.csv.

## Recommendation
1. Arcus bot = port the autopilot book (A+G+RIMC) with Arcus fees, practice mode first, 1% risk, 10x cap (cap never binds: median stop ~0.47%), ~2 trades/week. At ~$200 equity: ~$1.97 risk, ~$420 notional/trade, well above the 0.0001 BTC minimum.
2. Must not double-trade with the Lighter autopilot on the same signals unless the user wants both venues; keep a cross-venue open-risk cap.
3. No new 5m/15m setup is worth adding. Optionally log the London ORB retest in practice only, as a watch item.
4. Caveats: Binance prices, not Arcus (Arcus book thinner, oracle-based marks); live entries/stops are taker, so real slippage may sit between the 1 and 4 bp cases.
