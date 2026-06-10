import logging
import os
import threading
import time
from datetime import datetime, timezone

from alpaca_stock_bot import AlpacaStockBot, NY_TZ, StrategyConfig
from dashboard import app


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


def start_background_loop():
    if not env_flag("BOT_ENABLE_AUTO_LOOP", True):
        logging.info("BOT_ENABLE_AUTO_LOOP is disabled. Dashboard only.")
        return

    worker = threading.Thread(target=run_scan_loop, name="bot-scan-loop", daemon=True)
    worker.start()
    logging.info("Started bot scan loop thread.")


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    start_background_loop()

    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8080"))
    logging.info("Starting Railway dashboard on %s:%s", host, port)
    app.run(host=host, port=port, use_reloader=False)


if __name__ == "__main__":
    main()
