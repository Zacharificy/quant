# Quant Trading Research Notes

These notes translate the Roman Paolucci / Quant Guild style ideas into a practical bot roadmap for this Alpaca paper project.

## Core Ideas

1. Optimize for survival before profit.
   A bot that can place trades but cannot cap risk, exit positions, or detect bad state is not a trading system yet. It is an order sender.

2. Geometric growth matters more than pretty win rate.
   A strategy can have positive average returns and still compound poorly if the path is volatile. Large drawdowns hurt compounding more than most beginners expect.

3. Diversification should be structural, not just more tickers.
   Holding many tech tickers is still mostly one risk bet. A better system separates return drivers, such as trend, mean reversion, volatility, cash, and hedges.

4. Options need contract-aware risk.
   One option contract controls 100 shares. Premium risk is `contracts * premium * 100`. Greeks and expiration risk matter even for long-only options.

5. Backtests are research, not proof.
   A good backtest must include position sizing, bid/ask, slippage, option contract availability, cash limits, survivorship bias checks, and out-of-sample testing.

## Strategy Sleeves To Build

### Sleeve 1: Equity Momentum

Purpose: capture broad risk-on trends.

Rules to research:

- Universe: liquid ETFs and large-cap names only.
- Entry: price above medium/long moving averages, improving momentum, volume confirmation.
- Exit: ATR stop, trend failure, time stop.
- Position sizing: fixed dollar cap, volatility-adjusted share count.

Why it belongs:

- Simple.
- Easy to paper test.
- Lower operational complexity than options.

### Sleeve 2: Equity Mean Reversion

Purpose: trade short-term overreaction in otherwise liquid names.

Rules to research:

- Only trade names with enough average volume.
- Look for oversold RSI or downside move into support.
- Require broad market not collapsing.
- Exit faster than momentum trades.

Why it belongs:

- Can behave differently from breakout momentum.
- Gives the bot a second return driver.

### Sleeve 3: Long Options Directional

Purpose: defined-risk convex bets.

Rules to research:

- Buy calls only when bullish score is strong and spread is tight.
- Buy puts only when bearish score is strong and spread is tight.
- Avoid very short DTE until execution is proven.
- Cap contracts per trade.
- Exit on profit target, stop, time decay, or signal flip.

Why it belongs:

- Risk is capped at premium paid.
- Convex payoff can help when movement is large.

Main danger:

- Repeated small premium losses can bleed the account.

### Sleeve 4: Hedge / Volatility Drag Control

Purpose: reduce portfolio crash risk and improve compounding path.

Possible research:

- Keep cash when broad market regime is weak.
- Use tiny put exposure only during high-risk market regimes.
- Use risk-off mode to stop new longs and tighten exits.

Why it belongs:

- This is closest to the volatility-drag theme in Roman's note.
- The goal is not to predict every crash, but to avoid letting one market regime destroy the account.

## Bot Architecture

The bot should have these layers:

1. Data layer
   Fetch prices, option chains, quotes, account, positions, orders, and news.

2. Signal layer
   Score bullish, bearish, and neutral/no-trade conditions.

3. Portfolio layer
   Decide which sleeve gets risk today. Enforce max total exposure.

4. Risk layer
   Stop duplicate orders, cap contracts, cap cash, block risky dates/news, and trim oversized positions.

5. Execution layer
   Submit orders only after the risk layer approves them. Prefer limit orders for options.

6. Journal layer
   Record every entry, exit, reason, price, quantity/contracts, and P/L.

7. Research layer
   Run experiments offline. Promote settings only if they pass guardrails.

## Minimum Metrics

Track these before trusting any strategy:

- CAGR / total return
- max drawdown
- profit factor
- average win / average loss
- win rate
- trade count
- exposure time
- average holding period
- worst single trade
- worst day
- option premium spent
- option premium recovered
- closed-trade learning adjustments

## Guardrails

For this small paper account style:

- Paper only until there are many closed trades.
- Hard total bot cap.
- Hard max dollars per stock trade.
- Hard max premium per option trade.
- Max one option contract per underlying while testing.
- No naked short options.
- No spreads until single-leg handling is reliable.
- No trading if the bot cannot read positions.
- No trading if state and Alpaca positions disagree badly.

## Research Backlog

1. Add a daily snapshot file with account equity, open positions, exposure, and bot budget.
2. Build a closed-trade report page in the dashboard.
3. Add an order reconciliation check so duplicate open orders cannot stack.
4. Backtest stocks and options separately.
5. Add out-of-sample testing windows.
6. Add parameter search with drawdown and trade-count guardrails.
7. Add regime detection: risk-on, risk-off, chop.
8. Add liquidity filters: stock volume, option bid/ask spread, open interest if available.
9. Add option Greeks once reliable data is available.
10. Add a kill switch button in the dashboard.

## Practical Rule

Do not ask, "Can it make money?"

Ask:

1. Can it avoid catastrophic mistakes?
2. Can it explain why it entered?
3. Can it exit correctly?
4. Can it journal the result?
5. Can it learn only from completed evidence?
6. Can the same idea survive out-of-sample?

Only after those are true is profitability worth testing.
