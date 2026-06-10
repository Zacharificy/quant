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
```

Do not commit your real `.env` file or Alpaca keys to GitHub.

## Recommended Volume

Railway files can reset on deploy. Add a Railway volume mounted at `/data`, then set:

```text
BOT_STATE_PATH=/data/alpaca_stock_bot_state.json
BOT_WATCHLIST_PATH=/data/watchlist.json
BOT_LEVELS_PATH=/data/trade_levels.json
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
- Let the bot run paper for multiple market days before considering real money.
