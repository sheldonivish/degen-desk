# Arcus backtests (Oct 2026, research only)
Binance USD-M BTCUSDT 1m, Jul 2024 – Oct 2026; Arcus fees (maker 0, taker 0.0214%); 1% risk, 10x cap, one position.
- [`SCALP_REPORT.md`](SCALP_REPORT.md): 5 scalping families, 12,672 configs → **no edge** (0 pass in-sample, walk-forward negative).
- [`INTRADAY_REPORT.md`](INTRADAY_REPORT.md): 5 new 5m/15m families, 1,716 configs → **no robust edge**; the existing
  autopilot (A+G+RIMC) survives Arcus fees: OOS PF 2.07, +41%, DD −3.8% (PF 1.94 at 4 bp slip).
Verdict: run the autopilot on Arcus, not a scalper. "results/*.csv" mentioned inside the reports are not shipped.
