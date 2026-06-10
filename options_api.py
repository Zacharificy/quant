import logging
from dataclasses import dataclass
from typing import Optional

import aiohttp

from config import Settings
from database import WatchItem


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OptionQuote:
    ticker: str
    strike: float
    option_type: str
    expiry: str
    price: float
    percent_change: float


class OptionsDataClient:
    """Broker/data API wrapper.

    This bot is paper-trading only. This client fetches market data and never
    submits orders. Adapt `_parse_quote` to your broker/data provider response.
    """

    def __init__(self, settings: Settings):
        self.base_url = settings.options_api_base_url.rstrip("/")
        self.api_key = settings.options_api_key

    async def fetch_quote(self, watch: WatchItem) -> Optional[OptionQuote]:
        if not self.base_url or not self.api_key:
            logger.warning("Options API is not configured; skipping quote fetch.")
            return None

        params = {
            "ticker": watch.ticker,
            "strike": watch.strike,
            "type": watch.option_type,
            "expiry": watch.expiry,
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}

        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(f"{self.base_url}/options/quote", params=params, timeout=15) as response:
                    response.raise_for_status()
                    payload = await response.json()
        except aiohttp.ClientError:
            logger.exception("Failed to fetch options quote for watch %s.", watch.id)
            return None

        return self._parse_quote(watch, payload)

    def _parse_quote(self, watch: WatchItem, payload: dict) -> Optional[OptionQuote]:
        try:
            price = float(payload["price"])
            percent_change = float(payload.get("percent_change", payload.get("percentChange")))
        except (KeyError, TypeError, ValueError):
            logger.exception("Options API returned an unexpected payload: %s", payload)
            return None

        return OptionQuote(
            ticker=watch.ticker,
            strike=watch.strike,
            option_type=watch.option_type,
            expiry=watch.expiry,
            price=price,
            percent_change=percent_change,
        )
