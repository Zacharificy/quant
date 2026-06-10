# Profitability Research Plan

This note is the practical research map for improving the Alpaca paper bot. It does not claim any strategy will be profitable. It lists return drivers that are reputable enough to test, and the bot changes that would be needed before considering live trading.

## Reputable Return Drivers To Test

### 1. Time-Series Momentum

Source idea: Moskowitz, Ooi, and Pedersen documented trend-following behavior across liquid asset classes.

Bot translation:

- Prefer long stock/call trades when the ticker is above its own medium/long moving averages.
- Prefer put trades only when the ticker is below its own medium/long moving averages.
- Do not trade against the market regime unless explicitly testing mean reversion.
- Volatility-scale position size so high-volatility names receive smaller sizing.

Bot upgrade candidate:

- Replace raw fixed sizing with ATR/volatility-based sizing.
- Add a portfolio-level cap per directional regime: bullish, bearish, neutral.

### 2. Cross-Sectional Factors

Source idea: Fama and French showed broad stock returns have common risk factors; AQR and related research popularized multi-factor portfolios such as value, momentum, quality, and low volatility.

Bot translation:

- Avoid ranking only by chart breakout.
- Add a simple cross-sectional score:
  - momentum: 3 to 12 month return
  - quality/profitability proxy: positive operating trend if data is available
  - low volatility: avoid extreme ATR names
  - liquidity: average dollar volume gate

Bot upgrade candidate:

- Keep the current technical score, but add a second "portfolio score" that ranks tickers against each other.
- Only buy the best 1-3 candidates instead of any ticker that clears a threshold.

### 3. Volatility Risk Premium

Source idea: Cboe option-writing benchmark research and AQR volatility risk premium research show that option sellers may earn compensation for providing crash insurance, but with large tail risk.

Bot translation:

- Long options are hard because theta and bid/ask spreads work against the bot.
- The current bot buys calls/puts, so it should be selective: only trade options when directional score is strong and spread is tight.
- Selling options should not be added until the bot has strong risk controls, assignment handling, and capital rules.

Bot upgrade candidate:

- For now, keep options as long-only calls/puts.
- Add implied-volatility and spread discipline before buying options.
- Add a "do not buy options when spread is too wide or DTE too short" rule, already partly implemented.

### 4. Overfitting Controls

Source idea: Bailey and Lopez de Prado show that repeated backtest selection can manufacture false positives. Lopez de Prado's financial ML work emphasizes proper out-of-sample testing.

Bot translation:

- Do not keep loosening scanner rules just because the bot "did not trade today."
- A strategy that trades more is not automatically better.
- Any researched setting needs train/test split, walk-forward testing, transaction costs, and a minimum trade count.

Bot upgrade candidate:

- Add a research report that marks strategies as "candidate" only if:
  - at least 30 trades
  - positive out-of-sample return
  - max drawdown below threshold
  - profit factor above threshold
  - not dependent on one huge trade

## Priority Bot Changes

1. Volatility-based sizing. Implemented for stock entries using ATR stop distance and a target cash risk per trade.
2. Rank candidates cross-sectionally instead of threshold-only selection. Implemented for stock and option scans using signal score, medium-term momentum, and volatility discipline.
3. Add portfolio correlation/sector concentration guard. Implemented as simple ticker risk buckets with a max positions per bucket guard.
4. Add better option selectivity: DTE, spread, liquidity, and no same-day expiry. Partly implemented with DTE, spread, max premium, and explicit 1-contract sizing.
5. Improve backtest/research harness before adding more signals.
6. Keep the dashboard simple: show risk, positions, orders, daily guard, and last scan reason.

## Latest Implementation Check

- Option buy orders are built as buy-to-open limit orders with contract quantity, not share quantity.
- Option sell orders are built as sell-to-close limit orders with contract quantity, not share quantity.
- Cash math uses the 100x option contract multiplier separately from the Alpaca order quantity.
- Preview scans can rank stock and option candidates without submitting orders.
- Dashboard shows current risk bucket counts.
- Research runner now uses ranked candidates, volatility sizing, bucket limits, and a benchmark comparison.

## What Not To Add Yet

- No neural network or "AI learns every trade" logic until there are enough real closed trades.
- No naked short options.
- No external news scraping unless the source is reliable and terms/API are stable.
- No auto-optimization directly connected to order execution.
