import logging
import os
import threading
import time
import json
from datetime import datetime, timezone
from pathlib import Path

from alpaca_stock_bot import AlpacaStockBot, NY_TZ, StrategyConfig
from auto_research import run_autoresearch
from dashboard import app
from discord_notifier import DiscordNotifier
from discord_presence import start_discord_presence
from pretrade_research import format_research_summary, run_pretrade_research


def env_flag(name, default=True):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def run_scan_loop():
    interval_minutes = float(os.getenv("BOT_SCAN_INTERVAL_MINUTES", "20"))
    interval_seconds = max(60, int(interval_minutes * 60))
    config = StrategyConfig()

    while True:
        sleep_seconds = interval_seconds
        try:
            bot = AlpacaStockBot(config)
            clock = bot.trading.get_clock()

            if clock.is_open:
                logging.info("Railway scan loop running one live scan.")
                bot.run_once()
            else:
                next_open = clock.next_open
                if next_open and next_open.tzinfo is None:
                    next_open = next_open.replace(tzinfo=timezone.utc)
                if next_open:
                    until_open = (next_open - datetime.now(timezone.utc)).total_seconds()
                    sleep_seconds = min(interval_seconds, max(60, int(until_open)))
                    logging.info("Market closed. Next open: %s", next_open.astimezone(NY_TZ))
                else:
                    logging.info("Market closed. Next open was not available.")
        except Exception:
            logging.exception("Railway scan loop failed; will retry after interval.")

        time.sleep(sleep_seconds)


def marker_path() -> Path:
    return Path(os.getenv("BOT_AUTORESEARCH_MARKER_PATH", "autoresearch_last_run.json"))


def load_research_marker() -> dict:
    path = marker_path()
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)
    except Exception:
        return {}


def save_research_marker(update: dict) -> None:
    path = marker_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = load_research_marker()
    payload.update(update)
    payload["updated_at"] = datetime.now(NY_TZ).isoformat(timespec="seconds")
    with path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2, sort_keys=True)


def hours_since(timestamp: str, now_et: datetime) -> float:
    if not timestamp:
        return 9999.0
    try:
        parsed = datetime.fromisoformat(timestamp)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=NY_TZ)
        return (now_et - parsed.astimezone(NY_TZ)).total_seconds() / 3600
    except Exception:
        return 9999.0


def run_autoresearch_loop():
    notifier = DiscordNotifier.from_env()
    start_hour = int(os.getenv("BOT_AUTORESEARCH_START_HOUR_ET", "17"))
    overnight_end_hour = int(os.getenv("BOT_RESEARCH_OVERNIGHT_END_HOUR_ET", "8"))
    check_seconds = max(300, int(float(os.getenv("BOT_AUTORESEARCH_CHECK_MINUTES", "30")) * 60))
    ticker_interval_hours = max(1.0, float(os.getenv("BOT_TICKER_RESEARCH_INTERVAL_HOURS", "4")))
    apply_settings = env_flag("BOT_AUTORESEARCH_APPLY", True)
    enable_parameter_research = env_flag("BOT_ENABLE_AUTO_RESEARCH", True)
    enable_ticker_research = env_flag("BOT_ENABLE_TICKER_RESEARCH", True)
    config = StrategyConfig()

    while True:
        try:
            bot = AlpacaStockBot(config)
            clock = bot.trading.get_clock()
            now_et = datetime.now(NY_TZ)
            run_date = now_et.date().isoformat()
            after_research_hour = now_et.hour >= start_hour
            is_overnight = now_et.hour >= start_hour or now_et.hour < overnight_end_hour
            marker = load_research_marker()
            ticker_due = (
                enable_ticker_research
                and not clock.is_open
                and is_overnight
                and hours_since(str(marker.get("last_ticker_research_at", "")), now_et) >= ticker_interval_hours
            )
            parameter_due = (
                enable_parameter_research
                and not clock.is_open
                and after_research_hour
                and str(marker.get("last_parameter_research_date", "")) != run_date
            )

            if ticker_due:
                logging.info("Starting overnight ticker research for %s.", run_date)
                notifier.send(f"**Ticker research started**\nFocus: `{os.getenv('BOT_RESEARCH_FOCUS_TICKERS', 'F,AMC,SPY')}`")
                ticker_payload = run_pretrade_research()
                save_research_marker(
                    {
                        "last_ticker_research_at": datetime.now(NY_TZ).isoformat(timespec="seconds"),
                        "last_ticker_research_date": run_date,
                        "last_ticker_research_reports": len(ticker_payload.get("reports") or {}),
                    }
                )
                notifier.send(format_research_summary(ticker_payload, max_tickers=8, include_news=True))

            if parameter_due:
                logging.info("Starting after-hours parameter autoresearch for %s. apply=%s", run_date, apply_settings)
                notifier.send(f"**Parameter auto research started**\nDate: `{run_date}` | apply: `{apply_settings}`")
                recommendation = run_autoresearch(apply=apply_settings)
                save_research_marker(
                    {
                        "last_parameter_research_date": run_date,
                        "last_parameter_research_reason": recommendation.get("reason", ""),
                        "last_parameter_research_should_apply": bool(recommendation.get("should_apply")),
                        "last_parameter_research_applied_settings": recommendation.get("applied_settings", {}),
                    }
                )
                applied = recommendation.get("applied_settings")
                best = recommendation.get("best_candidate") or {}
                notifier.send(
                    "**Parameter auto research finished**\n"
                    f"Reason: {recommendation.get('reason', 'n/a')}\n"
                    f"Applied: `{bool(applied)}`\n"
                    f"Best return: `{float(best.get('return_pct', 0.0)):.2f}%` | "
                    f"DD: `{float(best.get('max_drawdown_pct', 0.0)):.2f}%` | "
                    f"Trades: `{int(best.get('trade_count', 0))}`"
                )

            elif clock.is_open:
                logging.info("Auto research waiting: market is open.")
            elif not ticker_due and not parameter_due:
                logging.info(
                    "Closed-market research waiting. overnight=%s ticker_due=%s parameter_due=%s",
                    is_overnight,
                    ticker_due,
                    parameter_due,
                )
            else:
                logging.info("Closed-market research loop idle.")
        except Exception:
            logging.exception("Auto research loop failed; will retry later.")
            save_research_marker(
                {
                    "last_research_error_at": datetime.now(NY_TZ).isoformat(timespec="seconds"),
                    "last_research_error": "closed-market research failed; check Railway logs",
                }
            )
            DiscordNotifier.from_env().send("**Auto research failed**\nCheck Railway logs for details.")

        time.sleep(check_seconds)


def start_autoresearch_loop():
    if not env_flag("BOT_ENABLE_AUTO_RESEARCH", True) and not env_flag("BOT_ENABLE_TICKER_RESEARCH", True):
        logging.info("Closed-market research is disabled.")
        return

    worker = threading.Thread(target=run_autoresearch_loop, name="bot-autoresearch-loop", daemon=True)
    worker.start()
    logging.info("Started closed-market research loop thread.")


def start_background_loop():
    if not env_flag("BOT_ENABLE_AUTO_LOOP", True):
        logging.info("BOT_ENABLE_AUTO_LOOP is disabled. Dashboard only.")
        return

    worker = threading.Thread(target=run_scan_loop, name="bot-scan-loop", daemon=True)
    worker.start()
    logging.info("Started bot scan loop thread.")


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    start_discord_presence()
    start_background_loop()
    start_autoresearch_loop()

    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8080"))
    logging.info("Starting Railway dashboard on %s:%s", host, port)
    app.run(host=host, port=port, use_reloader=False)


if __name__ == "__main__":
    main()
