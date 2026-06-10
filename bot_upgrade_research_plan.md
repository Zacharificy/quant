# Bot Upgrade Research Plan

This is the practical sequence for turning the quant research notes into safer bot improvements.

## Phase 1: Audit And Safety

Goal: make sure the bot cannot do dumb expensive things.

Tasks:

- Add open order reconciliation.
- Add dashboard view for open orders.
- Add kill switch.
- Add manual close/trim buttons.
- Store Alpaca order IDs in local state.
- Use filled average price where possible.
- Block new entries if Alpaca positions and local state disagree.
- Add a daily loss guard that blocks new entries but still allows exits/trims.
- Add a minimum average dollar-volume filter so the bot avoids thin names.
- Keep raw debug state collapsed in the dashboard by default.

Success:

- The bot can explain every open position.
- The bot can avoid duplicate buys.
- The bot can sell/trim when limits are exceeded.
- The dashboard makes the current state obvious without needing to read JSON.
- A single bad day cannot keep opening new positions after the local daily stop is hit.

## Phase 2: Trade Journal

Goal: create enough evidence for learning.

Tasks:

- Save every entry with asset type, ticker, symbol, side, shares/contracts, multiplier, estimated cost, signal score, reason, and order ID.
- Save every exit with fill price, realized P/L, return percentage, exit reason, and holding time.
- Show closed trades in dashboard.
- Show stock and option performance separately.

Success:

- Learning is based on real closed trades.
- We can inspect whether losses come from bad entries, bad exits, spreads, or sizing.

## Phase 3: Research Harness

Goal: make a Karpathy-style trading autoresearch loop.

Rules:

- Autoresearch may edit only strategy configuration or research strategy files.
- Autoresearch may not edit Alpaca execution code.
- Autoresearch may not place live/paper orders.
- Every experiment uses the same capital, same universe, same costs, same dates.
- Every result is stored, even bad results.

Metrics:

- total return
- max drawdown
- profit factor
- trade count
- worst trade
- benchmark comparison
- parameter count penalty

Promotion guardrails:

- minimum 30 trades, unless explicitly testing a slow strategy
- out-of-sample positive
- max drawdown below threshold
- profit factor above threshold
- no single trade explains most profit
- result beats benchmark after costs

## Phase 4: Strategy Sleeves

Goal: diversify return drivers.

Sleeves:

- stock momentum
- stock mean reversion
- long call directional
- long put directional
- cash/risk-off

Each sleeve gets:

- separate score
- separate max exposure
- separate journal stats
- separate enable/disable switch

## Phase 5: Portfolio Layer

Goal: stop thinking trade-by-trade only.

Tasks:

- Rank all candidate trades.
- Allocate risk by sleeve.
- Prevent too many correlated names.
- Keep total exposure under cap.
- Reduce risk when recent closed-trade performance is weak.

## Phase 6: Data Improvements

Goal: improve signal quality only after safety works.

Possible data additions:

- Alpaca news headline risk
- option bid/ask and spread
- option open interest if available
- realized volatility
- implied-vs-realized volatility estimate
- earnings/event calendar from reputable sources

## Phase 7: Live Readiness Checklist

Do not go live until:

- At least several weeks of paper logs exist.
- Bot has both bought and sold successfully.
- Duplicate-order checks work.
- Max exposure checks work.
- Kill switch works.
- Dashboard shows all open positions and open orders.
- Realized P/L journal matches Alpaca.
- Strategy survives out-of-sample research.
- You can explain why the bot entered and exited each trade.
