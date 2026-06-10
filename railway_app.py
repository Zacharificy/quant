import logging
import os
import threading
import time
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from alpaca_stock_bot import AlpacaStockBot, NY_TZ, StrategyConfig
from auto_research import run_autoresearch
from dashboard import app
from discord_notifier import DiscordNotifier
from discord_presence import start_discord_presence


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


def last_research_date() -> str:
    path = marker_path()
    if not path.exists():
        return ""
    try:
        with path.open("r", encoding="utf-8") as file:
            payload = json.load(file)
        return str(payload.get("last_run_date", ""))
    except Exception:
        return ""


def save_research_marker(run_date: str, recommendation: dict) -> None:
    path = marker_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "last_run_date": run_date,
        "updated_at": datetime.now(NY_TZ).isoformat(timespec="seconds"),
        "reason": recommendation.get("reason", ""),
        "should_apply": bool(recommendation.get("should_apply")),
        "applied_settings": recommendation.get("applied_settings", {}),
    }
    with path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2, sort_keys=True)


def run_autoresearch_loop():
    notifier = DiscordNotifier.from_env()
    start_hour = int(os.getenv("BOT_AUTORESEARCH_START_HOUR_ET", "17"))
    check_seconds = max(300, int(float(os.getenv("BOT_AUTORESEARCH_CHECK_MINUTES", "30")) * 60))
    apply_settings = env_flag("BOT_AUTORESEARCH_APPLY", True)
    config = StrategyConfig()

    while True:
        try:
            bot = AlpacaStockBot(config)
            clock = bot.trading.get_clock()
            now_et = datetime.now(NY_TZ)
            run_date = now_et.date().isoformat()
            after_research_hour = now_et.hour >= start_hour
            premarket_window = not clock.is_open and clock.next_open and clock.next_open.astimezone(NY_TZ) - now_et <= timedelta(hours=8)
            already_ran = last_research_date() == run_date

            if not clock.is_open and not already_ran and (after_research_hour or premarket_window):
                logging.info("Starting closed-market autoresearch for %s. apply=%s", run_date, apply_settings)
                notifier.send(f"**Auto research started**\nDate: `{run_date}` | apply: `{apply_settings}`")
                recommendation = run_autoresearch(apply=apply_settings)
                save_research_marker(run_date, recommendation)
                applied = recommendation.get("applied_settings")
                best = recommendation.get("best_candidate") or {}
                notifier.send(
                    "**Auto research finished**\n"
                    f"Reason: {recommendation.get('reason', 'n/a')}\n"
                    f"Applied: `{bool(applied)}`\n"
                    f"Best return: `{float(best.get('return_pct', 0.0)):.2f}%` | "
                    f"DD: `{float(best.get('max_drawdown_pct', 0.0)):.2f}%` | "
                    f"Trades: `{int(best.get('trade_count', 0))}`"
                )
            elif clock.is_open:
                logging.info("Auto research waiting: market is open.")
            elif already_ran:
                logging.info("Auto research already ran for %s.", run_date)
            else:
                logging.info("Auto research waiting for %02d:00 ET or premarket window.", start_hour)
        except Exception:
            logging.exception("Auto research loop failed; will retry later.")
            DiscordNotifier.from_env().send("**Auto research failed**\nCheck Railway logs for details.")

        time.sleep(check_seconds)


def start_autoresearch_loop():
    if not env_flag("BOT_ENABLE_AUTO_RESEARCH", True):
        logging.info("BOT_ENABLE_AUTO_RESEARCH is disabled.")
        return

    worker = threading.Thread(target=run_autoresearch_loop, name="bot-autoresearch-loop", daemon=True)
    worker.start()
    logging.info("Started auto research loop thread.")


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
