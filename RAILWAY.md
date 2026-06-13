# Railway Deployment

This project can run on Railway as one small web service:

- the dashboard is served on Railway's public URL
- the bot scan loop runs in the background while the market is open
- the dashboard can still run scans manually

## Required Variables

Add these in Railway under `Variables`:

```text
ALPACA_PAPER_API_KEY=your_paper_key
ALPACA_PAPER_SECRET_KEY=your_paper_secret
ALPACA_PAPER=true
ALPACA_DATA_FEED=iex
DASHBOARD_USER=admin
DASHBOARD_PASSWORD=make_a_long_private_password
BOT_ENABLE_AUTO_LOOP=true
BOT_SCAN_INTERVAL_MINUTES=20
BOT_ENABLE_AUTO_RESEARCH=true
BOT_ENABLE_TICKER_RESEARCH=true
BOT_RESEARCH_FOCUS_TICKERS=F,AMC,SPY
BOT_TICKER_RESEARCH_INTERVAL_HOURS=4
BOT_AUTORESEARCH_APPLY=true
BOT_AUTORESEARCH_START_HOUR_ET=17
BOT_RESEARCH_OVERNIGHT_END_HOUR_ET=8
DISCORD_TRADE_WEBHOOK_URL=optional_webhook_for_trade_alerts
BOT_NEWS_IMPACT_ALERTS_ENABLED=true
DISCORD_NEWS_MENTION_USER_ID=1270486587402358784
BOT_NEWS_IMPACT_MAX_ITEM_AGE_HOURS=48
EXTERNAL_MACRO_RSS_URLS=https://trumpstruth.org/feed,https://www.federalreserve.gov/feeds/press_all.xml
BOT_TRUTH_MONITOR_INTERVAL_SECONDS=5
BOT_TRUTH_MONITOR_FETCH_LIMIT=40
BOT_TRUTH_MONITOR_MAX_POST_AGE_MINUTES=45
BOT_TRUTH_MONITOR_LINK_CHECKS_ENABLED=true
```

Do not commit your real `.env` file or Alpaca keys to GitHub.

## Recommended Volume

Railway files can reset on deploy. Add a Railway volume mounted at `/data`, then set:

```text
BOT_STATE_PATH=/data/alpaca_stock_bot_state.json
BOT_WATCHLIST_PATH=/data/watchlist.json
BOT_LEVELS_PATH=/data/trade_levels.json
BOT_LEARNED_SETTINGS_PATH=/data/learned_settings.json
BOT_TICKER_RESEARCH_PATH=/data/ticker_research.json
BOT_RESEARCH_RESULTS_DIR=/data/research_results
BOT_AUTORESEARCH_MARKER_PATH=/data/autoresearch_last_run.json
```

Without a volume, the bot can still run, but state, watchlist changes, chart/GEX levels, and learning history may reset after redeploys.

## Start Command

Railway should detect the `Procfile` and run:

```text
python railway_app.py
```

If Railway asks for a start command manually, use that exact command.

## Safety Checklist Before Going Live

- Use Alpaca paper keys first.
- Set `DASHBOARD_PASSWORD` before exposing the dashboard.
- Keep `ALPACA_DATA_FEED=iex` unless you pay for SIP data.
- Check the dashboard after deploy and confirm the account says paper mode.
- If using Discord, create a webhook in the trades/positions channel and set `DISCORD_TRADE_WEBHOOK_URL`.
- Closed-market ticker research runs mainly overnight when `BOT_ENABLE_TICKER_RESEARCH=true`; by default it researches the saved watchlist plus the best scan candidates, while `BOT_RESEARCH_FOCUS_TICKERS` only acts as a priority list. Use `BOT_RESEARCH_MAX_TICKERS` to cap how wide the run can get.
- If Discord starts logging websocket lag, raise `BOT_AUTORESEARCH_YIELD_SECONDS` or set `BOT_AUTORESEARCH_MAX_EXPERIMENTS` to a smaller number on Railway.
- Let the bot run paper for multiple market days before considering real money.
