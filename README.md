# Alpaca Paper Stocks Bot

This project replaces the discontinued Discord bot with a small standalone Alpaca Paper stock bot you can run on your PC.

## What It Trades

- Instruments: liquid stocks and ETFs, not options
- Universe: `SPY`, `QQQ`, `IWM`, `DIA`, `AAPL`, `MSFT`, `NVDA`, `AMD`, `PLTR`, `SOFI`
- Account size: `$1,000`
- Max open positions: `2`
- Sizing: up to 45% of account value per position, whole shares only
- Entry: daily 50/200 EMA uptrend, 20-day high breakout, and RSI confirmation
- Exits: ATR stop, ATR target, 25-day time stop, or failed trend
- Cooldown: 7 calendar days after closing the same ticker
- Orders: Alpaca-supported market orders only

This is a starter paper strategy, not a proven profitable system. It is intentionally stock-first because a `$1,000` account is much easier to test with equities than long options.

## Run On Your PC

1. Open PowerShell in this folder.
2. Create a virtual environment:
   ```powershell
   python -m venv .venv
   ```
3. Activate it:
   ```powershell
   .\.venv\Scripts\Activate.ps1
   ```
4. Install dependencies:
   ```powershell
   pip install -r requirements.txt
   ```
5. Copy `.env.example` to `.env`.
6. Put your Alpaca **paper** API key and secret in `.env`.
7. Run the bot:
   ```powershell
   python .\alpaca_stock_bot.py
   ```

The bot is designed to run once per trading day after market open. It checks exits first, then looks for one new entry if there is room.

## Important Notes

- This script is locked to Alpaca Paper mode.
- Do not paste Alpaca keys into code or GitHub.
- The bot stores local state in `alpaca_stock_bot_state.json` by default.
- Paper fills are not the same as real live fills.
- This version may take fewer trades because it waits for daily breakouts.
- Start with paper only until you have a real sample of closed trades.

## First Things To Check

After the first few paper runs:

- Did it actually place stock orders?
- Did it avoid stocks it could not afford?
- Are entries happening mostly during strong market periods?
- Are exits happening from ATR stops, ATR targets, time stops, or trend failures?
- Does Alpaca show the same positions that the local state file tracks?

If it takes too few trades, loosen one setting at a time:

- `self.min_score`
- `self.breakout_lookback_days`
- RSI bounds in `score_stock`
- `self.max_positions`
- `self.cooldown_days`

Avoid adding smart-money/FVG/order-block filters until they are backtested.
