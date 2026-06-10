# Alpaca Paper Stocks Bot

This project replaces the discontinued Discord bot with a small standalone Alpaca Paper stock bot you can run on your PC.

## What It Trades

- Instruments: liquid stocks and ETFs, not options
- Universe: `SPY`, `QQQ`, `IWM`, `DIA`, `AAPL`, `MSFT`, `NVDA`, `AMD`, `PLTR`, `SOFI`
- Account size: `$1,000`
- Max open stock positions: `5`
- Sizing: up to 45% of account value per position, whole shares only
- Entry: daily 50/200 EMA uptrend, 20-day high breakout, and RSI confirmation
- Exits: ATR stop, ATR target, 25-day time stop, or failed trend
- Cooldown: 7 calendar days after closing the same ticker
- Orders: Alpaca-supported market orders only
- Options: optional long-only calls/puts, up to 3 option positions, limit orders only

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
   Keep `ALPACA_DATA_FEED=iex` unless you pay Alpaca for SIP market data.
7. Run the bot:
   ```powershell
   python .\alpaca_stock_bot.py
   ```

The bot is designed to run once per trading day after market open. It checks exits first, then looks for one new entry if there is room.

## Local Dashboard

Run this from the project folder:

```powershell
python .\dashboard.py
```

Then open:

```text
http://127.0.0.1:5050
```

The dashboard is local-only by default. It shows Alpaca Paper account status, open positions, the bot state file, and has a button to run one scan.

The dashboard also lets you add or remove tickers from the bot watchlist. The watchlist is stored in `watchlist.json` by default.

Dashboard controls:

- `Pause Trading` stops new entries but still lets exits and risk trims run.
- `Resume Trading` allows new entries again.
- `Cancel Bot Open Orders` cancels pending bot-related Alpaca orders.
- `Trim` reduces a tracked position back toward the bot's configured size limits.
- `Close` submits an exit order for that position.

Use `Close` and `Trim` carefully. They submit real Alpaca Paper orders.

## Risk Checks

Before opening a new position, the bot now checks:

- broad market regime using `SPY`, `QQQ`, and `DIA`
- manual block dates from `BOT_BLOCK_DATES`
- large ticker gaps
- unusually high ATR versus price
- recent Alpaca news headlines for risky keywords
- buying power and whole-share affordability

For options, the bot only uses long premium:

- bullish setup -> buy-to-open one call
- bearish setup -> buy-to-open one put
- option quantity is contract count, not shares
- one option contract controls 100 shares, so estimated cost is `contracts * limit premium * 100`
- default sizing is capped to 1 contract per trade and 1 contract per underlying
- no naked short options
- no spreads yet
- option cost must fit the internal paper sizing cap
- exits use option profit target, option stop loss, or option time stop

## Self-Learning

The bot learns only from closed trades. It records closed stock and option trades in the local state file, then:

- adds small score bonuses to ticker/direction setups that have worked
- adds small score penalties to ticker/direction setups that have failed
- scales risk down after a weak recent streak
- never scales above the hard dollar caps

This is adaptive paper-trading feedback, not a guarantee of profitability.

Use `BOT_BLOCK_DATES` in `.env` for dates when you do not want new entries, such as CPI or FOMC days:

```env
BOT_BLOCK_DATES=2026-06-10,2026-06-17
```

## Research Runner

The local research loop is inspired by Karpathy's `autoresearch` idea: change one thing, test it, measure it, keep a leaderboard. It never submits orders.

Run:

```powershell
python .\research_runner.py
```

It writes results into `research_results/`:

- `leaderboard_*.csv` for all parameter combinations
- `best_*.json` for the top runs

Use this to decide which settings deserve a paper-trading test. Do not copy the best backtest blindly into live trading; look for enough trades, reasonable drawdown, and stable behavior.

## Auto Research

`auto_research.py` is the guarded version of the Karpathy-style loop. It runs a sweep, compares results to the current bot settings, and writes a recommendation.

Recommendation only:

```powershell
python .\auto_research.py
```

Apply only if the candidate passes guardrails:

```powershell
python .\auto_research.py --apply
```

When applied, it writes `learned_settings.json`. The bot loads that file at startup, so restart the dashboard/bot after applying settings.

Guardrails:

- at least 15 closed backtest trades
- max drawdown at or below 18%
- profit factor at or above 1.20
- return improvement at least 3% better than current settings

Current paper-test settings were selected from the first local sweep as the more conservative candidate:

- `breakout_lookback_days=10`
- `min_score=0.68`
- `stop_atr_multiple=2.5`
- `take_profit_atr_multiple=4.0`
- `max_hold_days=35`
- `position_pct=0.30`
- local research result: `26.87%` return, `10.08%` max drawdown, `16` trades

## Important Notes

- This script is locked to Alpaca Paper mode.
- Free Alpaca accounts should use `ALPACA_DATA_FEED=iex`; SIP data requires a paid data subscription.
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
