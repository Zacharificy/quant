# QuantConnect Alpaca Paper Options Starter

This project replaces the discontinued Discord bot with a QuantConnect algorithm that can be deployed to Alpaca Paper.

## What It Trades

- Underlyings: `SPY`, `QQQ`
- Instrument: long single-leg options only
- Account size: `$1,000`
- Max open option contracts: `1`
- Entry: 12/26 EMA direction plus RSI confirmation
- Contract selection: 21-45 DTE, near 30 delta, spread capped
- Risk: max 15% of portfolio value per option premium, capped at `$150`
- Exits: -30% stop, +50% target, 5-day time stop, or signal flip

This is a starter paper strategy, not a proven profitable system.

## How To Use In QuantConnect

1. Open your QuantConnect project.
2. Open `main.py`.
3. Replace the starter template with the contents of this repository's `main.py`.
4. Click **Build**.
5. Click **Backtest**.
6. Review trades, drawdown, win rate, and order fills.
7. Only after it builds/backtests, click **Deploy Live**.
8. Brokerage: **Alpaca**.
9. Environment: **Paper**.
10. Authenticate Alpaca when QuantConnect redirects you.
11. Choose a live node and deploy.

## Important Notes

- "Deploy Live" means the algorithm runs in real time. Choosing **Paper** keeps it paper money.
- Do not paste Alpaca keys into code or GitHub.
- Alpaca Paper options should be enabled by default.
- QuantConnect backtests and paper fills are not the same as real live fills.
- Start with paper only until you have a real sample of closed trades.

## First Things To Check

After the first backtest:

- Did it actually place option orders?
- Are contracts too expensive for a `$1,000` account?
- Are spreads too wide?
- Is the strategy trading too often or too rarely?
- Are exits happening from stops, targets, or time stops?

If it takes too few trades, loosen one setting at a time:

- `self.max_contract_mid`
- `self.max_spread_pct`
- RSI bands in `get_signal`
- `self.min_dte` / `self.max_dte`

Avoid adding smart-money/FVG/order-block filters until they are backtested.
