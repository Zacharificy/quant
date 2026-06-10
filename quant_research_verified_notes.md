# Quant Trading Verified Notes

These notes are meant to be used later when upgrading the Alpaca paper bot. They separate credible quant concepts from ideas that are useful but easy to misuse.

## Source Vetting

### Roman Paolucci / Quant Guild

Status: useful educational source, but still treat as education, not a trading signal vendor.

What appears legitimate:

- Roman Paolucci is publicly associated with Quant Guild and quantitative finance education.
- Search results and public materials connect him to QFin, options pricing, risk models, portfolio theory, and Python for finance.
- The ideas in the pasted notes line up with established finance concepts: volatility drag, geometric vs arithmetic return, convexity, diversification, beta exposure, and risk premia.

What not to assume:

- A YouTube explanation is not a validated profitable strategy.
- Roman-style concepts still need data, backtests, transaction costs, and out-of-sample checks before they belong in a bot.
- Any claim about “edge” should be translated into a measurable hypothesis.

### Karpathy Autoresearch

Status: real project and highly relevant as a workflow idea.

What appears legitimate:

- `karpathy/autoresearch` exists on GitHub.
- Its core loop is intentionally narrow: an agent edits one file, runs a fixed-time experiment, measures one metric, and keeps/discards changes.
- The repo uses fixed experiment budgets so results are comparable.
- It is for machine learning experiments, not finance directly.

How to use the idea for trading:

- Do not let an agent trade live.
- Let an agent propose research changes only inside a sandbox.
- Run fixed-budget backtests.
- Score candidates by out-of-sample return, drawdown, trade count, and stability.
- Promote settings only after guardrails pass.

### Karpathy Researchpooler

Status: real but older and less directly useful for the trading bot.

What it is:

- `karpathy/researchpooler` is about automating research-paper discovery and analysis.
- It is useful as inspiration for a literature-review helper.

How to use the idea:

- Build a script that collects strategy papers, extracts claims, links data requirements, and logs whether each idea is testable.
- Do not mix literature discovery with live trading execution.

## Legit Concepts To Keep

### 1. Volatility Drag

Legit.

Core idea:

- Arithmetic average return is not the same as geometric compound growth.
- Volatility lowers compound growth.
- Large losses require larger gains to recover.

Bot implication:

- Track max drawdown and worst trade, not only win rate.
- Reduce risk after bad streaks.
- Keep cash/risk-off mode as a valid decision.

### 2. Geometric Growth Objective

Legit, but advanced.

Core idea:

- Long-term capital growth depends on the path of returns.
- A smoother lower-return strategy can compound better than a volatile higher-average strategy.

Bot implication:

- Optimize for return per drawdown, not just raw return.
- Penalize strategies with unstable equity curves.
- Prefer smaller sizing until the bot has enough closed trades.

### 3. Structural Diversification

Legit.

Core idea:

- More tickers do not equal diversification if they all load on the same factor.
- A tech-heavy universe still behaves like a tech/beta bet.

Bot implication:

- Separate sleeves: momentum, mean reversion, long options, risk-off cash.
- Track correlation between sleeves.
- Do not add 50 tickers and call it diversified.

### 4. Volatility Risk Premium

Legit, but dangerous for small accounts.

Academic support:

- Goyal and Saretto studied option returns sorted by the difference between realized and implied volatility and found economically/statistically significant average returns in their tested construction.

Bot implication:

- This can inspire research, but not immediate live short-option trading.
- A small bot should start long-only options until position handling, exits, and option data quality are proven.
- Short vol strategies can have high win rates and catastrophic tail losses.

### 5. Factor Models

Legit.

Academic support:

- Fama and French showed common stock return variation can be captured by market, size, and book-to-market factors, with bond factors also relevant.

Bot implication:

- Measure whether the bot is just long market beta.
- Compare returns against SPY/QQQ benchmark.
- Avoid thinking a bullish stock bot has alpha just because the market went up.

### 6. Backtest Overfitting / Data Snooping

Very legit.

Academic support:

- Lo and MacKinlay showed data-snooping bias can make false discoveries look statistically significant.
- Bailey / Lopez de Prado style work warns that many backtests fail because too many trials are searched and the best one is selected by luck.

Bot implication:

- Keep a leaderboard of all failed experiments.
- Use out-of-sample windows.
- Penalize too many parameters.
- Do not blindly apply the best run from a sweep.

## Ideas To Treat With Caution

### “The bot learns every trade”

Dangerous wording.

Better framing:

- The bot journals every entry.
- It updates scores only after closed trades.
- It needs enough closed trades before adjustments matter.

### “News makes it smarter”

Partly true, mostly risk control.

Better framing:

- News headlines should block obvious risk events.
- A simple keyword news filter is not true NLP alpha.
- Reputable sources matter, but the bot still needs testable rules.

### “Options are better because leverage”

Dangerous.

Better framing:

- Options give convex exposure and defined premium risk when long.
- Time decay and spreads can quietly destroy returns.
- One contract controls 100 shares, so sizing must be contract-aware.

### “Autoresearch can find a profitable strategy”

Possible, but easy to misuse.

Better framing:

- Autoresearch can search parameter/logic space.
- It cannot prove future profitability.
- It should optimize for robust guardrails, not just highest return.

## Trading Autoresearch Design

Borrow this from Karpathy:

1. Fixed experiment budget.
   Every experiment uses the same data window, same cost assumptions, same max runtime, and same starting capital.

2. Single controlled edit area.
   The research loop should modify only a config file or a strategy function, not broker execution code.

3. One primary metric plus guardrails.
   Primary metric can be risk-adjusted return, but guardrails should include max drawdown, min trades, profit factor, turnover, and worst trade.

4. Keep all results.
   Failed experiments are valuable because they reduce future overfitting.

5. Human review before promotion.
   The bot should never auto-promote settings into live trading.

## Suggested Metrics For The Bot

Minimum:

- total return
- benchmark return
- max drawdown
- trade count
- win rate
- profit factor
- average win
- average loss
- worst trade
- average holding days
- exposure percentage
- option premium spent
- option premium recovered

Better:

- CAGR
- Sharpe or Sortino
- Calmar ratio
- rolling drawdown
- regime-specific performance
- stock vs option performance split
- ticker-level contribution
- sleeve-level contribution

## Build Priorities

### Priority 1: Safety Before Intelligence

- Verify every Alpaca position against local state.
- Block duplicate open orders.
- Enforce max contracts and max exposure.
- Add kill switch.
- Add force-close/trim controls in dashboard.

### Priority 2: Better Journal

- Record order IDs.
- Record filled price, not only estimated entry price.
- Record contracts vs shares clearly.
- Record entry reason and exit reason.
- Record realized P/L after exit.

### Priority 3: Better Research

- Create a reusable backtest result schema.
- Split in-sample and out-of-sample.
- Add walk-forward testing.
- Save every experiment.
- Add a promotion checklist.

### Priority 4: Better Strategy

- Separate stock and option decisions.
- Add liquidity filters.
- Add market regime scoring.
- Add mean-reversion sleeve.
- Add benchmark comparison.

### Priority 5: Better Dashboard

- Show closed trades.
- Show open orders.
- Show bot budget.
- Show learning adjustments.
- Show “why no trade.”
- Add a kill switch.

## What This Means For The Current Bot

The current bot should not be made more aggressive yet.

Before improving signal logic:

1. Make sure it can close and trim correctly.
2. Make sure it cannot stack duplicate options.
3. Make sure contract math is correct.
4. Make sure every order is journaled.
5. Make sure closed trades update learning.
6. Make sure the dashboard shows enough to audit it.

After that, use autoresearch to test strategy parameters, not to trade live.
