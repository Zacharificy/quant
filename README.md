# QuantConnect Alpaca Paper Stocks Starter

This project replaces the discontinued Discord bot with a QuantConnect algorithm that can be deployed to Alpaca Paper.

## What It Trades

- Instruments: liquid stocks and ETFs, not options
- Universe: `SPY`, `QQQ`, `IWM`, `DIA`, `AAPL`, `MSFT`, `NVDA`, `AMD`, `PLTR`, `SOFI`
- Account size: `$1,000`
- Max open positions: `2`
- Sizing: up to 45% of account value per position, whole shares only
- Entry: SPY/QQQ market health filter, daily 50/200 EMA uptrend, 20-day high breakout, and RSI confirmation
- Exits: ATR stop, ATR trailing stop, ATR target, 25-day time stop, or failed trend
- Cooldown: 7 calendar days after closing the same ticker
- Orders: Alpaca-supported market orders only

This is a starter paper strategy, not a proven profitable system. It is intentionally stock-first because a `$1,000` account is much easier to test with equities than long options. The market filter and trailing exit are there to reduce the large giveback that can happen when breakout trades keep firing into broad weakness.

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


   class AlpacaPaperStocksStarter(QCAlgorithm):
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
- QuantConnect backtests and paper fills are not the same as real live fills.
- This version may take fewer trades because it waits for daily breakouts.
- Start with paper only until you have a real sample of closed trades.

## First Things To Check

After the first backtest:

- Did it actually place stock orders?
- Did it avoid stocks it could not afford?
- Are entries happening mostly during strong market periods?
- Are exits happening from ATR stops, ATR trailing stops, ATR targets, time stops, or trend failures?
- Is drawdown better than the long-options version?

If it takes too few trades, loosen one setting at a time:

- `self.min_score`
- `self.breakout_lookback_days`
- RSI bounds in `score_stock`
- `self.max_positions`
- `self.cooldown_days`
- `self.trailing_stop_atr_multiple`

Avoid adding smart-money/FVG/order-block filters until they are backtested.
