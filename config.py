import os
from dataclasses import dataclass


def _get_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _get_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    discord_token: str
    alert_channel_id: int
    database_path: str
    poll_seconds: int
    default_price_change: float
    default_percent_change: float
    options_api_base_url: str
    options_api_key: str


def load_settings() -> Settings:
    return Settings(
        discord_token=os.getenv("DISCORD_TOKEN", ""),
        alert_channel_id=_get_int("ALERT_CHANNEL_ID", 0),
        database_path=os.getenv("DATABASE_PATH", "watchlist.db"),
        poll_seconds=_get_int("POLL_SECONDS", 60),
        default_price_change=_get_float("DEFAULT_PRICE_CHANGE", 0.25),
        default_percent_change=_get_float("DEFAULT_PERCENT_CHANGE", 10.0),
        options_api_base_url=os.getenv("OPTIONS_API_BASE_URL", ""),
        options_api_key=os.getenv("OPTIONS_API_KEY", ""),
    )
