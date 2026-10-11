# Autopilot research summary (BTC on Lighter)

Backtests on BTC 1m data since 2022 (in-sample + out-of-sample, 3x leverage cap, fees/slippage modeled):

- **Keep the autopilot at setups A + G + RIMC on BTC only.** No additional setup tested added trades without weakening the edge.
- **Scalping (1m-5m) does not hold up** after costs out of sample. Not shipped.
- **Gold (PAXG history and the XAU perp) loses money** with the same rules and none of the tested settings fixed it
  (recent-window profit factor ~0.6 vs ~2.5 for BTC). Gold calls, if any, are discretionary and labelled as such.
- **ETH** also failed with the BTC parameters.
- Partial-profit management did not meaningfully beat single fixed targets.
- Risk: keep 1% per trade (hard ceiling 2%); at 2% the in-sample max drawdown can trip the 15% drawdown pause.

Past performance does not predict future results. Not financial advice.
