# QuantConnect Alpaca Paper Options Starter

This project replaces the discontinued Discord bot with a QuantConnect algorithm that can be deployed to Alpaca Paper.

## What It Trades

- Underlyings: `SPY`
- Instrument: long single-leg options only
- Account size: `$1,000`
- Max open option contracts: `1`
- Entry: daily 20/50 EMA uptrend plus intraday 12/26 EMA and RSI confirmation
- Contract selection: 14-30 DTE calls, roughly 2% out-of-the-money, spread capped
- Risk: max 7% of portfolio value per option premium
- Exits: -25% stop, +60% target, 240-minute time stop, or end-of-day flattening
- Cooldown: 10 calendar days after closing a trade
- Entry orders: limit orders are canceled if they do not fill within 10 minutes
- Exit orders: explicit market orders during 10:00-15:30 ET only
- Entry window: 10:30-13:30 ET only

This is a starter paper strategy, not a proven profitable system.

## How To Use In QuantConnect

1. Open your QuantConnect project.
2. Open `main.py`.
3. Press `Ctrl+A` in QuantConnect's editor and delete the entire starter template.
4. Copy the entire contents of this repository's `main.py`, starting at line 1:
   `from AlgorithmImports import *`
5. Paste the full file into QuantConnect. Do not paste only a middle chunk.
6. Make sure lines 1-4 look exactly like this, with no leading spaces:
   ```python
   from AlgorithmImports import *
   from datetime import timedelta


   class AlpacaPaperOptionsStarter(QCAlgorithm):
   ```
7. Click **Build**.
8. Click **Backtest**.
9. Review trades, drawdown, win rate, and order fills.
10. Only after it builds/backtests, click **Deploy Live**.
11. Brokerage: **Alpaca**.
12. Environment: **Paper**.
13. Authenticate Alpaca when QuantConnect redirects you.
14. Choose a live node and deploy.

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
- `self.cooldown_days`

Avoid adding smart-money/FVG/order-block filters until they are backtested.
