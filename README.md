# Quant Trading Console

This project is a standalone Alpaca Paper trading console with a local/Railway dashboard, automated scan loop, options entries, exits, learning state, news checks, chart/GEX levels, and optional Discord trade notifications.

## What It Trades

- Instruments: long-only calls/puts by default, with stock trading still available in code but disabled by default
- Universe: `SPY`, `QQQ`, `IWM`, `DIA`, `AAPL`, `MSFT`, `NVDA`, `AMD`, `PLTR`, `SOFI`
- Account size: `$1,000`
- Internal paper sizing cap: `$1,500` by default
- Max open option positions: `3`
- Sizing: options are sized as contracts, where `1 contract = 100 shares`
- Entry: multi-timeframe chart confirmation with news/research nudges, while still requiring option liquidity and Greek checks
- Exits: default option plan is about `+35%` take profit, `-15%` stop, day-0 profit only for a fast `+45%` move, and a 5-day max hold
- SPY manual levels: `trade_levels.json` can mark a chop/kill zone. Current SPY context treats `740.09-744.09` as scalp-only unless a 30-minute candle confirms a breakout above `744.09` or a breakdown under `740`.
- Learning: closed trades now adjust future scores with win rate, profit factor, and downside-adjusted return so one lucky winner does not hide repeated bad losses
- Cooldown: 7 calendar days after closing the same ticker
- Orders: Alpaca Paper orders only
- Options: long-only calls/puts, limit orders, no naked short options

This is a paper strategy, not a proven profitable system. Let it build a real closed-trade sample before trusting any setting.
The current default option settings are meant for short swings, not pure 0DTE scalps: prefer roughly `3-10 DTE`, hold winning setups for `2-5` trading days if the stop is not hit, and avoid treating noisy headlines as market catalysts.

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

Useful Railway strategy variables:

```env
BOT_TRADE_OPTIONS=true
BOT_TRADE_STOCKS=true
BOT_PAPER_EQUITY_CAP=1500
BOT_MAX_OPTION_POSITIONS=3
BOT_MAX_OPTION_PREMIUM_CASH=650
BOT_MIN_OPTION_SCORE=0.58
BOT_MIN_ACTIVITY_OPTION_SCORE=0.46
BOT_MAX_CANDIDATE_COUNT=8
BOT_MAX_OPTION_SPREAD_PCT=0.45
BOT_MIN_OPTION_ABS_DELTA=0.22
BOT_MAX_OPTION_ABS_DELTA=0.72
BOT_MAX_OPTION_THETA_DECAY_PCT=0.18
BOT_MIN_OPTION_DELTA_THETA_SCORE=1.75
BOT_OPTION_PROFIT_TARGET_PCT=0.20
BOT_OPTION_STOP_LOSS_PCT=0.10
BOT_MAX_STOCK_TRADE_CASH=600
BOT_FOCUS_LIQUID_UNIVERSE=true
BOT_EXTRA_TICKERS=
```

The stock sleeve matters because the QuantConnect-style test was stock based. The live bot can still trade long calls/puts, but if the option chain is too expensive or too wide, it can now fall back to stock entries instead of sitting idle. `BOT_FOCUS_LIQUID_UNIVERSE=true` keeps the live scanner focused on SPY/major ETFs plus liquid names with tighter spreads. Use `BOT_EXTRA_TICKERS=F,AMC` only when you intentionally want extra names added back.

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
DISCORD_ANNOUNCE_ONLINE=false
DISCORD_STATUS_REFRESH_SECONDS=300
DISCORD_ENABLE_RESEARCH_COMMAND=true
DISCORD_COMMAND_GUILD_ID=your_server_id_optional
```

The bot sends messages when it records an opened trade, records a closed trade, or submits a manual close/trim from the dashboard. If `DISCORD_TOKEN` is set, Railway also starts a tiny Discord client so the bot shows online and updates its status to all-time closed-trade P/L. `DISCORD_ANNOUNCE_ONLINE=false` prevents the repeated "Trading bot is online" message on each redeploy/reconnect. Discord failures are logged but do not block trading.

Discord command:

- `/researchplan` shows the overnight ticker research, the likely next-session candidate, and the latest live scan. This is the only slash command registered by this Railway bot. Set `DISCORD_COMMAND_GUILD_ID` to your Discord server ID if you want the command to appear quickly and avoid old global-command clutter.

## Risk Checks

Before opening a new position, the bot now checks:

- broad market regime using `SPY`, `QQQ`, and `DIA`
- manual block dates from `BOT_BLOCK_DATES`
- large ticker gaps
- unusually high ATR versus price
- recent Alpaca news headlines for risky keywords
- reputable external macro RSS feeds with body/title checks, including TruthSocial, Federal Reserve, CNN Business/top/politics, and MarketWatch/Dow Jones feeds by default
- InsiderFinance GEX levels where available
- manual chart levels from `trade_levels.json`; SPY uses 30-minute confirmation around its saved kill-zone levels and tighter per-trade exits when it is inside the chop zone
- buying power and whole-share affordability

The risky-news gate is intentionally a filter, not a buy/sell signal. It blocks new entries on hard catalyst terms such as SEC investigations, subpoenas, restatements, FDA rejections, going-concern warnings, delisting notices, merger agreement risk, cancelled contracts, lawsuits, offerings, and dilution.

Market-news Discord pings are also filtered. The bot reads the headline plus RSS summary/article body when available, then only pings when a trusted source contains a real market-moving event, market context, and a directional phrase. Examples include Trump/Iran escalation or de-escalation, tariffs, Fed/rate surprises, AI/chip policy, and Tesla/EV policy. The alert names the affected ticker group and whether the news is likely up or likely down.

Railway also starts a dedicated Truth Social monitor when `BOT_ENABLE_TRUTH_MONITOR=true`. It polls Trump's public Truth Social feed every `BOT_TRUTH_MONITOR_INTERVAL_SECONDS` seconds, enriches posts through Truth Social's public status API, checks linked URLs for basic safety issues, and includes media attachment metadata such as image/video URLs, duration, dimensions, and descriptions when available. If Truth Social resets or blocks a feed request, the monitor backs off up to `BOT_TRUTH_MONITOR_MAX_BACKOFF_SECONDS` instead of hammering the feed. It cannot guarantee a video transcript or OCR text from every image because Truth Social does not always expose that data, so media URLs are included for manual review when no transcript or description exists.

For options, the bot only uses long premium:

- bullish setup -> buy-to-open one call
- bearish setup -> buy-to-open one put
- option quantity is contract count, not shares
- one option contract controls 100 shares, so estimated cost is `contracts * limit premium * 100`
- default sizing is capped to 1 contract per trade and 1 contract per underlying
- no naked short options
- no spreads yet
- option cost must fit the internal paper sizing cap
- option delta must be in range and theta decay must be reasonable versus premium
- exits use option profit target, option stop loss, or option time stop

The repo pins Railway to Python `3.13.13` with `.python-version` so Railway does not auto-select a just-released Python patch without a prebuilt image.

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

On Railway, `railway_app.py` can run this automatically while the market is closed:

```env
BOT_ENABLE_AUTO_RESEARCH=true
BOT_ENABLE_TICKER_RESEARCH=true
BOT_RESEARCH_FOCUS_TICKERS=F,AMC,SPY,TSLA,NVDA,AMD,QQQ
BOT_RESEARCH_MAX_TICKERS=28
BOT_RESEARCH_SCAN_CANDIDATES=16
BOT_TICKER_RESEARCH_INTERVAL_HOURS=4
BOT_AUTORESEARCH_APPLY=true
BOT_AUTORESEARCH_START_HOUR_ET=17
BOT_RESEARCH_OVERNIGHT_END_HOUR_ET=8
BOT_AUTORESEARCH_CHECK_MINUTES=30
BOT_AUTORESEARCH_MAX_EXPERIMENTS=0
BOT_AUTORESEARCH_YIELD_SECONDS=0.15
BOT_TRUTH_MONITOR_MAX_BACKOFF_SECONDS=120
```

It runs at most once per ET date. It can apply settings only if the candidate passes the guardrails below. For persistent Railway storage, put these on the `/data` volume:

```env
BOT_LEARNED_SETTINGS_PATH=/data/learned_settings.json
BOT_TICKER_RESEARCH_PATH=/data/ticker_research.json
BOT_RESEARCH_RESULTS_DIR=/data/research_results
BOT_AUTORESEARCH_MARKER_PATH=/data/autoresearch_last_run.json
```

The ticker research step runs mainly overnight, every 4 hours by default between 5 PM and 8 AM ET. It researches a broad universe from the saved watchlist plus the bot's strongest current scan candidates, capped by `BOT_RESEARCH_MAX_TICKERS` so Railway does not grind itself down. `BOT_RESEARCH_FOCUS_TICKERS` is treated as a priority list, not the whole universe. It writes a compact report with chart score, risky-news checks, recent article summaries, Trump/deal catalyst checks, earnings/guidance context, and a `prefer_call` / `prefer_put` / `watch` / `avoid` recommendation. Shared market-wide catalysts are summarized once, then ticker rows explain the correlation instead of repeating the same news under every symbol. The dashboard and Discord summary now show a concrete next-session swing plan with hold window, entry discipline, exit plan, setup reasons, and catalysts. The live bot uses that report lightly: `avoid` can block a trade, while agreement/disagreement only nudges the score. Parameter auto research now waits until the next research-loop pass if ticker research just ran, and `BOT_AUTORESEARCH_YIELD_SECONDS` gives Discord and the dashboard breathing room during sweeps.

Deal-catalyst scoring is intentionally narrow. It needs a real market, policy, or company context such as tariffs, trade deals, ceasefires, defense contracts, export controls, semiconductors, autos, SpaceX, Tesla, Ford, or Nvidia. Generic legal/media settlements are ignored so junk headlines do not boost index trades.

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
