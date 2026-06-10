# Quant Trading Console

This project is a standalone Alpaca Paper trading console with a local/Railway dashboard, automated scan loop, options entries, exits, learning state, news checks, chart/GEX levels, and optional Discord trade notifications.

## What It Trades

- Instruments: long-only calls/puts by default, with stock trading still available in code but disabled by default
- Universe: `SPY`, `QQQ`, `IWM`, `DIA`, `AAPL`, `MSFT`, `NVDA`, `AMD`, `PLTR`, `SOFI`
- Account size: `$1,000`
- Internal paper sizing cap: `$1,500` by default
- Max open option positions: `3`
- Sizing: options are sized as contracts, where `1 contract = 100 shares`
- Entry: daily 50/200 EMA uptrend, 20-day high breakout, and RSI confirmation
- Exits: option profit target, stop loss, time stop, or Alpaca bracket protection when accepted
- Cooldown: 7 calendar days after closing the same ticker
- Orders: Alpaca Paper orders only
- Options: long-only calls/puts, limit orders, no naked short options

This is a paper strategy, not a proven profitable system. Let it build a real closed-trade sample before trusting any setting.

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

## Railway

The repo includes Railway support:

- `Procfile`
- `railway_app.py`
- `RAILWAY.md`

Railway runs the dashboard and a background scan loop in one service. Set `DASHBOARD_PASSWORD` before exposing the dashboard.

## Discord Trade Notifications

No Discord commands are required. The bot can post trade activity to a `trades` or `positions` channel.

Recommended setup: create a Discord webhook in that channel, then set:

```env
DISCORD_TRADE_WEBHOOK_URL=https://discord.com/api/webhooks/...
```

Alternative setup:

```env
DISCORD_TOKEN=your_bot_token
DISCORD_TRADE_CHANNEL_ID=your_channel_id
DISCORD_SHOW_ONLINE=true
```

The bot sends messages when it records an opened trade, records a closed trade, or submits a manual close/trim from the dashboard. If `DISCORD_TOKEN` is set, Railway also starts a tiny no-command Discord client so the bot shows online. Discord failures are logged but do not block trading.

## Risk Checks

Before opening a new position, the bot now checks:

- broad market regime using `SPY`, `QQQ`, and `DIA`
- manual block dates from `BOT_BLOCK_DATES`
- large ticker gaps
- unusually high ATR versus price
- recent Alpaca news headlines for risky keywords
- reputable external macro RSS feeds with content/title checks
- InsiderFinance GEX levels where available
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
