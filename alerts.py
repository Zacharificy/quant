import logging

import discord
from discord.ext import tasks

from config import Settings
from database import WatchItem, WatchlistStore
from options_api import OptionQuote, OptionsDataClient


logger = logging.getLogger(__name__)


class AlertService:
    def __init__(
        self,
        bot: discord.Client,
        settings: Settings,
        store: WatchlistStore,
        options_client: OptionsDataClient,
    ):
        self.bot = bot
        self.settings = settings
        self.store = store
        self.options_client = options_client
        self._task = tasks.loop(seconds=settings.poll_seconds)(self.check_alerts)

    def start(self) -> None:
        if not self._task.is_running():
            self._task.start()

    async def check_alerts(self) -> None:
        if self.settings.alert_channel_id == 0:
            logger.warning("ALERT_CHANNEL_ID is not configured; alerts will not be sent.")
            return

        channel = self.bot.get_channel(self.settings.alert_channel_id)
        if channel is None:
            logger.warning("Could not find alert channel %s.", self.settings.alert_channel_id)
            return

        for watch in self.store.list_watches():
            quote = await self.options_client.fetch_quote(watch)
            if quote is None:
                continue

            should_alert, reason = self._should_alert(watch, quote)
            self.store.update_snapshot(watch.id, quote.price, quote.percent_change)

            if should_alert:
                await channel.send(self._format_alert(watch, quote, reason))

    @staticmethod
    def _should_alert(watch: WatchItem, quote: OptionQuote) -> tuple[bool, str]:
        if watch.last_price is not None:
            price_delta = abs(quote.price - watch.last_price)
            if price_delta >= watch.price_change:
                return True, f"price moved ${price_delta:.2f}"

        if abs(quote.percent_change) >= watch.percent_change:
            return True, f"percent change is {quote.percent_change:.2f}%"

        return False, ""

    @staticmethod
    def _format_alert(watch: WatchItem, quote: OptionQuote, reason: str) -> str:
        return (
            "**Paper Trading Alert**\n"
            f"{quote.ticker} {quote.expiry} {quote.strike:g} {quote.option_type.upper()}\n"
            f"Price: ${quote.price:.2f} | Change: {quote.percent_change:.2f}%\n"
            f"Trigger: {reason}\n"
            "_No live orders were placed._"
        )
