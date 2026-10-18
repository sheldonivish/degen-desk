# Arcus BTC-USD scalping backtest (research only, no orders placed)
Run 2026-10-18.

## Verdict
**None of the 5 scalping families has an edge on BTC after Arcus costs. Do not trade any of them, not even in practice mode as a candidate.**
- 12,672 configurations tested. **0** pass the IS rule (>=150 trades, PF>1.05, >=3 of 4 half-year IS periods positive).
- **0** configurations are profitable in both IS and OOS.
- Nothing that trades >=1/day reaches IS PF 1.0 (best 0.998, Asia session fade).
- Walk-forward (12-month train -> next quarter, 5 folds Jul 2025 - Oct 2026): 3 families never had a single trainable (PF>1) config; session fade lost in all 5 folds (PF 0.72, -56.6R total); sweep reclaim lost its only fold (PF 0.46).
- Even with optimistic touch fills, no slippage and **zero fees**, OOS PF is 0.80-1.01 -> the signals themselves have ~no edge on recent data; costs + adverse selection of maker fills then make it clearly negative.
- Same conclusion as the earlier Lighter scalp rounds (scalp3: 21.7k configs, nothing survived OOS). The only BTC setup that has held up is the slower course book (A+G+RIMC, ~2.4 trades/week, OOS PF 2.47 on Lighter) -> recommended for Arcus instead (re-check with Arcus taker fee 0.0214% on stops).

## Data & split
- Binance USD-M BTCUSDT 1m, 2024-07-01 -> 2026-10-16 23:59 UTC , 1.21M bars, no gaps (cache + daily archives to 16 Oct).
- IS 2024-07-03 -> 2026-03-31 (21 mo); OOS 2026-04-01 -> 2026-10-16 (6.5 mo). Selection on IS only.
- No tick data: Arcus candles are oracle-price based (not trades) and its trade history is short, so fills use Binance 1m with a trade-through rule. Arcus BTC book is thinner (~$40M/day), so real fills would likely be worse.

## Execution model (engine.py)
- Post-only limit entry placed after the signal bar closes; fills only if price trades THROUGH by 1 bp; cancelled if TP reached first or after expiry.
- TP = maker limit (trade-through 1 bp, never on the fill bar). Stop = taker, gap-aware, +1 bp slip. Time stop = taker at close.
- Fees: maker 0, taker 0.0214% (225 ppm less 5% referral). Stress: 2 bp slip + 2 bp trade-through.
- 1% risk/trade, 10x notional cap, min 0.0001 BTC, one position at a time, -4R daily stop. ~$200 start.

## Best-IS config per family (by IS Sharpe, >=150 IS trades), compounding from ~$200
| family | IS trades | IS tr/day | IS win | IS avgR | IS PF | IS ret | IS maxDD | IS Sharpe | OOS trades | OOS tr/day | OOS win | OOS avgR | OOS PF | OOS ret | OOS maxDD | OOS Sharpe | OOS PF touch-fill | OOS PF no-cost |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| VWAP/BB fade (range) | 290 | 0.46 | 43% | -0.16 | 0.70 | -38% | -48% | -2.0 | 130 | 0.65 | 38% | -0.26 | 0.55 | -29% | -33% | -3.8 | 0.76 | 0.95 |
| 1m/5m EMA pullback | 3178 | 4.99 | 37% | -0.06 | 0.92 | -88% | -92% | -2.0 | 1005 | 5.05 | 34% | -0.15 | 0.81 | -79% | -80% | -5.0 | 0.90 | 0.98 |
| Range-break retest | 799 | 1.25 | 32% | -0.05 | 0.91 | -37% | -48% | -0.7 | 181 | 0.91 | 30% | -0.13 | 0.80 | -23% | -25% | -1.6 | 0.89 | 0.94 |
| Session-open fade (Asia) | 155 | 0.24 | 54% | +0.05 | 1.09 | +7% | -9% | +0.4 | 56 | 0.28 | 32% | -0.38 | 0.50 | -19% | -22% | -3.4 | 0.71 | 0.80 |
| Liquidity-sweep reclaim | 505 | 0.79 | 30% | -0.04 | 0.94 | -24% | -37% | -0.4 | 161 | 0.81 | 25% | -0.27 | 0.72 | -36% | -45% | -2.9 | 0.84 | 1.01 |

Params: results/final_table.csv. Counts per family: results/family_counts.csv. Walk-forward: results/wf_summary.csv, results/wf_picks.csv. Full grids: results/grid_*.csv.

## Why it fails
- Tight 1m-ATR stops: taker fee + 1 bp slip on a ~7-15 bp stop costs 0.2-0.45R per loser. Gross (no fee/slip) avgR is negative in 100% of VWAP-fade and EMA-pullback configs anyway.
- Maker entries are adversely selected: the limit fills mainly when price keeps going through it.
- Wider stops (6-8x 1m ATR) cut cost per R but the signals revert to ~zero edge (PF ~0.9-1.0 before costs on OOS).

## Recommendation for the Arcus bot
1. Don't run a scalper. Use the Arcus bot to execute the existing course-rule BTC calls / slower autopilot book in practice mode first (1% risk, 10x cap), re-validated with Arcus fees.
2. If the user still wants a high-frequency component, the only cost-positive option is pure maker volume (0% maker fee) like the PopDEX MM, but that is a volume tool, not a profit strategy, and on Arcus inventory risk is uncompensated (no maker rebate below VIP).
