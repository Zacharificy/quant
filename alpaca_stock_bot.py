import argparse
import html
import json
import logging
import math
import os
import re
import time
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import pandas as pd
from alpaca.common.exceptions import APIError
from alpaca.data.enums import DataFeed, OptionsFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.historical.news import NewsClient
from alpaca.data.historical.option import OptionHistoricalDataClient
from alpaca.data.requests import NewsRequest, OptionLatestQuoteRequest, StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import ContractType, OrderClass, OrderSide, OrderType, PositionIntent, QueryOrderStatus, TimeInForce
from alpaca.trading.requests import (
    GetOptionContractsRequest,
    GetOrdersRequest,
    LimitOrderRequest,
    MarketOrderRequest,
    StopLossRequest,
    TakeProfitRequest,
)
from dotenv import load_dotenv

from discord_notifier import DiscordNotifier


NY_TZ = ZoneInfo("America/New_York")
DEFAULT_WATCHLIST_PATH = Path("watchlist.json")
DEFAULT_LEVELS_PATH = Path("trade_levels.json")
OPTION_CONTRACT_MULTIPLIER = 100
DEFAULT_EXTERNAL_MACRO_RSS_URLS = (
    "https://trumpstruth.org/feed",
    "https://www.federalreserve.gov/feeds/press_all.xml",
)
TRUSTED_EXTERNAL_NEWS_DOMAINS = (
    "trumpstruth.org",
    "federalreserve.gov",
)
DEFAULT_TICKERS = (
    "SPY",
    "QQQ",
    "IWM",
    "DIA",
    "AAPL",
    "MSFT",
    "NVDA",
    "AMD",
    "PLTR",
    "SOFI",
)
LIQUID_FOCUS_TICKERS = (
    "SPY",
    "QQQ",
    "IWM",
    "DIA",
    "AAPL",
    "MSFT",
    "NVDA",
    "AMD",
    "AVGO",
)

TICKER_BUCKETS = {
    "SPY": "broad_index",
    "QQQ": "growth_index",
    "IWM": "small_cap_index",
    "DIA": "blue_chip_index",
    "AAPL": "mega_cap_tech",
    "MSFT": "mega_cap_tech",
    "NVDA": "semiconductor",
    "AMD": "semiconductor",
    "AVGO": "semiconductor",
    "MU": "semiconductor",
    "MRVL": "semiconductor",
    "SMCI": "semiconductor",
    "PLTR": "software",
    "SOFI": "fintech",
    "SNOW": "software",
    "F": "auto",
    "AMC": "meme_stock",
    "HPE": "hardware",
    "NOK": "telecom",
    "SPCE": "speculative",
    "APLD": "data_center",
    "MARA": "crypto_beta",
    "IREN": "crypto_beta",
}


@dataclass(frozen=True)
class StrategyConfig:
    tickers: tuple[str, ...] = DEFAULT_TICKERS
    max_positions: int = 5
    max_positions_per_bucket: int = 2
    paper_equity_cap: float = 1500.0
    position_pct: float = 0.40
    max_stock_trade_cash: float = 600.0
    target_stock_risk_cash: float = 35.0
    trade_stocks: bool = True
    max_candidate_count: int = 8
    min_cross_sectional_score: float = 0.35
    min_cash_buffer: float = 25.0
    min_activity_option_score: float = 0.38
    breakout_lookback_days: int = 5
    cooldown_days: int = 7
    stop_atr_multiple: float = 2.0
    take_profit_atr_multiple: float = 4.0
    min_reward_risk_ratio: float = 2.0
    max_hold_days: int = 35
    min_score: float = 0.50
    history_days: int = 365
    min_market_score: int = 1
    max_gap_pct: float = 0.12
    max_atr_pct: float = 0.09
    min_avg_dollar_volume: float = 5_000_000.0
    max_daily_loss_cash: float = 150.0
    min_rsi: float = 45.0
    max_rsi: float = 78.0
    news_lookback_hours: int = 36
    block_on_risky_news: bool = True
    trade_options: bool = True
    option_position_pct: float = 0.35
    max_option_premium_cash: float = 650.0
    min_option_score: float = 0.50
    max_option_positions: int = 3
    max_option_contracts_per_trade: int = 1
    max_option_contracts_per_underlying: int = 1
    min_option_dte: int = 1
    max_option_dte: int = 7
    high_price_option_dte: int = 5
    low_price_option_dte: int = 1
    high_price_option_threshold: float = 100.0
    max_option_spread_pct: float = 0.45
    max_option_model_premium_ratio: float = 1.75
    min_option_abs_delta: float = 0.22
    max_option_abs_delta: float = 0.72
    max_option_theta_decay_pct: float = 0.30
    min_option_delta_theta_score: float = 1.10
    min_realized_vol: float = 0.12
    max_realized_vol: float = 1.50
    option_profit_target_pct: float = 0.60
    option_stop_loss_pct: float = 0.25
    option_trailing_stop_enabled: bool = True
    option_trail_start_r: float = 1.0
    option_trail_step_r: float = 1.0
    index_long_only: bool = True
    use_intraday_timeframes: bool = True
    intraday_lookback_days: int = 7
    ml_quality_enabled: bool = True
    min_ml_quality_samples: int = 8
    option_max_hold_days: int = 5
    cancel_stale_order_minutes: int = 30
    min_learning_trades_per_setup: int = 6
    min_learning_trades_broad: int = 10
    min_risk_learning_trades: int = 6
    allow_stock_after_option: bool = True
    block_on_macro_news: bool = True
    macro_relief_score_boost: float = 0.12
    use_external_macro_news: bool = True
    use_insiderfinance_gex: bool = True
    insiderfinance_gex_cache_minutes: int = 20
    insiderfinance_gex_tickers: tuple[str, ...] = ("SPY", "QQQ", "IWM", "DIA")
    min_news_items_with_content: int = 10
    news_impact_alerts_enabled: bool = True
    news_impact_alert_cooldown_hours: int = 6
    news_impact_max_alerts_per_scan: int = 1
    news_impact_max_tickers: int = 4
    news_impact_mention_user_id: str = "1270486587402358784"
    macro_news_keywords: tuple[str, ...] = (
        "war",
        "invasion",
        "missile",
        "airstrike",
        "nuclear",
        "terror",
        "terrorist",
        "sanction",
        "tariff",
        "fed emergency",
        "rate shock",
        "cpi surprise",
        "market crash",
        "circuit breaker",
        "bank crisis",
        "default",
        "debt ceiling",
    )
    risky_news_keywords: tuple[str, ...] = (
        "bankruptcy",
        "chapter 11",
        "delisting",
        "fraud",
        "investigation",
        "lawsuit",
        "offering",
        "dilution",
        "sec charges",
        "halted",
        "recall",
        "downgrade",
        "misses estimates",
        "earnings",
        "guidance cut",
    )


def load_state(path: Path) -> dict:
    if not path.exists():
        return {
            "positions": {},
            "option_positions": {},
            "last_exit_dates": {},
            "trade_history": {},
            "learning": {},
            "open_orders": {},
            "safety": {},
            "controls": {"trading_paused": False},
            "daily_risk": {},
        }
    with path.open("r", encoding="utf-8") as file:
        state = json.load(file)
    state.setdefault("positions", {})
    state.setdefault("option_positions", {})
    state.setdefault("last_exit_dates", {})
    state.setdefault("trade_history", {})
    state.setdefault("learning", {})
    state.setdefault("open_orders", {})
    state.setdefault("safety", {})
    state.setdefault("controls", {"trading_paused": False})
    state.setdefault("daily_risk", {})
    return state


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as file:
        json.dump(state, file, indent=2, sort_keys=True)
    tmp_path.replace(path)


def normalize_ticker(ticker: str) -> str:
    return "".join(ch for ch in ticker.upper().strip() if ch.isalnum() or ch in {".", "-"})


def env_flag(name: str, default: bool = True) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def parse_env_tickers(name: str) -> list[str]:
    tickers = []
    for part in os.getenv(name, "").split(","):
        ticker = normalize_ticker(part)
        if ticker and ticker not in tickers:
            tickers.append(ticker)
    return tickers


def read_watchlist(path: Path | None = None) -> list[str]:
    path = path or Path(os.getenv("BOT_WATCHLIST_PATH", str(DEFAULT_WATCHLIST_PATH)))
    if not path.exists():
        return list(DEFAULT_TICKERS)
    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    raw_tickers = payload.get("tickers", payload if isinstance(payload, list) else [])
    tickers = []
    for ticker in raw_tickers:
        normalized = normalize_ticker(str(ticker))
        if normalized and normalized not in tickers:
            tickers.append(normalized)
    return tickers


def save_watchlist(path: Path | None, tickers: list[str]) -> None:
    path = path or Path(os.getenv("BOT_WATCHLIST_PATH", str(DEFAULT_WATCHLIST_PATH)))
    cleaned = []
    for ticker in tickers:
        normalized = normalize_ticker(ticker)
        if normalized and normalized not in cleaned:
            cleaned.append(normalized)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump({"tickers": cleaned}, file, indent=2)


def read_trade_levels(path: Path | None = None) -> dict:
    path = path or Path(os.getenv("BOT_LEVELS_PATH", str(DEFAULT_LEVELS_PATH)))
    if not path.exists():
        return {"symbols": {}}
    try:
        with path.open("r", encoding="utf-8") as file:
            payload = json.load(file)
    except Exception as exc:
        logging.warning("Could not read trade levels from %s: %s", path, exc)
        return {"symbols": {}}
    if isinstance(payload, dict) and "symbols" in payload:
        return payload
    return {"symbols": payload if isinstance(payload, dict) else {}}


def save_trade_levels(path: Path | None, levels: dict) -> None:
    path = path or Path(os.getenv("BOT_LEVELS_PATH", str(DEFAULT_LEVELS_PATH)))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(levels, file, indent=2, sort_keys=True)


def compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, pd.NA)
    return 100 - (100 / (1 + rs))


def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift()).abs()
    low_close = (df["low"] - df["close"].shift()).abs()
    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return true_range.ewm(alpha=1 / period, adjust=False).mean()


def normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def normal_pdf(value: float) -> float:
    return math.exp(-0.5 * value * value) / math.sqrt(2.0 * math.pi)


def black_scholes_terms(
    spot: float,
    strike: float,
    dte: int,
    volatility: float,
    risk_free_rate: float = 0.04,
) -> tuple[float, float, float, float] | None:
    if spot <= 0 or strike <= 0 or dte <= 0 or volatility <= 0:
        return None
    time_to_expiry = dte / 365.0
    sqrt_time = math.sqrt(time_to_expiry)
    d1 = (math.log(spot / strike) + (risk_free_rate + 0.5 * volatility * volatility) * time_to_expiry) / (
        volatility * sqrt_time
    )
    d2 = d1 - volatility * sqrt_time
    return d1, d2, time_to_expiry, sqrt_time


def black_scholes_price(
    spot: float,
    strike: float,
    dte: int,
    volatility: float,
    option_type: str,
    risk_free_rate: float = 0.04,
) -> float:
    terms = black_scholes_terms(spot, strike, dte, volatility, risk_free_rate)
    if terms is None:
        return 0.0
    d1, d2, time_to_expiry, _sqrt_time = terms
    discounted_strike = strike * math.exp(-risk_free_rate * time_to_expiry)
    if option_type.lower() == "call":
        return max(0.0, spot * normal_cdf(d1) - discounted_strike * normal_cdf(d2))
    return max(0.0, discounted_strike * normal_cdf(-d2) - spot * normal_cdf(-d1))


def black_scholes_snapshot(
    spot: float,
    strike: float,
    dte: int,
    volatility: float,
    option_type: str,
    risk_free_rate: float = 0.04,
) -> dict[str, float]:
    terms = black_scholes_terms(spot, strike, dte, volatility, risk_free_rate)
    price = black_scholes_price(spot, strike, dte, volatility, option_type, risk_free_rate)
    if terms is None:
        return {"price": price, "delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0, "rho": 0.0}
    d1, d2, time_to_expiry, sqrt_time = terms
    pdf_d1 = normal_pdf(d1)
    discounted_strike = strike * math.exp(-risk_free_rate * time_to_expiry)
    option_type = option_type.lower()
    if option_type == "call":
        delta = normal_cdf(d1)
        theta = (-(spot * pdf_d1 * volatility) / (2 * sqrt_time) - risk_free_rate * discounted_strike * normal_cdf(d2)) / 365
        rho = (strike * time_to_expiry * math.exp(-risk_free_rate * time_to_expiry) * normal_cdf(d2)) / 100
    else:
        delta = normal_cdf(d1) - 1
        theta = (-(spot * pdf_d1 * volatility) / (2 * sqrt_time) + risk_free_rate * discounted_strike * normal_cdf(-d2)) / 365
        rho = (-strike * time_to_expiry * math.exp(-risk_free_rate * time_to_expiry) * normal_cdf(-d2)) / 100
    gamma = pdf_d1 / (spot * volatility * sqrt_time)
    vega = spot * sqrt_time * pdf_d1 / 100
    return {
        "price": round(price, 4),
        "delta": round(delta, 4),
        "gamma": round(gamma, 6),
        "theta": round(theta, 4),
        "vega": round(vega, 4),
        "rho": round(rho, 4),
    }


def round_price(value: float) -> float:
    if value >= 1:
        return round(value, 2)
    return round(max(0.01, value), 2)


class AlpacaStockBot:
    def __init__(self, config: StrategyConfig):
        load_dotenv()
        config = self.load_watchlist(config)
        config = self.load_learned_settings(config)
        self.config = self.load_env_settings(config)
        self.state_path = Path(os.getenv("BOT_STATE_PATH", "alpaca_stock_bot_state.json"))
        self.state = load_state(self.state_path)
        self.data_feed = self.load_data_feed()

        api_key = os.getenv("ALPACA_PAPER_API_KEY")
        secret_key = os.getenv("ALPACA_PAPER_SECRET_KEY")
        paper = os.getenv("ALPACA_PAPER", "true").lower() == "true"
        if not api_key or not secret_key:
            raise RuntimeError("Missing ALPACA_PAPER_API_KEY or ALPACA_PAPER_SECRET_KEY in .env")
        if not paper:
            raise RuntimeError("This script is locked to paper mode. Set ALPACA_PAPER=true.")

        self.trading = TradingClient(api_key, secret_key, paper=True)
        self.data = StockHistoricalDataClient(api_key, secret_key)
        self.news = NewsClient(api_key, secret_key)
        self.option_data = OptionHistoricalDataClient(api_key, secret_key)
        self.notifier = DiscordNotifier.from_env()

    @staticmethod
    def watchlist_path() -> Path:
        return Path(os.getenv("BOT_WATCHLIST_PATH", "watchlist.json"))

    @classmethod
    def load_watchlist(cls, config: StrategyConfig) -> StrategyConfig:
        path = cls.watchlist_path()
        if not path.exists():
            save_watchlist(path, list(config.tickers))
            tickers = list(config.tickers)
        else:
            tickers = read_watchlist(path)
            if not tickers:
                tickers = list(config.tickers)
        if env_flag("BOT_FOCUS_LIQUID_UNIVERSE", True):
            focused = list(LIQUID_FOCUS_TICKERS)
            extras = parse_env_tickers("BOT_EXTRA_TICKERS")
            for ticker in extras:
                if ticker not in focused:
                    focused.append(ticker)
            tickers = focused
            logging.info("Liquid-focus universe enabled: %s", ", ".join(tickers))
        return replace(config, tickers=tuple(tickers))

    @staticmethod
    def load_learned_settings(config: StrategyConfig) -> StrategyConfig:
        path = Path(os.getenv("BOT_LEARNED_SETTINGS_PATH", "learned_settings.json"))
        if not path.exists():
            return config
        with path.open("r", encoding="utf-8") as file:
            raw = json.load(file)
        allowed = {}
        for key, value in raw.items():
            if key in StrategyConfig.__dataclass_fields__:
                allowed[key] = value
        return replace(config, **allowed)

    @staticmethod
    def load_env_settings(config: StrategyConfig) -> StrategyConfig:
        """Let Railway/local env safely override live risk and scanner knobs."""

        def env_bool(name: str, current: bool) -> bool:
            raw = os.getenv(name)
            if raw is None or raw.strip() == "":
                return current
            return raw.strip().lower() in {"1", "true", "yes", "on"}

        def env_int(name: str, current: int, minimum: int | None = None) -> int:
            raw = os.getenv(name)
            if raw is None or raw.strip() == "":
                return current
            try:
                value = int(float(raw))
            except ValueError:
                logging.warning("Ignoring invalid %s=%r", name, raw)
                return current
            return max(minimum, value) if minimum is not None else value

        def env_float(name: str, current: float, minimum: float | None = None) -> float:
            raw = os.getenv(name)
            if raw is None or raw.strip() == "":
                return current
            try:
                value = float(raw)
            except ValueError:
                logging.warning("Ignoring invalid %s=%r", name, raw)
                return current
            return max(minimum, value) if minimum is not None else value

        overrides = {
            "paper_equity_cap": env_float("BOT_PAPER_EQUITY_CAP", config.paper_equity_cap, 0.0),
            "position_pct": env_float("BOT_STOCK_POSITION_PCT", config.position_pct, 0.0),
            "max_stock_trade_cash": env_float("BOT_MAX_STOCK_TRADE_CASH", config.max_stock_trade_cash, 0.0),
            "target_stock_risk_cash": env_float("BOT_TARGET_STOCK_RISK_CASH", config.target_stock_risk_cash, 0.0),
            "trade_stocks": env_bool("BOT_TRADE_STOCKS", config.trade_stocks),
            "trade_options": env_bool("BOT_TRADE_OPTIONS", config.trade_options),
            "max_positions": env_int("BOT_MAX_STOCK_POSITIONS", config.max_positions, 0),
            "max_option_positions": env_int("BOT_MAX_OPTION_POSITIONS", config.max_option_positions, 0),
            "max_candidate_count": env_int("BOT_MAX_CANDIDATE_COUNT", config.max_candidate_count, 1),
            "min_score": env_float("BOT_MIN_STOCK_SCORE", config.min_score, 0.0),
            "min_option_score": env_float("BOT_MIN_OPTION_SCORE", config.min_option_score, 0.0),
            "min_activity_option_score": env_float(
                "BOT_MIN_ACTIVITY_OPTION_SCORE", config.min_activity_option_score, 0.0
            ),
            "min_cross_sectional_score": env_float(
                "BOT_MIN_CROSS_SECTIONAL_SCORE", config.min_cross_sectional_score, 0.0
            ),
            "option_position_pct": env_float("BOT_OPTION_POSITION_PCT", config.option_position_pct, 0.0),
            "max_option_premium_cash": env_float(
                "BOT_MAX_OPTION_PREMIUM_CASH", config.max_option_premium_cash, 0.0
            ),
            "max_option_contracts_per_trade": env_int(
                "BOT_MAX_OPTION_CONTRACTS_PER_TRADE", config.max_option_contracts_per_trade, 1
            ),
            "max_option_contracts_per_underlying": env_int(
                "BOT_MAX_OPTION_CONTRACTS_PER_UNDERLYING", config.max_option_contracts_per_underlying, 1
            ),
            "min_option_dte": env_int("BOT_MIN_OPTION_DTE", config.min_option_dte, 0),
            "max_option_dte": env_int("BOT_MAX_OPTION_DTE", config.max_option_dte, 1),
            "high_price_option_dte": env_int("BOT_HIGH_PRICE_OPTION_DTE", config.high_price_option_dte, 1),
            "low_price_option_dte": env_int("BOT_LOW_PRICE_OPTION_DTE", config.low_price_option_dte, 0),
            "high_price_option_threshold": env_float(
                "BOT_HIGH_PRICE_OPTION_THRESHOLD", config.high_price_option_threshold, 0.0
            ),
            "max_option_spread_pct": env_float("BOT_MAX_OPTION_SPREAD_PCT", config.max_option_spread_pct, 0.0),
            "max_option_model_premium_ratio": env_float(
                "BOT_MAX_OPTION_MODEL_PREMIUM_RATIO", config.max_option_model_premium_ratio, 0.0
            ),
            "min_option_abs_delta": env_float("BOT_MIN_OPTION_ABS_DELTA", config.min_option_abs_delta, 0.0),
            "max_option_abs_delta": env_float("BOT_MAX_OPTION_ABS_DELTA", config.max_option_abs_delta, 0.0),
            "max_option_theta_decay_pct": env_float(
                "BOT_MAX_OPTION_THETA_DECAY_PCT", config.max_option_theta_decay_pct, 0.0
            ),
            "min_option_delta_theta_score": env_float(
                "BOT_MIN_OPTION_DELTA_THETA_SCORE", config.min_option_delta_theta_score, 0.0
            ),
            "option_profit_target_pct": env_float(
                "BOT_OPTION_PROFIT_TARGET_PCT", config.option_profit_target_pct, 0.0
            ),
            "option_stop_loss_pct": env_float("BOT_OPTION_STOP_LOSS_PCT", config.option_stop_loss_pct, 0.01),
            "option_trailing_stop_enabled": env_bool(
                "BOT_OPTION_TRAILING_STOP_ENABLED", config.option_trailing_stop_enabled
            ),
            "option_trail_start_r": env_float("BOT_OPTION_TRAIL_START_R", config.option_trail_start_r, 0.0),
            "option_trail_step_r": env_float("BOT_OPTION_TRAIL_STEP_R", config.option_trail_step_r, 0.1),
            "index_long_only": env_bool("BOT_INDEX_LONG_ONLY", config.index_long_only),
            "use_intraday_timeframes": env_bool("BOT_USE_INTRADAY_TIMEFRAMES", config.use_intraday_timeframes),
            "intraday_lookback_days": env_int("BOT_INTRADAY_LOOKBACK_DAYS", config.intraday_lookback_days, 1),
            "ml_quality_enabled": env_bool("BOT_ML_QUALITY_ENABLED", config.ml_quality_enabled),
            "min_ml_quality_samples": env_int("BOT_MIN_ML_QUALITY_SAMPLES", config.min_ml_quality_samples, 3),
            "news_impact_alerts_enabled": env_bool(
                "BOT_NEWS_IMPACT_ALERTS_ENABLED", config.news_impact_alerts_enabled
            ),
            "news_impact_alert_cooldown_hours": env_int(
                "BOT_NEWS_IMPACT_ALERT_COOLDOWN_HOURS", config.news_impact_alert_cooldown_hours, 1
            ),
            "news_impact_max_alerts_per_scan": env_int(
                "BOT_NEWS_IMPACT_MAX_ALERTS_PER_SCAN", config.news_impact_max_alerts_per_scan, 1
            ),
            "news_impact_max_tickers": env_int(
                "BOT_NEWS_IMPACT_MAX_TICKERS", config.news_impact_max_tickers, 1
            ),
            "option_max_hold_days": env_int("BOT_OPTION_MAX_HOLD_DAYS", config.option_max_hold_days, 1),
            "min_learning_trades_per_setup": env_int(
                "BOT_MIN_LEARNING_TRADES_PER_SETUP", config.min_learning_trades_per_setup, 1
            ),
            "min_learning_trades_broad": env_int(
                "BOT_MIN_LEARNING_TRADES_BROAD", config.min_learning_trades_broad, 1
            ),
            "min_risk_learning_trades": env_int(
                "BOT_MIN_RISK_LEARNING_TRADES", config.min_risk_learning_trades, 1
            ),
            "allow_stock_after_option": env_bool("BOT_ALLOW_STOCK_AFTER_OPTION", config.allow_stock_after_option),
            "min_market_score": env_int("BOT_MIN_MARKET_SCORE", config.min_market_score, 0),
            "max_gap_pct": env_float("BOT_MAX_GAP_PCT", config.max_gap_pct, 0.0),
            "max_atr_pct": env_float("BOT_MAX_ATR_PCT", config.max_atr_pct, 0.0),
            "block_on_risky_news": env_bool("BOT_BLOCK_ON_RISKY_NEWS", config.block_on_risky_news),
            "block_on_macro_news": env_bool("BOT_BLOCK_ON_MACRO_NEWS", config.block_on_macro_news),
            "macro_relief_score_boost": env_float(
                "BOT_MACRO_RELIEF_SCORE_BOOST", config.macro_relief_score_boost, 0.0
            ),
        }
        mention_user = os.getenv("DISCORD_NEWS_MENTION_USER_ID") or os.getenv("DISCORD_MENTION_USER_ID")
        if mention_user:
            overrides["news_impact_mention_user_id"] = "".join(ch for ch in mention_user if ch.isdigit())
        if overrides["max_option_dte"] < overrides["min_option_dte"]:
            overrides["max_option_dte"] = overrides["min_option_dte"]
        logging.info(
            "Strategy config: stocks=%s options=%s cap=%.2f max_option_positions=%s min_option_score=%.2f",
            overrides["trade_stocks"],
            overrides["trade_options"],
            overrides["paper_equity_cap"],
            overrides["max_option_positions"],
            overrides["min_option_score"],
        )
        return replace(config, **overrides)

    @staticmethod
    def load_data_feed() -> DataFeed:
        feed_name = os.getenv("ALPACA_DATA_FEED", "iex").strip().lower()
        if feed_name == "sip":
            return DataFeed.SIP
        if feed_name == "iex":
            return DataFeed.IEX
        raise RuntimeError("ALPACA_DATA_FEED must be either 'iex' or 'sip'. Use 'iex' for free Alpaca data.")

    def run_once(self) -> None:
        clock = self.trading.get_clock()
        if not clock.is_open:
            logging.info("Market is closed. Next open: %s", clock.next_open)
            self.record_entry_decision(
                "market_closed",
                [f"Market closed. Next open: {clock.next_open}"],
                {"clock_open": False},
            )
            save_state(self.state_path, self.state)
            return

        today = datetime.now(NY_TZ).date()
        self.update_daily_risk_snapshot()
        self.reconcile_open_orders(block_new_entries=False)
        self.cancel_stale_open_orders()
        if not self.reconcile_open_orders():
            self.record_entry_decision(
                "blocked_open_orders",
                ["Open order reconciliation found orders that need to finish or be cancelled first."],
            )
            save_state(self.state_path, self.state)
            return
        bars = self.fetch_all_bars()
        intraday_bars = self.fetch_intraday_bars()
        news = self.fetch_recent_news()
        positions = self.get_positions()
        self.sync_state_with_positions(positions)
        if not self.validate_state_matches_alpaca():
            self.record_entry_decision(
                "blocked_state_mismatch",
                ["Alpaca positions and local state did not match, so new entries were blocked."],
            )
            save_state(self.state_path, self.state)
            return
        self.enforce_position_limits()
        self.manage_exits(today, bars, positions)
        self.manage_option_exits(today)
        self.update_daily_risk_snapshot()

        if self.is_trading_paused():
            logging.warning("Trading is paused by local control. Exits/trims checked, no new entries.")
            self.state.setdefault("safety", {})["status"] = "paused"
            self.record_entry_decision("paused", ["Trading is paused from the dashboard or config."])
            save_state(self.state_path, self.state)
            return

        if not self.daily_risk_allows_entries():
            logging.warning("Daily loss limit reached. Exits/trims checked, no new entries.")
            self.record_entry_decision("blocked_daily_risk", ["Daily loss limit reached. Exits still run, entries blocked."])
            save_state(self.state_path, self.state)
            return

        positions = self.get_positions()
        option_positions = self.get_option_positions()
        option_entries_opened = 0
        failed_option_underlyings = set()
        option_attempts = 0
        while self.config.trade_options and len(self.state.setdefault("option_positions", {})) < self.config.max_option_positions:
            option_candidate = self.find_best_option_trade(today, bars, positions, news, failed_option_underlyings, intraday_bars)
            if not option_candidate:
                break
            option_attempts += 1
            if self.enter_option_position(*option_candidate):
                option_entries_opened += 1
                continue
            failed_option_underlyings.add(option_candidate[0])
            logging.info(
                "Option candidate %s did not produce an order; checking next ranked ticker.",
                option_candidate[0],
            )
            if option_attempts >= max(self.config.max_candidate_count, 1):
                break
        if option_entries_opened:
            logging.info("Opened/staged %d option trade(s).", option_entries_opened)
            if not self.config.allow_stock_after_option:
                self.record_entry_decision(
                    "option_entry_opened",
                    [f"Opened/staged {option_entries_opened} option trade(s). Stock fallback disabled."],
                    {
                        "option_entries_opened": option_entries_opened,
                        "option_attempts": option_attempts,
                        "remaining_bot_budget": round(self.remaining_bot_budget(), 2),
                    },
                )
                save_state(self.state_path, self.state)
                return

        if not self.config.trade_stocks:
            logging.info("Stock entries disabled; no share position will be opened.")
            self.record_entry_decision(
                "stock_entries_disabled",
                [
                    "No option order opened and stock entries are disabled."
                    if not option_entries_opened
                    else "Option order opened and stock entries are disabled."
                ],
                {"option_attempts": option_attempts, "option_entries_opened": option_entries_opened},
            )
            save_state(self.state_path, self.state)
            return

        if len(positions) >= self.config.max_positions:
            logging.info("Max positions already open: %d", len(positions))
            self.record_entry_decision(
                "max_stock_positions",
                [f"Already at max stock positions: {len(positions)}/{self.config.max_positions}."],
                {"option_attempts": option_attempts, "option_entries_opened": option_entries_opened},
            )
            save_state(self.state_path, self.state)
            return

        candidate = self.find_best_stock(today, bars, positions, news, intraday_bars)
        if candidate is None:
            logging.info("No stock passed the scanner today.")
            option_best = (self.state.get("last_option_scan") or {}).get("best") or {}
            stock_best = (self.state.get("last_scan") or {}).get("best")
            reasons = ["No stock passed the scanner today."]
            if option_entries_opened:
                reasons.insert(0, f"Opened/staged {option_entries_opened} option trade(s).")
            elif option_attempts:
                reasons.insert(0, f"Tried {option_attempts} option candidate(s), but none produced an order.")
            else:
                reasons.insert(0, "No option candidate passed the scanner.")
            self.record_entry_decision(
                "no_entry",
                reasons,
                {
                    "option_attempts": option_attempts,
                    "option_entries_opened": option_entries_opened,
                    "failed_option_underlyings": sorted(failed_option_underlyings),
                    "best_option": option_best,
                    "best_stock": stock_best,
                    "risk_multiplier": self.learning_risk_multiplier(),
                    "current_bot_exposure": round(self.current_bot_exposure_cash(), 2),
                    "remaining_bot_budget": round(self.remaining_bot_budget(), 2),
                },
            )
            save_state(self.state_path, self.state)
            return

        ticker, score, price, setup_features = candidate
        stock_order_opened = self.enter_position(ticker, score, price, setup_features)
        self.record_entry_decision(
            "entry_submitted" if stock_order_opened else "entry_sized_out",
            [
                f"Stock fallback submitted {ticker} at score {score:.2f}."
                if stock_order_opened
                else f"Stock fallback selected {ticker}, but sizing/budget blocked the order."
            ],
            {
                "ticker": ticker,
                "score": round(score, 4),
                "price": round(price, 4),
                "option_attempts": option_attempts,
                "option_entries_opened": option_entries_opened,
                "remaining_bot_budget": round(self.remaining_bot_budget(), 2),
            },
        )
        save_state(self.state_path, self.state)

    def record_entry_decision(self, status: str, reasons: list[str], details: dict | None = None) -> None:
        self.state["last_entry_decision"] = {
            "time": datetime.now(NY_TZ).isoformat(timespec="seconds"),
            "status": status,
            "reasons": reasons,
            "details": details or {},
        }

    def is_trading_paused(self) -> bool:
        return bool(self.state.setdefault("controls", {}).get("trading_paused", False))

    def set_trading_paused(self, paused: bool, reason: str = "dashboard") -> None:
        controls = self.state.setdefault("controls", {})
        controls["trading_paused"] = bool(paused)
        controls["updated_at"] = datetime.now(NY_TZ).isoformat(timespec="seconds")
        controls["reason"] = reason
        self.state.setdefault("safety", {})["status"] = "paused" if paused else "ok"
        save_state(self.state_path, self.state)

    def close_tracked_position(self, symbol: str, reason: str = "manual dashboard close") -> str:
        symbol = str(symbol).upper().strip()
        self.cancel_open_orders_for_symbol(symbol)
        position = self.trading.get_open_position(symbol)
        qty = int(float(position.qty))
        if qty <= 0:
            raise RuntimeError(f"{symbol} position quantity is not positive.")

        if symbol in self.state.setdefault("option_positions", {}):
            quote = self.get_option_quote(symbol)
            bid = quote[0] if quote else float(position.current_price)
            current_price = float(position.current_price or 0)
            limit_price = min(price for price in (bid, current_price) if price > 0) if bid > 0 or current_price > 0 else 0
            if limit_price <= 0:
                raise RuntimeError(f"{symbol} has no usable bid for a limit close.")
            order = self.close_option_position(symbol, qty, limit_price, reason, price_buffer_pct=0.10)
        else:
            order = self.submit_market_order(symbol, -qty, reason)

        actions = self.state.setdefault("manual_actions", [])
        actions.append(
            {
                "action": "close",
                "symbol": symbol,
                "qty": qty,
                "order_id": str(order.id),
                "time": datetime.now(NY_TZ).isoformat(timespec="seconds"),
                "reason": reason,
            }
        )
        del actions[:-100]
        save_state(self.state_path, self.state)
        self.notifier.order_submitted("Manual Close", symbol, qty, str(order.id), reason)
        return str(order.id)

    def trim_tracked_position(self, symbol: str, reason: str = "manual dashboard trim") -> str | None:
        symbol = str(symbol).upper().strip()
        self.cancel_open_orders_for_symbol(symbol)
        position = self.trading.get_open_position(symbol)
        qty = int(float(position.qty))
        current_price = abs(float(position.current_price))
        if qty <= 0 or current_price <= 0:
            raise RuntimeError(f"{symbol} has invalid quantity or price.")

        if symbol in self.state.setdefault("option_positions", {}):
            target_qty = self.config.max_option_contracts_per_underlying
            excess_qty = qty - target_qty
            if excess_qty <= 0:
                return None
            quote = self.get_option_quote(symbol)
            bid = quote[0] if quote else current_price
            if bid <= 0:
                raise RuntimeError(f"{symbol} has no usable bid for a limit trim.")
            order = self.close_option_position(symbol, excess_qty, bid, reason, price_buffer_pct=0.05)
        else:
            target_qty = max(1, int(self.config.max_stock_trade_cash / current_price))
            excess_qty = qty - target_qty
            if excess_qty <= 0:
                return None
            order = self.submit_market_order(symbol, -excess_qty, reason)

        actions = self.state.setdefault("manual_actions", [])
        actions.append(
            {
                "action": "trim",
                "symbol": symbol,
                "qty": excess_qty,
                "order_id": str(order.id),
                "time": datetime.now(NY_TZ).isoformat(timespec="seconds"),
                "reason": reason,
            }
        )
        del actions[:-100]
        save_state(self.state_path, self.state)
        self.notifier.order_submitted("Manual Trim", symbol, excess_qty, str(order.id), reason)
        return str(order.id)

    def cancel_open_orders_for_symbol(self, symbol: str) -> int:
        symbol = str(symbol).upper().strip()
        self.reconcile_open_orders(block_new_entries=False)
        order_ids = [
            order_id
            for order_id, order in self.state.get("open_orders", {}).items()
            if str(order.get("symbol", "")).upper().strip() == symbol
        ]
        cancelled = 0
        for order_id in order_ids:
            try:
                self.trading.cancel_order_by_id(order_id)
                cancelled += 1
            except Exception as exc:
                logging.warning("Failed to cancel open order %s for %s: %s", order_id, symbol, exc)
        if cancelled:
            time.sleep(1)
            self.reconcile_open_orders(block_new_entries=False)
            actions = self.state.setdefault("manual_actions", [])
            actions.append(
                {
                    "action": "cancel_symbol_open_orders",
                    "symbol": symbol,
                    "count": cancelled,
                    "time": datetime.now(NY_TZ).isoformat(timespec="seconds"),
                }
            )
            del actions[:-100]
        return cancelled

    def cancel_bot_open_orders(self) -> int:
        self.reconcile_open_orders(block_new_entries=False)
        order_ids = list(self.state.get("open_orders", {}))
        cancelled = 0
        for order_id in order_ids:
            try:
                self.trading.cancel_order_by_id(order_id)
                cancelled += 1
            except Exception as exc:
                logging.warning("Failed to cancel order %s: %s", order_id, exc)
        actions = self.state.setdefault("manual_actions", [])
        actions.append(
            {
                "action": "cancel_open_orders",
                "count": cancelled,
                "time": datetime.now(NY_TZ).isoformat(timespec="seconds"),
            }
        )
        del actions[:-100]
        self.reconcile_open_orders(block_new_entries=False)
        save_state(self.state_path, self.state)
        return cancelled

    def scan_only(self) -> None:
        """Refresh scanner/risk state without submitting orders."""
        today = datetime.now(NY_TZ).date()
        self.update_daily_risk_snapshot()
        self.reconcile_open_orders(block_new_entries=False)
        bars = self.fetch_all_bars()
        intraday_bars = self.fetch_intraday_bars()
        news = self.fetch_recent_news()
        positions = self.get_positions()
        self.sync_state_with_positions(positions)
        self.find_best_stock(today, bars, positions, news, intraday_bars)
        self.find_best_option_trade(today, bars, positions, news, intraday_bars=intraday_bars)
        save_state(self.state_path, self.state)

    def update_daily_risk_snapshot(self) -> dict:
        account = self.trading.get_account()
        today = datetime.now(NY_TZ).date().isoformat()
        equity = float(account.portfolio_value)
        daily = self.state.setdefault("daily_risk", {})
        if daily.get("date") != today:
            daily.clear()
            daily.update(
                {
                    "date": today,
                    "start_equity": equity,
                    "max_daily_loss_cash": self.config.max_daily_loss_cash,
                    "status": "ok",
                }
            )
        daily["current_equity"] = equity
        daily["pnl"] = round(equity - float(daily.get("start_equity", equity)), 2)
        daily["checked_at"] = datetime.now(NY_TZ).isoformat(timespec="seconds")
        if daily["pnl"] <= -abs(self.config.max_daily_loss_cash):
            daily["status"] = "blocked_daily_loss"
            self.state.setdefault("safety", {})["status"] = "blocked_daily_loss"
        elif daily.get("status") == "blocked_daily_loss":
            daily["status"] = "ok"
        return daily

    def daily_risk_allows_entries(self) -> bool:
        daily = self.update_daily_risk_snapshot()
        return daily.get("status") != "blocked_daily_loss"

    def get_open_orders(self) -> list[object]:
        request = GetOrdersRequest(status=QueryOrderStatus.OPEN, limit=100)
        try:
            return list(self.trading.get_orders(filter=request))
        except TypeError:
            return list(self.trading.get_orders(request))

    def reconcile_open_orders(self, block_new_entries: bool = True) -> bool:
        orders = self.get_open_orders()
        tracked_symbols = set(self.state.setdefault("positions", {})) | set(self.state.setdefault("option_positions", {}))
        relevant_orders = {}
        for order in orders:
            symbol = str(getattr(order, "symbol", ""))
            if symbol in self.config.tickers or symbol in tracked_symbols:
                relevant_orders[str(order.id)] = {
                    "symbol": symbol,
                    "side": str(getattr(order, "side", "")),
                    "qty": str(getattr(order, "qty", "")),
                    "type": str(getattr(order, "type", "")),
                    "status": str(getattr(order, "status", "")),
                    "limit_price": str(getattr(order, "limit_price", "") or ""),
                    "submitted_at": str(getattr(order, "submitted_at", "")),
                }
        self.state["open_orders"] = relevant_orders
        self.state.setdefault("safety", {})["open_order_count"] = len(relevant_orders)
        self.state["safety"]["checked_at"] = datetime.now(NY_TZ).isoformat(timespec="seconds")
        if relevant_orders and block_new_entries:
            logging.info("Open bot order(s) still pending: %d.", len(relevant_orders))
            self.state["safety"]["status"] = "pending_orders"
            return True
        self.state["safety"]["status"] = "ok"
        return True

    def cancel_stale_open_orders(self) -> int:
        stale_minutes = self.config.cancel_stale_order_minutes
        if stale_minutes <= 0:
            return 0
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=stale_minutes)
        cancelled = 0
        for order_id, order in list(self.state.get("open_orders", {}).items()):
            submitted_at = order.get("submitted_at", "")
            try:
                submitted = pd.Timestamp(submitted_at).to_pydatetime()
                if submitted.tzinfo is None:
                    submitted = submitted.replace(tzinfo=timezone.utc)
            except Exception:
                continue
            if submitted <= cutoff:
                try:
                    self.trading.cancel_order_by_id(order_id)
                    cancelled += 1
                    logging.warning("Cancelled stale order %s for %s", order_id, order.get("symbol", "unknown"))
                except Exception as exc:
                    logging.warning("Failed to cancel stale order %s: %s", order_id, exc)
        if cancelled:
            self.state.setdefault("manual_actions", []).append(
                {
                    "action": "cancel_stale_open_orders",
                    "count": cancelled,
                    "time": datetime.now(NY_TZ).isoformat(timespec="seconds"),
                }
            )
        return cancelled

    def validate_state_matches_alpaca(self) -> bool:
        alpaca_symbols = {str(position.symbol) for position in self.trading.get_all_positions()}
        tracked_symbols = set(self.state.setdefault("positions", {})) | set(self.state.setdefault("option_positions", {}))
        unmanaged = sorted(symbol for symbol in alpaca_symbols if symbol not in tracked_symbols)
        self.state.setdefault("safety", {})["unmanaged_symbols"] = unmanaged
        if unmanaged:
            logging.warning("Blocking new entries: unmanaged Alpaca positions found: %s", ", ".join(unmanaged))
            self.state["safety"]["status"] = "blocked_unmanaged_positions"
            return False
        return True

    def get_option_positions(self) -> dict[str, object]:
        tracked = self.state.setdefault("option_positions", {})
        open_order_symbols = {str(order.get("symbol", "")) for order in self.state.get("open_orders", {}).values()}
        positions = {}
        for position in self.trading.get_all_positions():
            if position.symbol in tracked:
                positions[position.symbol] = position
        for symbol in list(tracked):
            if symbol not in positions and symbol not in open_order_symbols:
                tracked.pop(symbol, None)
        return positions

    def open_option_underlyings(self) -> set[str]:
        tracked = self.state.setdefault("option_positions", {})
        return {str(entry.get("underlying", "")).upper() for entry in tracked.values() if entry.get("underlying")}

    @staticmethod
    def ticker_bucket(ticker: str) -> str:
        return TICKER_BUCKETS.get(ticker.upper(), "other")

    @staticmethod
    def parse_float_list(value) -> list[float]:
        if value is None:
            return []
        if isinstance(value, (int, float)):
            return [float(value)]
        if isinstance(value, str):
            parts = re.split(r"[,\\s]+", value.strip())
        else:
            parts = list(value) if isinstance(value, (list, tuple, set)) else []
        values = []
        for part in parts:
            try:
                values.append(float(part))
            except (TypeError, ValueError):
                continue
        return values

    @staticmethod
    def parse_money_value(value: str, suffix: str = "") -> float | None:
        raw = str(value or "").replace("$", "").replace(",", "").replace(" ", "").strip()
        try:
            number = float(raw)
        except ValueError:
            return None
        multiplier = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}.get(str(suffix or "").upper(), 1)
        return number * multiplier

    def fetch_insiderfinance_gex(self, ticker: str) -> dict | None:
        ticker = normalize_ticker(ticker)
        if not self.config.use_insiderfinance_gex or ticker not in self.config.insiderfinance_gex_tickers:
            return None
        cache = self.state.setdefault("insiderfinance_gex", {})
        cached = cache.get(ticker)
        if cached:
            try:
                checked_at = datetime.fromisoformat(str(cached.get("checked_at", "")))
                if datetime.now(NY_TZ) - checked_at < timedelta(minutes=self.config.insiderfinance_gex_cache_minutes):
                    return cached
            except Exception:
                pass

        url = f"https://www.insiderfinance.io/gamma-exposure/{ticker}"
        try:
            request = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 TradingConsoleGEX/1.0"},
            )
            with urllib.request.urlopen(request, timeout=8) as response:
                payload = response.read(1_200_000).decode("utf-8", errors="ignore")
        except Exception as exc:
            cache[ticker] = {
                "status": "unavailable",
                "source": url,
                "error": str(exc)[:160],
                "checked_at": datetime.now(NY_TZ).isoformat(timespec="seconds"),
            }
            return cache[ticker]

        text = self.compact_html_text(payload, limit=80_000)

        def price_after(label: str) -> float | None:
            match = re.search(rf"{re.escape(label)}[^$]{{0,80}}\$\s*(-?[\d,.]+)", text, flags=re.IGNORECASE)
            if not match:
                return None
            return self.parse_money_value(match.group(1))

        net_matches = re.findall(
            r"Net GEX:?\s*(-?\$?\s*-?[\d,.]+)\s*([KMB])?",
            text,
            flags=re.IGNORECASE,
        )
        net_gex = None
        for value, suffix in reversed(net_matches):
            parsed = self.parse_money_value(value, suffix)
            if parsed is not None:
                net_gex = parsed
                break
        status = "ok" if any(price_after(label) for label in ("Spot Price", "Zero-Gamma Level", "Call Wall", "Put Wall")) else "empty"
        result = {
            "status": status,
            "source": url,
            "checked_at": datetime.now(NY_TZ).isoformat(timespec="seconds"),
            "spot_price": price_after("Spot Price"),
            "net_gex": net_gex,
            "zero_gamma": price_after("Zero-Gamma Level") or price_after("Zero Gamma"),
            "call_wall": price_after("Call Wall"),
            "put_wall": price_after("Put Wall"),
            "peak_gex": price_after("Peak GEX Strike"),
            "max_pain": price_after("Max Pain"),
        }
        if result["net_gex"] is not None:
            result["regime"] = "negative_gamma" if result["net_gex"] < 0 else "positive_gamma"
        levels = [
            result.get("zero_gamma"),
            result.get("call_wall"),
            result.get("put_wall"),
            result.get("peak_gex"),
            result.get("max_pain"),
        ]
        result["gex_levels"] = sorted({round(float(level), 2) for level in levels if level})
        cache[ticker] = result
        return result

    def refresh_insiderfinance_gex(self) -> dict:
        results = {}
        for ticker in self.config.insiderfinance_gex_tickers:
            result = self.fetch_insiderfinance_gex(ticker)
            if result:
                results[ticker] = result
        ok_count = sum(1 for item in results.values() if item.get("status") == "ok")
        empty_count = sum(1 for item in results.values() if item.get("status") == "empty")
        unavailable_count = sum(1 for item in results.values() if item.get("status") == "unavailable")
        self.state["insiderfinance_gex_status"] = {
            "status": "ok" if ok_count else "warning",
            "checked_at": datetime.now(NY_TZ).isoformat(timespec="seconds"),
            "ok": ok_count,
            "empty": empty_count,
            "unavailable": unavailable_count,
            "tickers": list(self.config.insiderfinance_gex_tickers),
        }
        return results

    def chart_level_report(self, ticker: str, price: float, direction: str | None, atr: float | None = None) -> dict:
        manual_levels = read_trade_levels().get("symbols", {}).get(ticker.upper(), {})
        insider_gex = self.fetch_insiderfinance_gex(ticker)
        levels = dict(manual_levels or {})
        if insider_gex and insider_gex.get("status") == "ok":
            levels.setdefault("gex", [])
            levels["gex"] = self.parse_float_list(levels.get("gex")) + self.parse_float_list(insider_gex.get("gex_levels"))
            levels.setdefault("support", [])
            levels["support"] = self.parse_float_list(levels.get("support")) + self.parse_float_list([insider_gex.get("put_wall"), insider_gex.get("peak_gex")])
            levels.setdefault("resistance", [])
            levels["resistance"] = self.parse_float_list(levels.get("resistance")) + self.parse_float_list([insider_gex.get("call_wall"), insider_gex.get("zero_gamma")])
        if not levels or price <= 0:
            return {"status": "none", "score_adjustment": 0.0, "reasons": []}
        tolerance = float(levels.get("tolerance", 0.0) or 0.0)
        if tolerance <= 0:
            tolerance = max(price * 0.0025, (atr or 0.0) * 0.35, 0.35)
        supports = self.parse_float_list(levels.get("support"))
        resistances = self.parse_float_list(levels.get("resistance"))
        confirmations = self.parse_float_list(levels.get("confirmation"))
        failures = self.parse_float_list(levels.get("failure"))
        gex_levels = self.parse_float_list(levels.get("gex"))
        bearish_below = self.parse_float_list(levels.get("bearish_below"))
        bullish_above = self.parse_float_list(levels.get("bullish_above"))
        breakdown_below = self.parse_float_list(levels.get("breakdown_below"))
        reasons = []
        adjustment = 0.0
        if insider_gex and insider_gex.get("status") == "ok":
            zero_gamma = insider_gex.get("zero_gamma")
            put_wall = insider_gex.get("put_wall")
            call_wall = insider_gex.get("call_wall")
            regime = insider_gex.get("regime", "")
            if regime == "negative_gamma":
                reasons.append("InsiderFinance: negative GEX, momentum can amplify")
                adjustment += 0.01
            elif regime == "positive_gamma":
                reasons.append("InsiderFinance: positive GEX, mean reversion/pinning risk")
                adjustment -= 0.01
            if direction == "call" and zero_gamma and price < float(zero_gamma):
                reasons.append(f"below zero-gamma {float(zero_gamma):g}")
                adjustment -= 0.03
            if direction == "call" and put_wall and price >= float(put_wall):
                reasons.append(f"above put wall {float(put_wall):g}")
                adjustment += 0.02
            if direction == "put" and put_wall and price <= float(put_wall):
                reasons.append(f"below put wall {float(put_wall):g}")
                adjustment += 0.03
            if direction == "put" and call_wall and price < float(call_wall):
                reasons.append(f"below call wall {float(call_wall):g}")
                adjustment += 0.01

        active_bearish_below = max([level for level in bearish_below if price < level], default=None)
        active_bullish_above = max([level for level in bullish_above if price >= level], default=None)
        active_breakdown = max([level for level in breakdown_below if price < level], default=None)
        if active_bearish_below:
            if direction == "put":
                adjustment += 0.05
                reasons.append(f"chart bias: puts under {active_bearish_below:g}")
            elif direction == "call":
                adjustment -= 0.05
                reasons.append(f"chart bias blocks calls under {active_bearish_below:g}")
        if active_bullish_above:
            if direction == "call":
                adjustment += 0.04
                reasons.append(f"chart reclaim above {active_bullish_above:g}")
            elif direction == "put":
                adjustment -= 0.03
                reasons.append(f"put caution above reclaim {active_bullish_above:g}")
        if active_breakdown and direction == "put":
            adjustment += 0.04
            reasons.append(f"breakdown below {active_breakdown:g}")

        nearest_gex = min(gex_levels, key=lambda level: abs(price - level), default=None)
        if nearest_gex is not None and abs(price - nearest_gex) <= tolerance:
            adjustment += 0.02
            reasons.append(f"near GEX level {nearest_gex:g}")

        if direction == "call":
            below_supports = [level for level in supports if price >= level]
            above_confirmations = [level for level in confirmations if price >= level]
            overhead_resistance = [level for level in resistances if level > price]
            if below_supports:
                level = max(below_supports)
                adjustment += 0.03
                reasons.append(f"above support/retest {level:g}")
            if above_confirmations:
                level = max(above_confirmations)
                adjustment += 0.04
                reasons.append(f"above confirmation {level:g}")
            elif confirmations and price < min(confirmations) - tolerance:
                reasons.append(f"waiting for confirmation {min(confirmations):g}")
                adjustment -= 0.03
            if overhead_resistance:
                level = min(overhead_resistance)
                if level - price <= tolerance:
                    reasons.append(f"too close to resistance {level:g}")
                    adjustment -= 0.04
        elif direction == "put":
            above_resistances = [level for level in resistances if price <= level]
            below_failures = [level for level in failures if price <= level]
            nearby_support = [level for level in supports if level < price]
            if above_resistances:
                level = min(above_resistances)
                adjustment += 0.03
                reasons.append(f"below resistance {level:g}")
            if below_failures:
                level = min(below_failures)
                adjustment += 0.04
                reasons.append(f"below failure {level:g}")
            elif failures and price > max(failures) + tolerance:
                reasons.append(f"waiting for failure {max(failures):g}")
                adjustment -= 0.03
            if nearby_support:
                level = max(nearby_support)
                if price - level <= tolerance:
                    reasons.append(f"too close to support {level:g}")
                    adjustment -= 0.04
        return {
            "status": "ok",
            "score_adjustment": round(max(-0.08, min(0.08, adjustment)), 4),
            "reasons": reasons[:4],
            "levels": levels,
            "insiderfinance": insider_gex,
        }

    def pretrade_research_path(self) -> Path:
        return Path(os.getenv("BOT_TICKER_RESEARCH_PATH", "ticker_research.json"))

    def pretrade_research_report(self, ticker: str) -> dict:
        path = self.pretrade_research_path()
        if not path.exists():
            return {}
        try:
            with path.open("r", encoding="utf-8") as file:
                payload = json.load(file)
        except Exception as exc:
            logging.info("Could not read pretrade research from %s: %s", path, exc)
            return {}

        created_at = payload.get("created_at")
        if created_at:
            try:
                created = datetime.fromisoformat(str(created_at))
                if created.tzinfo is None:
                    created = created.replace(tzinfo=NY_TZ)
                age_hours = (datetime.now(NY_TZ) - created.astimezone(NY_TZ)).total_seconds() / 3600
                max_age = float(os.getenv("BOT_TICKER_RESEARCH_MAX_AGE_HOURS", "36"))
                if age_hours > max_age:
                    return {}
            except Exception:
                pass
        return (payload.get("reports") or {}).get(ticker.upper(), {})

    def apply_pretrade_research_score(
        self,
        ticker: str,
        direction: str | None,
        score: float,
        reasons: list[str],
    ) -> tuple[float, list[str]]:
        report = self.pretrade_research_report(ticker)
        if not report:
            return score, reasons

        recommendation = str(report.get("recommendation", "")).lower()
        preferred = str(report.get("preferred_direction", "")).lower()
        if recommendation == "avoid":
            research_reasons = report.get("reasons") or ["research says avoid"]
            return score, reasons + [f"pretrade research avoid: {research_reasons[0]}"]

        adjustment = 0.0
        if direction and preferred == direction and recommendation.startswith("prefer"):
            adjustment = 0.03
        elif direction and preferred and preferred != direction and recommendation.startswith("prefer"):
            adjustment = -0.05

        return max(0.0, min(1.0, score + adjustment)), reasons

    def bucket_counts(self) -> dict[str, int]:
        counts = {}
        for ticker in self.state.setdefault("positions", {}):
            bucket = self.ticker_bucket(ticker)
            counts[bucket] = counts.get(bucket, 0) + 1
        for entry in self.state.setdefault("option_positions", {}).values():
            bucket = self.ticker_bucket(str(entry.get("underlying", "")))
            counts[bucket] = counts.get(bucket, 0) + 1
        return counts

    def concentration_reasons(self, ticker: str) -> list[str]:
        bucket = self.ticker_bucket(ticker)
        current_count = self.bucket_counts().get(bucket, 0)
        if current_count >= self.config.max_positions_per_bucket:
            return [f"bucket {bucket} already has {current_count} position(s)"]
        return []

    def enforce_position_limits(self) -> None:
        """Reduce tracked positions that exceed the bot's hard per-position test limits."""
        tracked_stocks = self.state.setdefault("positions", {})
        tracked_options = self.state.setdefault("option_positions", {})

        for position in self.trading.get_all_positions():
            symbol = str(position.symbol)
            try:
                qty = int(float(position.qty))
                market_value = abs(float(position.market_value))
                current_price = abs(float(position.current_price))
            except (TypeError, ValueError):
                continue

            if symbol in tracked_options and qty > self.config.max_option_contracts_per_underlying:
                excess_qty = qty - self.config.max_option_contracts_per_underlying
                quote = self.get_option_quote(symbol)
                bid = quote[0] if quote else current_price
                logging.warning(
                    "Risk trim %s: qty=%s contract(s) exceeds max %s; selling %s contract(s)",
                    symbol,
                    qty,
                    self.config.max_option_contracts_per_underlying,
                    excess_qty,
                )
                self.close_option_position(symbol, excess_qty, bid, "risk trim excess option contracts")
                continue

            if symbol in tracked_stocks and market_value > self.config.max_stock_trade_cash * 1.25 and current_price > 0:
                target_qty = max(1, int(self.config.max_stock_trade_cash / current_price))
                excess_qty = max(0, qty - target_qty)
                if excess_qty > 0:
                    logging.warning(
                        "Risk trim %s: value %.2f exceeds max stock trade cash %.2f; selling %s",
                        symbol,
                        market_value,
                        self.config.max_stock_trade_cash,
                        excess_qty,
                    )
                    self.submit_market_order(symbol, -excess_qty, "risk trim oversized stock position")

    def current_bot_exposure_cash(self) -> float:
        tracked_stocks = set(self.state.setdefault("positions", {}))
        tracked_options = set(self.state.setdefault("option_positions", {}))
        exposure = 0.0
        for position in self.trading.get_all_positions():
            symbol = str(position.symbol)
            if symbol in tracked_stocks or symbol in tracked_options:
                try:
                    exposure += abs(float(position.market_value))
                except (TypeError, ValueError):
                    continue
        live_symbols = {str(position.symbol) for position in self.trading.get_all_positions()}
        for symbol, entry in self.state.setdefault("option_positions", {}).items():
            if symbol in live_symbols:
                continue
            try:
                contracts = int(float(entry.get("contracts", 0)))
                premium = float(entry.get("premium_per_contract", entry.get("entry_price", 0.0)))
                multiplier = int(float(entry.get("contract_multiplier", OPTION_CONTRACT_MULTIPLIER)))
            except (TypeError, ValueError):
                continue
            exposure += max(0.0, contracts * premium * multiplier)
        return exposure

    def remaining_bot_budget(self) -> float:
        return max(0.0, self.config.paper_equity_cap - self.current_bot_exposure_cash())

    def fetch_all_bars(self) -> dict[str, pd.DataFrame]:
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=self.config.history_days)
        request = StockBarsRequest(
            symbol_or_symbols=list(self.config.tickers),
            timeframe=TimeFrame.Day,
            start=start,
            end=end,
            feed=self.data_feed,
        )
        try:
            raw = self.data.get_stock_bars(request).df
        except APIError as exc:
            message = str(exc)
            if "subscription does not permit querying recent SIP data" in message:
                raise RuntimeError(
                    "Alpaca rejected SIP data. Set ALPACA_DATA_FEED=iex in .env and run again."
                ) from exc
            raise
        bars = {}
        for ticker in self.config.tickers:
            try:
                df = raw.loc[ticker].copy()
            except KeyError:
                logging.warning("No bars returned for %s", ticker)
                continue
            df = df.sort_index()
            bars[ticker] = self.add_indicators(df)
        return bars

    def fetch_intraday_bars(self) -> dict[str, dict[str, pd.DataFrame]]:
        if not self.config.use_intraday_timeframes:
            return {}
        start = datetime.now(timezone.utc) - timedelta(days=self.config.intraday_lookback_days)
        specs = {
            "5m": TimeFrame(5, TimeFrameUnit.Minute),
            "15m": TimeFrame(15, TimeFrameUnit.Minute),
            "1h": TimeFrame(1, TimeFrameUnit.Hour),
        }
        result: dict[str, dict[str, pd.DataFrame]] = {}
        status = {"status": "ok", "checked_at": datetime.now(NY_TZ).isoformat(timespec="seconds"), "frames": {}}
        for label, timeframe in specs.items():
            try:
                request = StockBarsRequest(
                    symbol_or_symbols=list(self.config.tickers),
                    timeframe=timeframe,
                    start=start,
                    end=datetime.now(timezone.utc),
                    feed=self.data_feed,
                )
                raw = self.data.get_stock_bars(request).df
            except Exception as exc:
                logging.warning("Intraday %s bars unavailable: %s", label, exc)
                status["status"] = "partial"
                status["frames"][label] = {"status": "unavailable", "error": str(exc)[:160]}
                continue
            frame_map = {}
            for ticker in self.config.tickers:
                try:
                    df = raw.loc[ticker].copy().sort_index()
                except KeyError:
                    continue
                if df.empty:
                    continue
                frame_map[ticker] = self.add_intraday_indicators(df)
            result[label] = frame_map
            status["frames"][label] = {"status": "ok", "tickers": len(frame_map)}
        self.state["last_intraday_check"] = status
        return result

    def add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df["ema_50"] = df["close"].ewm(span=50, adjust=False).mean()
        df["ema_200"] = df["close"].ewm(span=200, adjust=False).mean()
        df["rsi_14"] = compute_rsi(df["close"], 14)
        df["atr_14"] = compute_atr(df, 14)
        return df

    def add_intraday_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["ema_8"] = df["close"].ewm(span=8, adjust=False).mean()
        df["ema_21"] = df["close"].ewm(span=21, adjust=False).mean()
        df["rsi_14"] = compute_rsi(df["close"], 14)
        if "volume" in df.columns:
            df["volume_avg_20"] = df["volume"].rolling(20).mean()
        return df

    def get_positions(self) -> dict[str, object]:
        positions = {}
        for position in self.trading.get_all_positions():
            symbol = position.symbol
            if symbol in self.config.tickers:
                positions[symbol] = position
        return positions

    def sync_state_with_positions(self, positions: dict[str, object]) -> None:
        tracked = self.state.setdefault("positions", {})
        for ticker in list(tracked):
            if ticker not in positions:
                tracked.pop(ticker, None)

        for ticker, position in positions.items():
            if ticker not in tracked:
                tracked[ticker] = {
                    "entry_price": float(position.avg_entry_price),
                    "entry_date": datetime.now(NY_TZ).date().isoformat(),
                }

    def manage_exits(self, today, bars: dict[str, pd.DataFrame], positions: dict[str, object]) -> None:
        tracked = self.state.setdefault("positions", {})
        for ticker, position in positions.items():
            df = bars.get(ticker)
            if df is None or df.empty or ticker not in tracked:
                continue

            latest = df.iloc[-1]
            price = float(latest["close"])
            atr = float(latest["atr_14"])
            fast = float(latest["ema_50"])
            slow = float(latest["ema_200"])
            entry = float(tracked[ticker]["entry_price"])
            entry_date = datetime.fromisoformat(tracked[ticker]["entry_date"]).date()
            held_days = (today - entry_date).days

            reason = None
            if atr > 0 and price <= entry - self.config.stop_atr_multiple * atr:
                reason = "ATR stop"
            elif atr > 0 and price >= entry + self.config.take_profit_atr_multiple * atr:
                reason = "ATR target"
            elif held_days >= self.config.max_hold_days:
                reason = f"time stop {held_days}d"
            elif fast < slow:
                reason = "trend failed"

            if reason:
                qty = int(float(position.qty))
                if qty > 0:
                    order = self.submit_market_order(ticker, -qty, reason)
                    pnl = (price - entry) * qty
                    self.record_trade(
                        {
                            "asset_type": "stock",
                            "ticker": ticker,
                            "direction": "long",
                            "entry_date": entry_date.isoformat(),
                            "exit_date": today.isoformat(),
                            "entry_price": entry,
                            "exit_price": price,
                            "qty": qty,
                            "pnl": pnl,
                            "return_pct": pnl / (entry * qty) if entry > 0 and qty > 0 else 0,
                            "setup_features": tracked.get(ticker, {}).get("setup_features", {}),
                            "reason": reason,
                            "exit_order_id": str(order.id),
                        }
                    )
                    tracked.pop(ticker, None)
                    self.state.setdefault("last_exit_dates", {})[ticker] = today.isoformat()

    def fetch_recent_news(self) -> dict[str, list[dict[str, str]]]:
        end = datetime.now(timezone.utc)
        start = end - timedelta(hours=self.config.news_lookback_hours)
        request = NewsRequest(
            symbols=",".join(self.config.tickers),
            start=start,
            end=end,
            limit=50,
            include_content=True,
            exclude_contentless=False,
        )
        news_by_symbol = {ticker: [] for ticker in self.config.tickers}
        try:
            items = self.news.get_news(request)
        except Exception as exc:
            logging.warning("News check unavailable: %s", exc)
            self.state["news_status"] = f"unavailable: {exc}"
            return news_by_symbol

        for item in items:
            headline = getattr(item, "headline", "") or ""
            summary = getattr(item, "summary", "") or ""
            content = getattr(item, "content", "") or ""
            url = getattr(item, "url", "") or ""
            source = getattr(item, "source", "") or ""
            created_at = getattr(item, "created_at", "") or ""
            symbols = getattr(item, "symbols", []) or []
            for symbol in symbols:
                if symbol in news_by_symbol:
                    news_by_symbol[symbol].append(
                        {
                            "headline": headline,
                            "summary": summary,
                            "content": content,
                            "url": url,
                            "source": source,
                            "created_at": str(created_at),
                        }
                    )
        external_items = self.fetch_external_macro_news()
        self.refresh_insiderfinance_gex()
        for symbol in ("SPY", "QQQ", "DIA", "IWM"):
            if symbol in news_by_symbol:
                news_by_symbol[symbol].extend(external_items)
        total_items = sum(len(items) for items in news_by_symbol.values())
        content_items = sum(
            1
            for items in news_by_symbol.values()
            for item in items
            if item.get("content") or item.get("summary")
        )
        news_status = "ok" if content_items >= self.config.min_news_items_with_content else "warning_low_content"
        self.state["news_status"] = news_status
        self.state["last_news_check"] = {
            "status": news_status,
            "checked_at": datetime.now(NY_TZ).isoformat(timespec="seconds"),
            "items": total_items,
            "items_with_content": content_items,
            "external_macro_items": len(external_items),
            "lookback_hours": self.config.news_lookback_hours,
            "min_items_with_content": self.config.min_news_items_with_content,
        }
        self.process_news_impact_alerts(news_by_symbol)
        return news_by_symbol

    def process_news_impact_alerts(self, news_by_symbol: dict[str, list[dict[str, str]]]) -> None:
        if not self.config.news_impact_alerts_enabled:
            return
        self.refresh_insiderfinance_gex()
        alerts = self.detect_news_impact_alerts(news_by_symbol)
        self.state["last_news_impact_alerts"] = {
            "checked_at": datetime.now(NY_TZ).isoformat(timespec="seconds"),
            "count": len(alerts),
            "alerts": alerts[:8],
        }
        sent = 0
        max_alerts = max(1, self.config.news_impact_max_alerts_per_scan)
        max_tickers = max(1, self.config.news_impact_max_tickers)
        for alert in alerts:
            if self.news_impact_recently_sent(alert):
                continue
            short_alert = dict(alert)
            short_alert["tickers"] = list(alert.get("tickers", []))[:max_tickers]
            self.notifier.news_impact(short_alert, self.config.news_impact_mention_user_id)
            self.mark_news_impact_sent(short_alert)
            sent += 1
            if sent >= max_alerts:
                break

    def detect_news_impact_alerts(self, news_by_symbol: dict[str, list[dict[str, str]]]) -> list[dict]:
        alerts = []
        seen = set()
        for symbol, items in news_by_symbol.items():
            for item in items[:14]:
                source_domain = str(item.get("source_domain") or item.get("source") or item.get("url") or "").lower()
                truth_source = "trumpstruth.org" in source_domain or "truthsocial.com" in source_domain
                if not truth_source:
                    continue
                text = self.news_item_text(item)
                analysis = self.analyze_truth_social_market_impact(text)
                if not analysis:
                    continue
                evidence = self.best_impact_evidence(item, analysis)
                key = (analysis["event"], evidence[:120])
                if key in seen:
                    continue
                seen.add(key)
                tickers = analysis["tickers"]
                alerts.append(
                    {
                        "rule": analysis["event"],
                        "bias": analysis["bias"],
                        "direction": analysis["direction"],
                        "confidence": analysis["confidence"],
                        "tickers": tickers,
                        "headline": str(item.get("headline") or evidence or "Truth Social market impact"),
                        "evidence": evidence,
                        "reasoning": analysis["reasoning"],
                        "gex": self.news_impact_gex_summary(tickers),
                        "source": str(item.get("source_domain") or item.get("source") or item.get("url") or ""),
                        "detected_at": datetime.now(NY_TZ).isoformat(timespec="seconds"),
                    }
                )
        return alerts

    def analyze_truth_social_market_impact(self, text: str) -> dict | None:
        """Read a Truth Social post and infer likely near-term market impact.

        This is not a price oracle. It is a transparent event classifier that uses
        full post/body text, direction scores, and confidence gates before alerting.
        """
        clean = re.sub(r"\s+", " ", str(text or "")).strip()
        if len(clean) < 12:
            return None
        lowered = clean.lower()
        event_scores = self.truth_event_scores(lowered)
        if not event_scores:
            return None
        event, event_score = max(event_scores.items(), key=lambda item: item[1])
        profile = self.truth_event_profile(event)
        if not self.is_alert_worthy_market_news(clean, profile):
            return None
        bullish_score = self.phrase_score(lowered, profile["bullish"])
        bearish_score = self.phrase_score(lowered, profile["bearish"])
        modifier_score = self.phrase_score(lowered, profile.get("modifiers", ()))
        net = bullish_score - bearish_score
        if abs(net) < 1.0:
            return None
        direction = "up" if net > 0 else "down"
        confidence = min(0.95, 0.45 + (min(abs(net), 5.0) * 0.08) + min(event_score, 3.0) * 0.04 + modifier_score * 0.02)
        if confidence < 0.58:
            return None
        tickers = profile["up_tickers"] if direction == "up" else profile["down_tickers"]
        bias = f"likely {direction}"
        reasoning = self.impact_reasoning(event, direction, bullish_score, bearish_score, confidence)
        return {
            "event": event,
            "direction": direction,
            "bias": bias,
            "confidence": round(confidence, 2),
            "tickers": tickers,
            "reasoning": reasoning,
        }

    @staticmethod
    def is_alert_worthy_market_news(text: str, profile: dict) -> bool:
        lowered = str(text or "").lower()
        if len(lowered) < 40:
            return False
        fluff_terms = (
            "scott pelley",
            "60 minutes",
            "ratings",
            "fake news",
            "mainstream media",
            "journalist",
            "interview",
            "book",
            "subscribe",
            "endorsement",
            "poll",
            "campaign rally",
        )
        hard_market_terms = (
            "stock",
            "stocks",
            "market",
            "markets",
            "s&p",
            "spy",
            "nasdaq",
            "qqq",
            "futures",
            "oil",
            "energy",
            "dollar",
            "treasury",
            "rates",
            "inflation",
            "cpi",
            "fed",
            "tariff",
            "tariffs",
            "china",
            "iran",
            "israel",
            "hormuz",
            "missile",
            "strike",
            "airstrike",
            "war",
            "ceasefire",
            "sanction",
            "nvidia",
            "tesla",
            "semiconductor",
            "chip",
            "chips",
            "ev credit",
        )
        has_hard_market_term = any(term in lowered for term in hard_market_terms)
        if any(term in lowered for term in fluff_terms) and not has_hard_market_term:
            return False
        has_event = any(term in lowered for term in profile.get("event_terms", ()))
        has_direction = any(term in lowered for term in profile.get("bullish", ())) or any(
            term in lowered for term in profile.get("bearish", ())
        )
        return bool(has_event and has_direction and has_hard_market_term)

    @staticmethod
    def phrase_score(text: str, phrases: tuple[str, ...]) -> float:
        score = 0.0
        for phrase in phrases:
            if phrase in text:
                score += 1.5 if " " in phrase else 1.0
        return score

    def truth_event_scores(self, text: str) -> dict[str, float]:
        profiles = {
            name: self.truth_event_profile(name)
            for name in ("iran_geopolitics", "tariffs_trade", "ai_chips", "tesla_musk", "fed_rates")
        }
        scores = {}
        for name, profile in profiles.items():
            score = self.phrase_score(text, profile["event_terms"])
            if score > 0:
                scores[name] = score
        return scores

    @staticmethod
    def truth_event_profile(event: str) -> dict:
        profiles = {
            "iran_geopolitics": {
                "event_terms": ("iran", "israel", "missile", "strike", "war", "ceasefire", "hormuz", "oil"),
                "bullish": ("called off", "calls off", "cancel", "backed away", "stand down", "ceasefire", "peace", "deal", "talks", "de-escalat", "no attack", "will not attack"),
                "bearish": ("attack", "strike", "airstrike", "missile", "retaliation", "war", "bomb", "hormuz closed", "sanction"),
                "modifiers": ("market", "stocks", "oil", "energy", "futures", "nasdaq", "s&p"),
                "up_tickers": ["SPY", "QQQ", "TSLA", "NVDA", "AMD", "MSFT", "AAPL"],
                "down_tickers": ["SPY", "QQQ", "TSLA", "IWM"],
            },
            "tariffs_trade": {
                "event_terms": ("tariff", "trade", "china", "imports", "exports", "deal"),
                "bullish": ("delay", "pause", "exempt", "rollback", "deal", "agreement", "lower tariffs", "no tariffs"),
                "bearish": ("new tariff", "increase", "raise tariffs", "levy", "threat", "retaliatory tariff", "trade war"),
                "modifiers": ("autos", "chips", "china", "imports", "consumer", "retail"),
                "up_tickers": ["SPY", "QQQ", "TSLA", "AAPL", "NVDA", "AMD", "F"],
                "down_tickers": ["SPY", "QQQ", "TSLA", "AAPL", "NVDA", "AMD", "F"],
            },
            "ai_chips": {
                "event_terms": ("ai", "chip", "chips", "semiconductor", "nvidia", "export controls", "data center"),
                "bullish": ("approve", "approval", "fast track", "investment", "build", "deal", "partnership", "less regulation", "remove barriers"),
                "bearish": ("ban", "restrict", "export controls", "block", "investigation", "antitrust", "halt"),
                "modifiers": ("nvidia", "amd", "semiconductor", "data center", "ai"),
                "up_tickers": ["QQQ", "NVDA", "AMD", "AVGO", "MSFT", "AAPL", "SPY"],
                "down_tickers": ["QQQ", "NVDA", "AMD", "AVGO", "MSFT", "AAPL", "SPY"],
            },
            "tesla_musk": {
                "event_terms": ("tesla", "musk", "ev", "electric vehicle", "spacex", "robotaxi"),
                "bullish": ("support", "approve", "contract", "deal", "credit", "subsidy", "launch", "partnership"),
                "bearish": ("remove credit", "end credit", "investigation", "lawsuit", "ban", "cut subsidy", "contract cancelled"),
                "modifiers": ("tesla", "musk", "spacex", "ev", "robotaxi"),
                "up_tickers": ["TSLA", "QQQ", "SPY"],
                "down_tickers": ["TSLA", "QQQ", "SPY"],
            },
            "fed_rates": {
                "event_terms": ("fed", "powell", "rates", "inflation", "cpi", "jobs"),
                "bullish": ("cut rates", "rate cut", "lower rates", "dovish", "inflation cooling", "soft landing"),
                "bearish": ("higher rates", "raise rates", "hot inflation", "hawkish", "no cuts", "sticky inflation"),
                "modifiers": ("stocks", "market", "nasdaq", "s&p", "futures"),
                "up_tickers": ["SPY", "QQQ", "IWM", "TSLA", "NVDA"],
                "down_tickers": ["SPY", "QQQ", "IWM", "TSLA", "NVDA"],
            },
        }
        return profiles[event]

    @staticmethod
    def impact_reasoning(event: str, direction: str, bullish_score: float, bearish_score: float, confidence: float) -> str:
        event_name = event.replace("_", " ")
        return (
            f"{event_name}: full post scored {bullish_score:.1f} bullish vs {bearish_score:.1f} bearish, "
            f"so affected tickers are marked likely {direction} with {confidence:.0%} confidence."
        )

    def best_impact_evidence(self, item: dict[str, str], analysis: dict) -> str:
        text = self.news_item_text(item)
        event_terms = self.truth_event_profile(analysis["event"])["event_terms"]
        for term in event_terms:
            if self.news_keyword_match(text, term):
                return self.news_item_evidence(item, term, limit=260)
        return self.news_item_evidence(item, "news", limit=260)

    def news_impact_gex_summary(self, tickers: list[str]) -> str:
        parts = []
        for ticker in tickers:
            if ticker not in {"SPY", "QQQ", "IWM", "DIA"}:
                continue
            gex = (self.state.get("insiderfinance_gex") or {}).get(ticker) or {}
            if gex.get("status") != "ok":
                continue
            pieces = []
            if gex.get("regime"):
                pieces.append(str(gex.get("regime")))
            if gex.get("put_wall"):
                pieces.append(f"put wall {gex.get('put_wall')}")
            if gex.get("zero_gamma"):
                pieces.append(f"zero gamma {gex.get('zero_gamma')}")
            if gex.get("call_wall"):
                pieces.append(f"call wall {gex.get('call_wall')}")
            if pieces:
                parts.append(f"{ticker}: " + ", ".join(pieces))
        return " | ".join(parts[:4])

    @staticmethod
    def news_impact_rules() -> list[dict]:
        return [
            {
                "name": "trump_iran_deescalation",
                "truth_only": True,
                "must": ("iran",),
                "any": ("called off", "calls off", "cancel", "backed away", "ceasefire", "talks", "deal", "de-escalat"),
                "exclude": ("attack launched", "strikes begin", "missile strike"),
                "bias": "bullish risk-on",
                "tickers": ["SPY", "QQQ", "TSLA", "NVDA", "AMD", "MSFT", "AAPL"],
            },
            {
                "name": "trump_iran_escalation",
                "truth_only": True,
                "must": ("iran",),
                "any": ("strike", "attack", "missile", "war", "airstrike", "retaliation"),
                "exclude": ("called off", "calls off", "cancel", "ceasefire", "deal"),
                "bias": "bearish risk-off",
                "tickers": ["SPY", "QQQ", "TSLA", "IWM"],
            },
            {
                "name": "trump_tariff_pressure",
                "truth_only": True,
                "must": ("tariff",),
                "any": ("increase", "new tariff", "levy", "threat", "china", "imports"),
                "exclude": ("delay", "pause", "exempt", "deal"),
                "bias": "bearish trade-sensitive",
                "tickers": ["SPY", "QQQ", "TSLA", "AAPL", "NVDA", "AMD", "F"],
            },
            {
                "name": "trump_tariff_relief",
                "truth_only": True,
                "must": ("tariff",),
                "any": ("delay", "pause", "exempt", "deal", "agreement", "rollback"),
                "exclude": (),
                "bias": "bullish trade relief",
                "tickers": ["SPY", "QQQ", "TSLA", "AAPL", "NVDA", "AMD", "F"],
            },
            {
                "name": "ai_chip_policy",
                "truth_only": True,
                "must": (),
                "any": ("ai", "chip", "semiconductor", "nvidia", "export controls", "data center"),
                "exclude": (),
                "bias": "watch tech/semis",
                "tickers": ["QQQ", "NVDA", "AMD", "AVGO", "MSFT", "AAPL", "SPY"],
            },
            {
                "name": "tesla_musk_policy",
                "truth_only": True,
                "must": (),
                "any": ("tesla", "musk", "ev credit", "electric vehicle", "spacex"),
                "exclude": (),
                "bias": "watch TSLA",
                "tickers": ["TSLA", "SPY", "QQQ"],
            },
        ]

    def news_impact_recently_sent(self, alert: dict) -> bool:
        sent = self.state.setdefault("news_impact_sent", {})
        key = self.news_impact_key(alert)
        raw = sent.get(key)
        if not raw:
            return False
        try:
            last = datetime.fromisoformat(raw)
        except ValueError:
            return False
        return datetime.now(NY_TZ) - last < timedelta(hours=self.config.news_impact_alert_cooldown_hours)

    def mark_news_impact_sent(self, alert: dict) -> None:
        sent = self.state.setdefault("news_impact_sent", {})
        sent[self.news_impact_key(alert)] = datetime.now(NY_TZ).isoformat(timespec="seconds")
        cutoff = datetime.now(NY_TZ) - timedelta(days=7)
        for key, raw in list(sent.items()):
            try:
                if datetime.fromisoformat(raw) < cutoff:
                    sent.pop(key, None)
            except ValueError:
                sent.pop(key, None)

    @staticmethod
    def news_impact_key(alert: dict) -> str:
        headline = re.sub(r"\W+", "-", str(alert.get("headline", "")).lower()).strip("-")[:80]
        return f"{alert.get('rule', 'news')}:{headline}"

    def external_macro_rss_urls(self) -> list[str]:
        raw = os.getenv("EXTERNAL_MACRO_RSS_URLS", "").strip()
        if raw:
            return [url.strip() for url in raw.split(",") if url.strip()]
        return list(DEFAULT_EXTERNAL_MACRO_RSS_URLS)

    @staticmethod
    def trusted_news_domain(url: str) -> bool:
        host = urlparse(str(url or "")).netloc.lower()
        host = host[4:] if host.startswith("www.") else host
        return any(host == domain or host.endswith(f".{domain}") for domain in TRUSTED_EXTERNAL_NEWS_DOMAINS)

    @staticmethod
    def compact_html_text(value: str, limit: int = 3000) -> str:
        value = re.sub(r"(?is)<(script|style|noscript).*?>.*?</\1>", " ", value or "")
        value = re.sub(r"(?i)<br\s*/?>", " ", value)
        value = re.sub(r"(?i)</p\s*>", " ", value)
        value = html.unescape(re.sub("<[^>]+>", " ", value))
        return re.sub(r"\s+", " ", value).strip()[:limit]

    def fetch_article_excerpt(self, url: str) -> str:
        if not url or not self.trusted_news_domain(url):
            return ""
        try:
            request = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 TradingConsoleNewsCheck/1.0"},
            )
            with urllib.request.urlopen(request, timeout=6) as response:
                final_url = response.geturl()
                if not self.trusted_news_domain(final_url):
                    return ""
                payload = response.read(800_000).decode("utf-8", errors="ignore")
        except Exception as exc:
            logging.info("Could not fetch article body from %s: %s", url, exc)
            return ""
        paragraphs = re.findall(r"(?is)<p[^>]*>(.*?)</p>", payload)
        body = " ".join(self.compact_html_text(paragraph, limit=600) for paragraph in paragraphs[:8])
        body = re.sub(r"\s+", " ", body).strip()
        if len(body) < 80:
            body = self.compact_html_text(payload, limit=1800)
        return body[:1800]

    def fetch_external_macro_news(self) -> list[dict[str, str]]:
        if not self.config.use_external_macro_news:
            return []
        items = []
        source_stats = {}
        article_fetches = 0
        max_article_fetches = 6
        for url in self.external_macro_rss_urls():
            if not self.trusted_news_domain(url):
                logging.warning("Skipping untrusted external macro news source: %s", url)
                continue
            try:
                request = urllib.request.Request(
                    url,
                    headers={"User-Agent": "Mozilla/5.0 TradingConsoleNewsCheck/1.0"},
                )
                with urllib.request.urlopen(request, timeout=8) as response:
                    payload = response.read(1_000_000)
                root = ET.fromstring(payload)
            except Exception as exc:
                logging.warning("External macro news unavailable from %s: %s", url, exc)
                source_stats[url] = {"status": "unavailable", "items": 0, "error": str(exc)[:160]}
                continue
            parsed_count = 0
            for node in root.findall(".//item")[:20]:
                item = self.parse_rss_item(node, url)
                if item:
                    if not item.get("summary") and not item.get("content") and article_fetches < max_article_fetches:
                        item["content"] = self.fetch_article_excerpt(item.get("url", ""))
                        article_fetches += 1
                    item["has_body"] = bool(item.get("summary") or item.get("content"))
                    items.append(item)
                    parsed_count += 1
            source_stats[url] = {"status": "ok" if parsed_count else "empty", "items": parsed_count}
        self.state["external_macro_news"] = {
            "status": "ok" if items else "empty",
            "checked_at": datetime.now(NY_TZ).isoformat(timespec="seconds"),
            "items": len(items),
            "sources": self.external_macro_rss_urls(),
            "source_stats": source_stats,
            "trusted_domains": list(TRUSTED_EXTERNAL_NEWS_DOMAINS),
            "article_fetches": article_fetches,
        }
        return items[:40]

    @staticmethod
    def parse_rss_item(node: ET.Element, feed_url: str) -> dict[str, str] | None:
        def child_text(name: str) -> str:
            found = node.find(name)
            return found.text if found is not None and found.text else ""

        title = child_text("title").strip()
        description = child_text("description")
        content = ""
        for child in node:
            if child.tag.endswith("encoded") and child.text:
                content = child.text
                break
        if not title and not description and not content:
            return None
        url = child_text("link").strip()
        if not url or not AlpacaStockBot.trusted_news_domain(url):
            url = feed_url
        return {
            "headline": html.unescape(re.sub("<[^>]+>", " ", title)).strip(),
            "summary": AlpacaStockBot.compact_html_text(description, limit=1200),
            "content": AlpacaStockBot.compact_html_text(content, limit=1800),
            "url": url,
            "source": feed_url,
            "source_domain": urlparse(feed_url).netloc.lower(),
            "source_type": "external_macro",
            "created_at": child_text("pubDate").strip(),
        }

    def find_best_stock(
        self,
        today,
        bars: dict[str, pd.DataFrame],
        positions: dict[str, object],
        news: dict[str, list[dict[str, str]]],
        intraday_bars: dict[str, dict[str, pd.DataFrame]] | None = None,
    ):
        passed = []
        scan = {
            "time": datetime.now(NY_TZ).isoformat(timespec="seconds"),
            "market": self.market_risk_report(bars, today),
            "candidates": {},
        }
        macro_reasons = self.macro_news_reasons(news)
        if macro_reasons:
            scan["market"]["is_clear"] = False
            scan["market"].setdefault("reasons", []).extend(macro_reasons)
        if not scan["market"]["is_clear"]:
            self.state["last_scan"] = scan
            logging.info("Market risk filter blocked entries: %s", "; ".join(scan["market"]["reasons"]))
            return None

        for ticker, df in bars.items():
            reasons = []
            if ticker in positions:
                reasons.append("already held")
                scan["candidates"][ticker] = {"score": 0, "status": "blocked", "reasons": reasons}
                continue
            if self.in_cooldown(ticker, today):
                reasons.append("cooldown")
                scan["candidates"][ticker] = {"score": 0, "status": "blocked", "reasons": reasons}
                continue
            concentration_reasons = self.concentration_reasons(ticker)
            if concentration_reasons:
                scan["candidates"][ticker] = {"score": 0, "status": "blocked", "reasons": concentration_reasons}
                continue
            score, score_reasons = self.score_long_stock_trade(ticker, df)
            reasons.extend(score_reasons)
            reasons.extend(self.ticker_risk_reasons(ticker, df, news.get(ticker, [])))
            features = {}
            ml_note = []
            if not reasons:
                score = self.apply_macro_relief_score(ticker, "call", score)
                features = self.setup_features(ticker, "call", df, intraday_bars or {})
                score, ml_note = self.apply_ml_quality_score(score, features)
                score = self.apply_learning_score(score, "stock", ticker, "long")
            if score < self.config.min_score:
                reasons.append(f"score {score:.2f} below {self.config.min_score:.2f}")
            if reasons:
                scan["candidates"][ticker] = {"score": round(score, 3), "status": "blocked", "reasons": reasons[:6]}
                continue
            price = float(df.iloc[-1]["close"])
            rank_score = self.cross_sectional_score(score, df, "long")
            passed.append((ticker, rank_score, price, score))
            scan["candidates"][ticker] = {
                "score": round(rank_score, 3),
                "base_score": round(score, 3),
                "status": "passed",
                "reasons": ml_note[:2],
                "features": features,
            }
        passed.sort(key=lambda item: item[1], reverse=True)
        best = passed[0] if passed else None
        for ticker, rank_score, _price, _base_score in passed[self.config.max_candidate_count :]:
            scan["candidates"][ticker]["status"] = "blocked"
            scan["candidates"][ticker]["reasons"] = ["outside top ranked candidates"]
        if best and best[1] < self.config.min_cross_sectional_score:
            scan["candidates"][best[0]]["status"] = "blocked"
            scan["candidates"][best[0]]["reasons"] = [
                f"rank score {best[1]:.2f} below {self.config.min_cross_sectional_score:.2f}"
            ]
            best = None
        scan["best"] = best[0] if best else None
        self.state["last_scan"] = scan
        if not best:
            return None
        best_features = (scan["candidates"].get(best[0]) or {}).get("features", {})
        return best[0], best[1], best[2], best_features

    def find_best_option_trade(
        self,
        today,
        bars: dict[str, pd.DataFrame],
        positions: dict[str, object],
        news: dict[str, list[dict[str, str]]],
        skip_tickers: set[str] | None = None,
        intraday_bars: dict[str, dict[str, pd.DataFrame]] | None = None,
    ):
        skip_tickers = skip_tickers or set()
        option_scan = {
            "time": datetime.now(NY_TZ).isoformat(timespec="seconds"),
            "best": None,
            "candidates": {},
        }
        market_report = self.market_risk_report(bars, today)
        macro_reasons = self.macro_news_reasons(news)
        if macro_reasons:
            market_report["is_clear"] = False
            market_report.setdefault("reasons", []).extend(macro_reasons)
        option_scan["market"] = market_report
        if not market_report["is_clear"]:
            self.state["last_option_scan"] = option_scan
            return None

        passed = []
        open_option_underlyings = self.open_option_underlyings()
        for ticker, df in bars.items():
            if ticker in skip_tickers:
                option_scan["candidates"][ticker] = {
                    "direction": None,
                    "score": 0,
                    "status": "blocked",
                    "reasons": ["previous option candidate failed this scan"],
                }
                continue
            if ticker in positions or self.in_cooldown(ticker, today):
                continue
            concentration_reasons = self.concentration_reasons(ticker)
            if concentration_reasons:
                option_scan["candidates"][ticker] = {
                    "direction": None,
                    "score": 0,
                    "status": "blocked",
                    "reasons": concentration_reasons,
                }
                continue
            if ticker in open_option_underlyings:
                option_scan["candidates"][ticker] = {
                    "direction": None,
                    "score": 0,
                    "status": "blocked",
                    "reasons": ["option already open for underlying"],
                }
                continue
            direction, score, reasons = self.score_directional_trade(ticker, df)
            if self.config.index_long_only and ticker in {"SPY", "QQQ", "IWM", "DIA"} and direction == "put":
                score, reasons = self.score_stock(ticker, df)
                direction = "call"
                if reasons:
                    reasons = ["index long-only: skipped put; no clean call setup"] + reasons[:2]
            macro_relief = self.has_macro_relief() and ticker in {"SPY", "QQQ", "IWM", "DIA"}
            if macro_relief:
                direction = "call"
                score = max(score if not reasons else 0.0, self.config.min_option_score + self.config.macro_relief_score_boost)
                reasons = []
            if not reasons:
                score = self.apply_macro_relief_score(ticker, direction, score)
                features = self.setup_features(ticker, direction or "unknown", df, intraday_bars or {})
                score, ml_note = self.apply_ml_quality_score(score, features)
                score = self.apply_learning_score(score, "option", ticker, direction)
            else:
                features = {}
                ml_note = []
            ideal_score = max(self.config.min_score, self.config.min_option_score)
            activity_score = min(ideal_score, self.config.min_activity_option_score)
            if score < activity_score or reasons:
                option_scan["candidates"][ticker] = {
                    "direction": direction,
                    "score": round(score, 3),
                    "status": "blocked",
                    "reasons": reasons + ([f"score {score:.2f} below activity floor {activity_score:.2f}"] if score < activity_score else []),
                }
                continue
            risk_reasons = self.ticker_risk_reasons(ticker, df, news.get(ticker, []))
            if risk_reasons:
                option_scan["candidates"][ticker] = {
                    "direction": direction,
                    "score": round(score, 3),
                    "status": "blocked",
                    "reasons": risk_reasons,
                }
                continue
            latest_price = float(df.iloc[-1]["close"])
            latest_atr = float(df.iloc[-1].get("atr_14", 0.0) or 0.0)
            level_report = self.chart_level_report(ticker, latest_price, direction, latest_atr)
            if level_report["status"] == "ok":
                score = max(0.0, min(1.0, score + float(level_report["score_adjustment"])))
            score, research_reasons = self.apply_pretrade_research_score(ticker, direction, score, [])
            if research_reasons:
                option_scan["candidates"][ticker] = {
                    "direction": direction,
                    "score": round(score, 3),
                    "status": "blocked",
                    "reasons": research_reasons,
                }
                continue
            research_report = self.pretrade_research_report(ticker)
            research_note = []
            if research_report:
                recommendation = str(research_report.get("recommendation", "watch"))
                research_note = [f"research: {recommendation}"]
            rank_score = self.cross_sectional_score(score, df, direction or "long")
            passed.append((ticker, rank_score, latest_price, direction, score))
            option_scan["candidates"][ticker] = {
                "direction": direction,
                "score": round(rank_score, 3),
                "base_score": round(score, 3),
                "status": "passed" if score >= ideal_score else "watchlist",
                "reasons": (
                    ([] if score >= ideal_score else [f"below ideal {ideal_score:.2f}, allowed as best available"])
                    + [f"levels: {reason}" for reason in level_report.get("reasons", [])]
                    + (["macro relief index call"] if macro_relief else [])
                    + ml_note[:2]
                    + research_note
                ),
                "features": features,
            }
        passed.sort(key=lambda item: item[1], reverse=True)
        best = passed[0] if passed else None
        for ticker, _rank_score, _latest_price, _direction, _base_score in passed[self.config.max_candidate_count :]:
            option_scan["candidates"][ticker]["status"] = "blocked"
            option_scan["candidates"][ticker]["reasons"] = ["outside top ranked candidates"]
        if best and best[1] < self.config.min_cross_sectional_score and self.current_bot_exposure_cash() > 0:
            option_scan["candidates"][best[0]]["status"] = "blocked"
            option_scan["candidates"][best[0]]["reasons"] = [
                f"rank score {best[1]:.2f} below {self.config.min_cross_sectional_score:.2f}"
            ]
            best = None
        option_scan["best"] = {"ticker": best[0], "direction": best[3], "score": round(best[1], 3)} if best else None
        self.state["last_option_scan"] = option_scan
        if not best:
            return None
        best_features = (option_scan["candidates"].get(best[0]) or {}).get("features", {})
        return best[0], best[1], best[2], best[3], best_features

    def cross_sectional_score(self, signal_score: float, df: pd.DataFrame, direction: str = "long") -> float:
        """Rank candidates without letting medium-term trend dominate the setup."""
        if len(df) < 130:
            return signal_score
        latest = df.iloc[-1]
        raw_values = (latest["close"], latest["atr_14"], df["close"].iloc[-64], df["close"].iloc[-127])
        if any(pd.isna(value) for value in raw_values):
            return signal_score
        price, atr, close_3m, close_6m = (float(value) for value in raw_values)
        if price <= 0 or atr <= 0 or close_3m <= 0 or close_6m <= 0:
            return signal_score
        momentum_3m = price / close_3m - 1
        momentum_6m = price / close_6m - 1
        directional_momentum = (momentum_3m * 0.55) + (momentum_6m * 0.45)
        if direction == "put":
            directional_momentum *= -1
        momentum_score = max(0.0, min(directional_momentum / 0.35, 1.0))
        volatility_score = 1 - min((atr / price) / self.config.max_atr_pct, 1)
        return max(0.0, min((signal_score * 0.75) + (momentum_score * 0.10) + (volatility_score * 0.15), 1.0))

    def setup_features(
        self,
        ticker: str,
        direction: str,
        daily_df: pd.DataFrame,
        intraday_bars: dict[str, dict[str, pd.DataFrame]],
    ) -> dict:
        features = {"ticker": ticker, "direction": direction}
        if daily_df is not None and len(daily_df) >= 25:
            latest = daily_df.iloc[-1]
            prior = daily_df.iloc[-2]
            price = self.safe_float(latest.get("close"), 0.0)
            atr = self.safe_float(latest.get("atr_14"), 0.0)
            fast = self.safe_float(latest.get("ema_50"), 0.0)
            slow = self.safe_float(latest.get("ema_200"), 0.0)
            rsi = self.safe_float(latest.get("rsi_14"), 50.0)
            prior_close = self.safe_float(prior.get("close"), price)
            features.update(
                {
                    "daily_rsi_bucket": self.bucket_value(rsi, (35, 45, 55, 65, 75)),
                    "daily_atr_pct_bucket": self.bucket_value((atr / price) if price > 0 else 0, (0.015, 0.03, 0.05, 0.08)),
                    "daily_trend": "up" if price > fast > slow else "down" if price < fast < slow else "mixed",
                    "daily_green": bool(price > prior_close),
                    "long_index": bool(ticker in {"SPY", "QQQ", "IWM", "DIA"} and direction == "call"),
                }
            )
        for label in ("5m", "15m", "1h"):
            frame = (intraday_bars.get(label) or {}).get(ticker)
            if frame is None or len(frame) < 25:
                features[f"{label}_ready"] = False
                continue
            latest = frame.iloc[-1]
            previous = frame.iloc[-2]
            close = self.safe_float(latest.get("close"), 0.0)
            ema8 = self.safe_float(latest.get("ema_8"), 0.0)
            ema21 = self.safe_float(latest.get("ema_21"), 0.0)
            rsi = self.safe_float(latest.get("rsi_14"), 50.0)
            volume = self.safe_float(latest.get("volume"), 0.0)
            avg_volume = self.safe_float(latest.get("volume_avg_20"), 0.0)
            previous_close = self.safe_float(previous.get("close"), close)
            features.update(
                {
                    f"{label}_ready": True,
                    f"{label}_trend": "up" if close > ema8 > ema21 else "down" if close < ema8 < ema21 else "mixed",
                    f"{label}_rsi_bucket": self.bucket_value(rsi, (35, 45, 55, 65, 75)),
                    f"{label}_green": bool(close > previous_close),
                    f"{label}_volume": "high" if avg_volume > 0 and volume > avg_volume * 1.25 else "normal",
                }
            )
        return features

    @staticmethod
    def safe_float(value, default: float = 0.0) -> float:
        try:
            if pd.isna(value):
                return default
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def bucket_value(value: float, thresholds: tuple[float, ...]) -> str:
        for threshold in thresholds:
            if value < threshold:
                return f"<{threshold:g}"
        return f">={thresholds[-1]:g}"

    def apply_ml_quality_score(self, score: float, features: dict) -> tuple[float, list[str]]:
        if not self.config.ml_quality_enabled or not features:
            return score, []
        trades = [
            trade
            for trade in self.state.setdefault("trade_history", {}).get("closed_trades", [])
            if isinstance(trade.get("setup_features"), dict)
        ]
        if len(trades) < self.config.min_ml_quality_samples:
            features["ml_quality"] = f"untrained {len(trades)}/{self.config.min_ml_quality_samples}"
            return score, [features["ml_quality"]]
        keys = (
            "direction",
            "daily_trend",
            "daily_rsi_bucket",
            "daily_atr_pct_bucket",
            "long_index",
            "5m_trend",
            "15m_trend",
            "1h_trend",
            "15m_volume",
        )
        similar = []
        for trade in trades[-150:]:
            past = trade.get("setup_features") or {}
            matches = sum(1 for key in keys if key in features and past.get(key) == features.get(key))
            if matches >= 4:
                similar.append((matches, float(trade.get("pnl", 0.0)), float(trade.get("return_pct", 0.0))))
        if len(similar) < max(3, self.config.min_ml_quality_samples // 2):
            features["ml_quality"] = f"low sample {len(similar)} similar"
            return score, [features["ml_quality"]]
        weighted_pnl = sum(pnl * matches for matches, pnl, _ret in similar)
        weight = sum(matches for matches, _pnl, _ret in similar)
        avg_pnl = weighted_pnl / weight if weight else 0.0
        win_rate = sum(1 for _matches, pnl, _ret in similar if pnl > 0) / len(similar)
        adjustment = max(-0.08, min(0.08, (win_rate - 0.5) * 0.10 + (0.02 if avg_pnl > 0 else -0.02)))
        features["ml_quality"] = f"{len(similar)} similar, win {win_rate:.0%}, adj {adjustment:+.2f}"
        return max(0.0, min(1.0, score + adjustment)), [f"ML quality {features['ml_quality']}"]

    def score_directional_trade(self, ticker: str, df: pd.DataFrame) -> tuple[str | None, float, list[str]]:
        choices = []
        bullish_score, bullish_reasons = self.score_stock(ticker, df)
        choices.append(("call", bullish_score, bullish_reasons, "trend call"))
        bearish_score, bearish_reasons = self.score_bearish_stock(ticker, df)
        choices.append(("put", bearish_score, bearish_reasons, "trend put"))
        reversal_direction, reversal_score, reversal_reasons = self.score_reversal_trade(ticker, df)
        if reversal_direction:
            choices.append((reversal_direction, reversal_score, reversal_reasons, "reversal"))

        clean_choices = [choice for choice in choices if not choice[2]]
        if clean_choices:
            direction, score, reasons, setup = max(clean_choices, key=lambda item: item[1])
            if score > 0:
                return direction, score, reasons
        direction, score, reasons, _setup = max(choices, key=lambda item: item[1])
        return direction, score, reasons

    def score_long_stock_trade(self, ticker: str, df: pd.DataFrame) -> tuple[float, list[str]]:
        trend_score, trend_reasons = self.score_stock(ticker, df)
        reversal_direction, reversal_score, reversal_reasons = self.score_reversal_trade(ticker, df)
        if reversal_direction == "call" and not reversal_reasons and reversal_score >= trend_score:
            return reversal_score, []
        return trend_score, trend_reasons

    def score_reversal_trade(self, ticker: str, df: pd.DataFrame) -> tuple[str | None, float, list[str]]:
        """Find pullback/reversal setups so the bot is not only chasing breakouts."""
        if len(df) < 220:
            return None, 0, ["not enough history"]
        latest = df.iloc[-1]
        previous = df.iloc[-2]
        raw_values = (
            latest["close"],
            previous["close"],
            latest["ema_50"],
            latest["ema_200"],
            latest["rsi_14"],
            latest["atr_14"],
            df["low"].tail(10).min(),
            df["high"].tail(10).max(),
        )
        if any(pd.isna(value) for value in raw_values):
            return None, 0, ["indicator not ready"]
        price, prev_close, fast, slow, rsi, atr, low_10, high_10 = (float(value) for value in raw_values)
        if price <= 0 or prev_close <= 0 or atr <= 0 or low_10 <= 0 or high_10 <= 0:
            return None, 0, ["invalid reversal data"]
        if atr / price > self.config.max_atr_pct:
            return None, 0, [f"ATR too high {atr / price:.1%}"]

        bounce_from_low = price / low_10 - 1
        fade_from_high = high_10 / price - 1
        close_change = price / prev_close - 1
        above_long_trend = price > slow
        below_long_trend = price < slow

        call_score = 0.0
        call_reasons = []
        if not (28 <= rsi <= 55):
            call_reasons.append(f"call reversal RSI {rsi:.1f} outside 28-55")
        if bounce_from_low < 0.004:
            call_reasons.append("no bounce from recent low")
        if close_change < -0.02:
            call_reasons.append("latest close still falling hard")
        if not above_long_trend and price < fast:
            call_reasons.append("below both 50/200 EMA")
        if not call_reasons:
            rsi_score = 1 - min(abs(rsi - 42) / 20, 1)
            bounce_score = min(bounce_from_low / 0.045, 1)
            trend_score = 0.65 if above_long_trend else 0.35
            call_score = (rsi_score * 0.35) + (bounce_score * 0.35) + (trend_score * 0.20) + 0.10

        put_score = 0.0
        put_reasons = []
        if not (45 <= rsi <= 76):
            put_reasons.append(f"put reversal RSI {rsi:.1f} outside 45-76")
        if fade_from_high < 0.004:
            put_reasons.append("no rejection from recent high")
        if close_change > 0.02:
            put_reasons.append("latest close still squeezing up")
        if not below_long_trend and price > fast:
            put_reasons.append("above both 50/200 EMA")
        if not put_reasons:
            rsi_score = 1 - min(abs(rsi - 62) / 22, 1)
            fade_score = min(fade_from_high / 0.045, 1)
            trend_score = 0.65 if below_long_trend else 0.35
            put_score = (rsi_score * 0.35) + (fade_score * 0.35) + (trend_score * 0.20) + 0.10

        if call_score <= 0 and put_score <= 0:
            reasons = call_reasons if len(call_reasons) <= len(put_reasons) else put_reasons
            return None, 0, reasons[:3]
        if call_score >= put_score:
            return "call", max(0.0, min(call_score, 1.0)), []
        return "put", max(0.0, min(put_score, 1.0)), []

    def score_stock(self, ticker: str, df: pd.DataFrame) -> tuple[float, list[str]]:
        if len(df) < 80:
            return 0, ["not enough history"]

        latest = df.iloc[-1]
        prior = df.iloc[:-1].tail(20)
        recent = df.tail(5)
        raw_values = (
            latest["close"],
            latest["high"],
            latest["low"],
            latest["ema_50"],
            latest["ema_200"],
            latest["rsi_14"],
            latest["atr_14"],
            prior["high"].max(),
            prior["low"].min(),
        )
        if any(pd.isna(value) for value in raw_values):
            return 0, ["indicator not ready"]
        price, high, low, fast, slow, rsi, atr, resistance, support = (float(value) for value in raw_values)
        if price <= 0 or slow <= 0 or atr <= 0 or resistance <= 0 or support <= 0:
            return 0, ["invalid price/indicator data"]
        if rsi < 30 or rsi > 82:
            return 0, [f"call RSI {rsi:.1f} outside 30-82"]

        tolerance = max(price * 0.0025, atr * 0.35)
        broke_resistance = price > resistance + tolerance
        support_retest = float(recent["low"].min()) <= support + tolerance and price > support + (atr * 0.35)
        reclaimed_fast = float(df.iloc[-2]["close"]) < fast <= price
        held_prior_breakout = price > resistance and low >= resistance - tolerance
        swept_support_reclaim = low < support - tolerance and price > support + (atr * 0.25)

        structure_score = 0.0
        if broke_resistance:
            structure_score = max(structure_score, min((price - resistance) / max(atr, tolerance), 1.0))
        if support_retest:
            structure_score = max(structure_score, 0.75)
        if swept_support_reclaim:
            structure_score = max(structure_score, 0.78)
        if held_prior_breakout:
            structure_score = max(structure_score, 0.65)
        if reclaimed_fast:
            structure_score = max(structure_score, 0.55)
        if structure_score <= 0:
            return 0, [f"no call structure: support {support:.2f}, resistance {resistance:.2f}"]

        trend_context = 0.25
        if price > fast > slow:
            trend_context = 1.0
        elif price > fast:
            trend_context = 0.70
        elif price > slow:
            trend_context = 0.55
        rsi_score = 1 - min(abs(rsi - 58) / 28, 1)
        atr_score = 1 - min((atr / price) / self.config.max_atr_pct, 1)
        score = (structure_score * 0.45) + (trend_context * 0.20) + (rsi_score * 0.20) + (atr_score * 0.15)
        return score, []

    def score_bearish_stock(self, ticker: str, df: pd.DataFrame) -> tuple[float, list[str]]:
        if len(df) < 80:
            return 0, ["not enough history"]

        latest = df.iloc[-1]
        prior = df.iloc[:-1].tail(20)
        recent = df.tail(5)
        raw_values = (
            latest["close"],
            latest["high"],
            latest["low"],
            latest["ema_50"],
            latest["ema_200"],
            latest["rsi_14"],
            latest["atr_14"],
            prior["high"].max(),
            prior["low"].min(),
        )
        if any(pd.isna(value) for value in raw_values):
            return 0, ["indicator not ready"]
        price, high, low, fast, slow, rsi, atr, resistance, support = (float(value) for value in raw_values)
        if price <= 0 or slow <= 0 or atr <= 0 or resistance <= 0 or support <= 0:
            return 0, ["invalid price/indicator data"]
        if rsi < 18 or rsi > 72:
            return 0, [f"put RSI {rsi:.1f} outside 18-72"]

        tolerance = max(price * 0.0025, atr * 0.35)
        broke_support = price < support - tolerance
        resistance_reject = float(recent["high"].max()) >= resistance - tolerance and price < resistance - (atr * 0.35)
        lost_fast = float(df.iloc[-2]["close"]) > fast >= price
        held_prior_breakdown = price < support and high <= support + tolerance
        swept_resistance_reject = high > resistance + tolerance and price < resistance - (atr * 0.25)

        structure_score = 0.0
        if broke_support:
            structure_score = max(structure_score, min((support - price) / max(atr, tolerance), 1.0))
        if resistance_reject:
            structure_score = max(structure_score, 0.75)
        if swept_resistance_reject:
            structure_score = max(structure_score, 0.78)
        if held_prior_breakdown:
            structure_score = max(structure_score, 0.65)
        if lost_fast:
            structure_score = max(structure_score, 0.55)
        if structure_score <= 0:
            return 0, [f"no put structure: support {support:.2f}, resistance {resistance:.2f}"]

        trend_context = 0.25
        if price < fast < slow:
            trend_context = 1.0
        elif price < fast:
            trend_context = 0.70
        elif price < slow:
            trend_context = 0.55
        rsi_score = 1 - min(abs(rsi - 42) / 28, 1)
        atr_score = 1 - min((atr / price) / self.config.max_atr_pct, 1)
        score = (structure_score * 0.45) + (trend_context * 0.20) + (rsi_score * 0.20) + (atr_score * 0.15)
        return score, []

    def market_risk_report(self, bars: dict[str, pd.DataFrame], today: date) -> dict:
        reasons = []
        score = 0
        for ticker in ("SPY", "QQQ", "DIA"):
            df = bars.get(ticker)
            if df is None or len(df) < 220:
                reasons.append(f"{ticker} market data missing")
                continue
            latest = df.iloc[-1]
            raw_values = (latest["close"], latest["ema_50"], latest["ema_200"], latest["rsi_14"])
            if any(pd.isna(value) for value in raw_values):
                reasons.append(f"{ticker} market indicators not ready")
                continue
            price, fast, slow, rsi = (float(value) for value in raw_values)
            if price > slow and fast > slow and rsi >= 45:
                score += 1
            else:
                reasons.append(f"{ticker} weak regime")

        blocked_dates = self.blocked_dates()
        if today in blocked_dates:
            reasons.append("manual macro/event block date")

        is_clear = score >= self.config.min_market_score and today not in blocked_dates
        return {"is_clear": is_clear, "score": score, "required": self.config.min_market_score, "reasons": reasons}

    def blocked_dates(self) -> set[date]:
        raw = os.getenv("BOT_BLOCK_DATES", "")
        dates = set()
        for part in raw.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                dates.add(date.fromisoformat(part))
            except ValueError:
                logging.warning("Ignoring invalid BOT_BLOCK_DATES entry: %s", part)
        return dates

    def ticker_risk_reasons(self, ticker: str, df: pd.DataFrame, news_items: list[dict[str, str]]) -> list[str]:
        reasons = []
        if len(df) >= 2:
            latest = df.iloc[-1]
            previous = df.iloc[-2]
            raw_values = (latest["close"], previous["close"], latest["atr_14"])
            if any(pd.isna(value) for value in raw_values):
                reasons.append("risk indicators not ready")
                return reasons
            close, previous_close, atr = (float(value) for value in raw_values)
            if previous_close > 0:
                gap_pct = abs(close / previous_close - 1)
                if gap_pct > self.config.max_gap_pct:
                    reasons.append(f"large gap {gap_pct:.1%}")
            if close > 0 and atr / close > self.config.max_atr_pct:
                reasons.append(f"ATR too high {atr / close:.1%}")
            if "volume" in df.columns:
                recent = df.tail(20)
                avg_dollar_volume = float((recent["close"] * recent["volume"]).mean())
                if avg_dollar_volume < self.config.min_avg_dollar_volume:
                    reasons.append(
                        f"liquidity too low ${avg_dollar_volume / 1_000_000:.1f}M avg dollar volume"
                    )

        if self.config.block_on_risky_news:
            keyword_hit = self.risky_news_hit(news_items)
            if keyword_hit:
                reasons.append(f"risky news: {keyword_hit}")
        return reasons

    def risky_news_hit(self, news_items: list[dict[str, str]]) -> str | None:
        for item in news_items[:10]:
            if item.get("source_type") == "external_macro":
                continue
            text = self.news_item_text(item)
            for keyword in self.config.risky_news_keywords:
                if self.news_keyword_match(text, keyword):
                    return self.news_item_evidence(item, keyword)
        return None

    def macro_news_reasons(self, news: dict[str, list[dict[str, str]]]) -> list[str]:
        if not self.config.block_on_macro_news:
            self.state["macro_news"] = {"status": "disabled", "reasons": []}
            return []
        relief_reasons = self.macro_relief_reasons(news)
        reasons = []
        seen = set()
        for ticker in ("SPY", "QQQ", "DIA", "IWM"):
            for item in news.get(ticker, [])[:10]:
                text = self.news_item_text(item)
                if self.is_macro_relief_text(text):
                    continue
                if not self.is_market_moving_macro_risk_text(text):
                    continue
                for keyword in self.config.macro_news_keywords:
                    if self.news_keyword_match(text, keyword):
                        clipped = self.news_item_evidence(item, keyword, limit=160)
                        if clipped not in seen:
                            reasons.append(f"macro news: {clipped}")
                            seen.add(clipped)
                        break
        if reasons:
            self.state["news_status"] = "macro risk blocked"
            self.state["macro_news"] = {
                "status": "blocked",
                "reasons": reasons[:3],
                "relief_reasons": relief_reasons[:3],
                "checked_at": datetime.now(NY_TZ).isoformat(timespec="seconds"),
            }
        elif relief_reasons:
            self.state["macro_news"] = {
                "status": "relief",
                "reasons": relief_reasons[:3],
                "score_boost": self.config.macro_relief_score_boost,
                "checked_at": datetime.now(NY_TZ).isoformat(timespec="seconds"),
            }
        else:
            self.state["macro_news"] = {
                "status": "ok",
                "reasons": [],
                "checked_at": datetime.now(NY_TZ).isoformat(timespec="seconds"),
            }
        return reasons[:3]

    @staticmethod
    def is_market_moving_macro_risk_text(text: str) -> bool:
        lowered = str(text or "").lower()
        if len(lowered) < 40:
            return False
        risk_events = (
            "war",
            "invasion",
            "missile",
            "airstrike",
            "strike",
            "attack",
            "retaliation",
            "nuclear",
            "sanction",
            "tariff",
            "trade war",
            "fed emergency",
            "rate shock",
            "hot inflation",
            "cpi surprise",
            "bank crisis",
            "circuit breaker",
            "market crash",
            "iran",
            "israel",
            "hormuz",
        )
        market_context = (
            "stock",
            "stocks",
            "market",
            "markets",
            "s&p",
            "spy",
            "nasdaq",
            "qqq",
            "futures",
            "oil",
            "energy",
            "dollar",
            "treasury",
            "rates",
            "inflation",
            "fed",
            "china",
            "imports",
            "exports",
            "semiconductor",
            "chip",
            "tesla",
            "nvidia",
        )
        return any(term in lowered for term in risk_events) and any(term in lowered for term in market_context)

    def apply_macro_relief_score(self, ticker: str, direction: str | None, score: float) -> float:
        if ticker not in {"SPY", "QQQ", "DIA", "IWM"} or direction != "call":
            return score
        if not self.has_macro_relief():
            return score
        return max(0.0, min(1.0, score + self.config.macro_relief_score_boost))

    def has_macro_relief(self) -> bool:
        macro = self.state.get("macro_news") or {}
        return macro.get("status") == "relief"

    def macro_relief_reasons(self, news: dict[str, list[dict[str, str]]]) -> list[str]:
        reasons = []
        seen = set()
        for ticker in ("SPY", "QQQ", "DIA", "IWM"):
            for item in news.get(ticker, [])[:12]:
                text = self.news_item_text(item)
                if not self.is_macro_relief_text(text):
                    continue
                clipped = self.news_item_evidence(item, "relief", limit=160)
                if clipped not in seen:
                    reasons.append(f"macro relief: {clipped}")
                    seen.add(clipped)
        return reasons[:3]

    @staticmethod
    def is_macro_relief_text(text: str) -> bool:
        text = str(text or "").lower()
        risk_terms = (
            "iran",
            "war",
            "strike",
            "strikes",
            "airstrike",
            "attack",
            "attacks",
            "ceasefire",
            "hormuz",
            "missile",
        )
        relief_terms = (
            "called off",
            "calls off",
            "cancel",
            "cancels",
            "canceled",
            "cancelled",
            "backed away",
            "backs away",
            "peace",
            "agreement",
            "deal",
            "talks",
            "negotiations",
            "ceasefire",
            "de-escalat",
            "will end",
        )
        return any(term in text for term in risk_terms) and any(term in text for term in relief_terms)

    @staticmethod
    def news_item_text(item: dict[str, str]) -> str:
        return " ".join(
            str(item.get(field, "") or "")
            for field in ("headline", "summary", "content")
        )

    @staticmethod
    def news_keyword_match(text: str, keyword: str) -> bool:
        keyword = str(keyword or "").strip()
        if not keyword:
            return False
        escaped = re.escape(keyword)
        if " " in keyword:
            pattern = rf"(?<![a-z0-9]){escaped}(?![a-z0-9])"
        else:
            pattern = rf"\b{escaped}\b"
        return re.search(pattern, text, flags=re.IGNORECASE) is not None

    @staticmethod
    def news_item_evidence(item: dict[str, str], keyword: str, limit: int = 140) -> str:
        headline = str(item.get("headline", "") or "").strip()
        body = " ".join(
            str(item.get(field, "") or "").replace("\n", " ").strip()
            for field in ("summary", "content")
            if item.get(field)
        )
        text = body or headline
        lowered = text.lower()
        idx = lowered.find(keyword.lower())
        if idx >= 0:
            start = max(0, idx - 45)
            if start > 0:
                next_space = text.find(" ", start)
                if 0 <= next_space < idx:
                    start = next_space + 1
            snippet = text[start : start + limit].strip()
        else:
            snippet = text[:limit].strip()
        if headline and snippet and snippet not in headline:
            return f"{headline[:80]} | {snippet}"
        return (headline or snippet)[:limit]

    def learning_key(self, asset_type: str, ticker: str, direction: str) -> str:
        return f"{asset_type}:{ticker}:{direction}"

    def apply_learning_score(self, score: float, asset_type: str, ticker: str, direction: str | None) -> float:
        direction = direction or "unknown"
        learning = self.state.setdefault("learning", {})
        adjustments = learning.get("score_adjustments", {})
        keys = (
            self.learning_key(asset_type, ticker, direction),
            self.learning_key(asset_type, "*", direction),
            self.learning_key(asset_type, "*", "*"),
        )
        adjustment = sum(float(adjustments.get(key, 0.0)) for key in keys)
        return max(0.0, min(1.0, score + adjustment))

    def learning_risk_multiplier(self) -> float:
        learning = self.state.setdefault("learning", {})
        return max(0.25, min(1.0, float(learning.get("risk_multiplier", 1.0))))

    def record_trade(self, trade: dict) -> None:
        trade["closed_at"] = datetime.now(NY_TZ).isoformat(timespec="seconds")
        history = self.state.setdefault("trade_history", {})
        trades = history.setdefault("closed_trades", [])
        trades.append(trade)
        del trades[:-200]
        self.update_learning()
        self.notifier.trade_exit(trade)

    def record_entry(self, trade: dict) -> None:
        trade["opened_at"] = datetime.now(NY_TZ).isoformat(timespec="seconds")
        history = self.state.setdefault("trade_history", {})
        entries = history.setdefault("opened_trades", [])
        entries.append(trade)
        del entries[:-300]
        self.notifier.trade_entry(trade)

    def update_learning(self) -> None:
        trades = self.state.setdefault("trade_history", {}).setdefault("closed_trades", [])
        learning = self.state.setdefault("learning", {})
        adjustments = {}
        grouped = {}
        for trade in trades:
            asset_type = trade.get("asset_type", "unknown")
            ticker = trade.get("ticker", "unknown")
            direction = trade.get("direction", "unknown")
            keys = (
                self.learning_key(asset_type, ticker, direction),
                self.learning_key(asset_type, "*", direction),
                self.learning_key(asset_type, "*", "*"),
            )
            for key in keys:
                grouped.setdefault(key, []).append(trade)

        for key, key_trades in grouped.items():
            recent = key_trades[-12:]
            is_broad_key = ":*:" in key or key.endswith(":*")
            min_sample = self.config.min_learning_trades_broad if is_broad_key else self.config.min_learning_trades_per_setup
            if len(recent) < min_sample:
                continue
            avg_return = sum(float(trade.get("return_pct", 0.0)) for trade in recent) / len(recent)
            win_rate = sum(1 for trade in recent if float(trade.get("pnl", 0.0)) > 0) / len(recent)
            adjustment = (avg_return * 0.25) + ((win_rate - 0.5) * 0.03)
            if any(str(trade.get("loss_diagnosis", "")) == "direction_wrong" for trade in recent[-3:]):
                adjustment -= 0.01
            limit = 0.04 if is_broad_key else 0.08
            adjustments[key] = round(max(-limit, min(limit, adjustment)), 4)

        recent_all = trades[-10:]
        risk_multiplier = 1.0
        stats = {
            "sample_size": len(recent_all),
            "wins": 0,
            "losses": 0,
            "win_rate": None,
            "profit_factor": None,
            "consecutive_losses": 0,
        }
        if len(recent_all) >= self.config.min_risk_learning_trades:
            wins = [trade for trade in recent_all if float(trade.get("pnl", 0.0)) > 0]
            losses = [trade for trade in recent_all if float(trade.get("pnl", 0.0)) <= 0]
            gross_profit = sum(float(trade.get("pnl", 0.0)) for trade in wins)
            gross_loss = abs(sum(float(trade.get("pnl", 0.0)) for trade in losses))
            win_rate = len(wins) / len(recent_all)
            profit_factor = gross_profit / gross_loss if gross_loss else 99.0
            consecutive_losses = 0
            for trade in reversed(recent_all):
                if float(trade.get("pnl", 0.0)) <= 0:
                    consecutive_losses += 1
                else:
                    break
            stats = {
                "sample_size": len(recent_all),
                "wins": len(wins),
                "losses": len(losses),
                "win_rate": round(win_rate, 4),
                "profit_factor": round(profit_factor, 4),
                "consecutive_losses": consecutive_losses,
            }
            if consecutive_losses >= 3 or win_rate < 0.35 or profit_factor < 0.75:
                risk_multiplier = 0.5
            elif win_rate < 0.45 or profit_factor < 1.0:
                risk_multiplier = 0.7

        learning["score_adjustments"] = adjustments
        learning["risk_multiplier"] = risk_multiplier
        learning["stats"] = stats
        learning["min_setup_sample"] = self.config.min_learning_trades_per_setup
        learning["min_broad_sample"] = self.config.min_learning_trades_broad
        learning["min_risk_sample"] = self.config.min_risk_learning_trades
        learning["closed_trade_count"] = len(trades)
        learning["updated_at"] = datetime.now(NY_TZ).isoformat(timespec="seconds")

    def in_cooldown(self, ticker: str, today) -> bool:
        raw = self.state.get("last_exit_dates", {}).get(ticker)
        if raw is None:
            return False
        last_exit = datetime.fromisoformat(raw).date()
        return (today - last_exit).days < self.config.cooldown_days

    def enter_position(self, ticker: str, score: float, price: float, setup_features: dict | None = None) -> bool:
        account = self.trading.get_account()
        buying_power = float(account.buying_power)
        cash = float(account.cash)
        sizing_equity = min(float(account.portfolio_value), self.config.paper_equity_cap)
        target_cash = sizing_equity * self.config.position_pct * self.learning_risk_multiplier()
        volatility_cash = self.volatility_sized_stock_cash(ticker, price)
        available_cash = max(0, min(cash, buying_power) - self.config.min_cash_buffer)
        remaining_budget = self.remaining_bot_budget()
        order_cash = min(target_cash, volatility_cash, available_cash, remaining_budget, self.config.max_stock_trade_cash)
        quantity = int(order_cash / price)

        if remaining_budget <= 0:
            logging.warning(
                "Skip %s: bot exposure %.2f is already at/above paper cap %.2f",
                ticker,
                self.current_bot_exposure_cash(),
                self.config.paper_equity_cap,
            )
            return False
        if quantity <= 0:
            logging.info(
                "Skip %s: price %.2f is too high for order cash %.2f / remaining bot budget %.2f",
                ticker,
                price,
                order_cash,
                remaining_budget,
            )
            return False

        stop_price = None
        take_profit_price = None
        try:
            bars = self.fetch_all_bars().get(ticker)
            if bars is not None and not bars.empty:
                atr = float(bars.iloc[-1].get("atr_14", 0.0) or 0.0)
                if atr > 0:
                    stop_price = round_price(price - self.config.stop_atr_multiple * atr)
                    take_profit_price = round_price(price + self.config.take_profit_atr_multiple * atr)
        except Exception as exc:
            logging.warning("Could not calculate bracket prices for %s: %s", ticker, exc)
        if not stop_price or stop_price <= 0:
            stop_price = round_price(price * 0.93)
        if not take_profit_price or take_profit_price <= price:
            take_profit_price = round_price(price * 1.12)
        risk = price - stop_price
        reward = take_profit_price - price
        if risk <= 0:
            stop_price = round_price(price * 0.95)
            risk = price - stop_price
        if risk > 0 and reward / risk < self.config.min_reward_risk_ratio:
            take_profit_price = round_price(price + risk * self.config.min_reward_risk_ratio)

        order = self.submit_market_order(
            ticker,
            quantity,
            f"stock breakout score={score:.2f}",
            take_profit_price=take_profit_price,
            stop_loss_price=stop_price,
        )
        self.state.setdefault("positions", {})[ticker] = {
            "entry_price": price,
            "entry_date": datetime.now(NY_TZ).date().isoformat(),
            "bucket": self.ticker_bucket(ticker),
            "entry_order_id": str(order.id),
            "qty": quantity,
            "score": score,
            "setup_features": setup_features or {},
            "take_profit_price": take_profit_price,
            "stop_loss_price": stop_price,
            "protection": "bracket",
        }
        self.record_entry(
            {
                "asset_type": "stock",
                "ticker": ticker,
                "direction": "long",
                "entry_price": price,
                "qty": quantity,
                "score": score,
                "setup_features": setup_features or {},
                "entry_order_id": str(order.id),
            }
        )
        return True

    def enter_option_position(
        self,
        ticker: str,
        score: float,
        underlying_price: float,
        direction: str,
        setup_features: dict | None = None,
    ) -> bool:
        if ticker in self.open_option_underlyings():
            logging.info("Skip %s %s: option already open for this underlying", ticker, direction)
            return False

        account = self.trading.get_account()
        available_cash = max(0, min(float(account.cash), float(account.buying_power)) - self.config.min_cash_buffer)
        sizing_equity = min(float(account.portfolio_value), self.config.paper_equity_cap)
        max_premium = sizing_equity * self.config.option_position_pct * self.learning_risk_multiplier()
        remaining_budget = self.remaining_bot_budget()
        option_cash_limit = min(max_premium, available_cash, remaining_budget, self.config.max_option_premium_cash)
        if remaining_budget <= 0:
            logging.warning(
                "Skip %s %s: bot exposure %.2f is already at/above paper cap %.2f",
                ticker,
                direction,
                self.current_bot_exposure_cash(),
                self.config.paper_equity_cap,
            )
            return False
        max_contract_ask = option_cash_limit / OPTION_CONTRACT_MULTIPLIER

        contract_type = ContractType.CALL if direction == "call" else ContractType.PUT
        contract_quote = self.find_option_contract(ticker, underlying_price, contract_type, max_ask=max_contract_ask)
        if contract_quote is None:
            logging.info(
                "No affordable option contract passed filters for %s %s under %.2f ask / %.2f total",
                ticker,
                direction,
                max_contract_ask,
                option_cash_limit,
            )
            return False
        contract, quote = contract_quote

        bid, ask = quote
        if ask <= 0:
            logging.info("Skip %s: invalid option ask %.2f", contract.symbol, ask)
            return False
        spread_pct = (ask - bid) / ask if ask else 1
        if spread_pct > self.config.max_option_spread_pct:
            logging.info("Skip %s: spread %.1f%% too wide", contract.symbol, spread_pct * 100)
            return False
        dte = max(1, (contract.expiration_date - datetime.now(NY_TZ).date()).days)
        strike = float(contract.strike_price)
        realized_vol = self.realized_volatility(ticker)
        model_snapshot = black_scholes_snapshot(underlying_price, strike, dte, realized_vol, direction)
        model_price = model_snapshot["price"]
        greek_reasons = self.option_greek_reasons(model_snapshot, ask, direction)
        if greek_reasons:
            logging.info("Skip %s: %s", contract.symbol, "; ".join(greek_reasons))
            self.state.setdefault("last_option_model_checks", {})[contract.symbol] = {
                "underlying": ticker,
                "direction": direction,
                "ask": ask,
                "bid": bid,
                "spread_pct": round(spread_pct, 4),
                "model_price": round(model_price, 4),
                "realized_vol": round(realized_vol, 4),
                "dte": dte,
                "greeks": model_snapshot,
                "status": "blocked_greeks",
                "reasons": greek_reasons,
            }
            return False
        max_reasonable_ask = max(0.05, model_price * self.config.max_option_model_premium_ratio)
        if model_price > 0 and ask > max_reasonable_ask:
            logging.info(
                "Skip %s: ask %.2f is high versus model %.2f at %.1f%% realized vol",
                contract.symbol,
                ask,
                model_price,
                realized_vol * 100,
            )
            self.state.setdefault("last_option_model_checks", {})[contract.symbol] = {
                "underlying": ticker,
                "direction": direction,
                "ask": ask,
                "bid": bid,
                "spread_pct": round(spread_pct, 4),
                "model_price": round(model_price, 4),
                "realized_vol": round(realized_vol, 4),
                "dte": dte,
                "greeks": model_snapshot,
                "status": "blocked_expensive",
            }
            return False

        cost_per_contract = ask * OPTION_CONTRACT_MULTIPLIER
        contracts = min(
            self.config.max_option_contracts_per_trade,
            int(option_cash_limit / cost_per_contract) if cost_per_contract > 0 else 0,
        )
        if contracts <= 0:
            logging.info(
                "Skip %s: 1 contract costs %.2f (%s x %.2f), max cash %.2f",
                contract.symbol,
                cost_per_contract,
                OPTION_CONTRACT_MULTIPLIER,
                ask,
                option_cash_limit,
            )
            self.state.setdefault("last_option_model_checks", {})[contract.symbol] = {
                "underlying": ticker,
                "direction": direction,
                "ask": ask,
                "bid": bid,
                "contract_cost": round(cost_per_contract, 2),
                "option_cash_limit": round(option_cash_limit, 2),
                "status": "blocked_cost",
            }
            return False

        take_profit_price = round_price(ask * (1 + self.config.option_profit_target_pct))
        stop_loss_price = round_price(ask * (1 - self.config.option_stop_loss_pct))
        if self.config.option_stop_loss_pct <= 0:
            logging.warning("Skip %s: option stop loss percent must be positive", contract.symbol)
            return False
        reward_risk = self.config.option_profit_target_pct / self.config.option_stop_loss_pct
        if reward_risk < self.config.min_reward_risk_ratio:
            logging.warning(
                "Skip %s: option reward/risk %.2f is below %.2f",
                contract.symbol,
                reward_risk,
                self.config.min_reward_risk_ratio,
            )
            return False
        request = self.build_option_entry_request(
            contract.symbol,
            contracts,
            ask,
            take_profit_price=take_profit_price,
            stop_loss_price=stop_loss_price,
        )
        try:
            order = self.trading.submit_order(request)
            protection = "bracket"
        except Exception as exc:
            logging.warning("Bracket option entry failed for %s, retrying simple entry: %s", contract.symbol, exc)
            request = self.build_option_entry_request(contract.symbol, contracts, ask)
            order = self.trading.submit_order(request)
            protection = "internal_exit_rules"
        self.state.setdefault("option_positions", {})[contract.symbol] = {
            "underlying": ticker,
            "direction": direction,
            "entry_price": ask,
            "entry_date": datetime.now(NY_TZ).date().isoformat(),
            "score": score,
            "setup_features": setup_features or {},
            "bucket": self.ticker_bucket(ticker),
            "contracts": contracts,
            "contract_multiplier": OPTION_CONTRACT_MULTIPLIER,
            "premium_per_contract": ask,
            "notional_cost": cost_per_contract * contracts,
            "underlying_price_at_entry": underlying_price,
            "entry_model_price": round(model_price, 4),
            "entry_realized_vol": round(realized_vol, 4),
            "entry_spread_pct": round(spread_pct, 4),
            "entry_greeks": model_snapshot,
            "strike": strike,
            "dte_at_entry": dte,
            "entry_order_id": str(order.id),
            "take_profit_price": take_profit_price,
            "stop_loss_price": stop_loss_price,
            "protection": protection,
        }
        self.record_entry(
            {
                "asset_type": "option",
                "ticker": ticker,
                "direction": direction,
                "symbol": contract.symbol,
                "entry_price": ask,
                "contracts": contracts,
                "contract_multiplier": OPTION_CONTRACT_MULTIPLIER,
                "notional_cost": cost_per_contract * contracts,
                "underlying_price_at_entry": underlying_price,
                "entry_model_price": round(model_price, 4),
                "entry_realized_vol": round(realized_vol, 4),
                "entry_spread_pct": round(spread_pct, 4),
                "entry_greeks": model_snapshot,
                "strike": strike,
                "dte_at_entry": dte,
                "score": score,
                "setup_features": setup_features or {},
                "entry_order_id": str(order.id),
            }
        )
        logging.info(
            "BUY_TO_OPEN %s %s contracts=%s limit=%.2f cost=%.2f id=%s score=%.2f",
            direction.upper(),
            contract.symbol,
            contracts,
            ask,
            cost_per_contract * contracts,
            order.id,
            score,
        )
        return True

    def realized_volatility(self, ticker: str, lookback: int = 30) -> float:
        try:
            bars = self.fetch_all_bars().get(ticker)
        except Exception as exc:
            logging.warning("Realized volatility unavailable for %s: %s", ticker, exc)
            return 0.30
        if bars is None or len(bars) < lookback + 2:
            return 0.30
        returns = bars["close"].pct_change().dropna().tail(lookback)
        if returns.empty:
            return 0.30
        realized = float(returns.std() * math.sqrt(252))
        if math.isnan(realized) or realized <= 0:
            return 0.30
        return max(self.config.min_realized_vol, min(self.config.max_realized_vol, realized))

    def option_greek_reasons(self, greeks: dict[str, float], premium: float, direction: str) -> list[str]:
        reasons = []
        if premium <= 0:
            return ["invalid option premium"]
        delta = float(greeks.get("delta", 0.0) or 0.0)
        theta = float(greeks.get("theta", 0.0) or 0.0)
        abs_delta = abs(delta)
        theta_decay_pct = abs(min(theta, 0.0)) / premium
        delta_theta_score = abs_delta / max(theta_decay_pct, 0.01)
        if direction == "call" and delta <= 0:
            reasons.append(f"call delta {delta:.2f} is not bullish")
        if direction == "put" and delta >= 0:
            reasons.append(f"put delta {delta:.2f} is not bearish")
        if abs_delta < self.config.min_option_abs_delta:
            reasons.append(f"abs delta {abs_delta:.2f} below {self.config.min_option_abs_delta:.2f}")
        if abs_delta > self.config.max_option_abs_delta:
            reasons.append(f"abs delta {abs_delta:.2f} above {self.config.max_option_abs_delta:.2f}")
        if theta_decay_pct > self.config.max_option_theta_decay_pct:
            reasons.append(f"theta decay {theta_decay_pct:.1%}/day above {self.config.max_option_theta_decay_pct:.1%}")
        if delta_theta_score < self.config.min_option_delta_theta_score:
            reasons.append(
                f"delta/theta score {delta_theta_score:.2f} below {self.config.min_option_delta_theta_score:.2f}"
            )
        return reasons

    def volatility_sized_stock_cash(self, ticker: str, price: float) -> float:
        """Cap stock cash so one ATR-sized move is near target_stock_risk_cash."""
        try:
            bars = self.fetch_all_bars().get(ticker)
        except Exception as exc:
            logging.warning("Volatility sizing unavailable for %s: %s", ticker, exc)
            return self.config.max_stock_trade_cash
        if bars is None or bars.empty:
            return self.config.max_stock_trade_cash
        atr = float(bars.iloc[-1].get("atr_14", 0.0))
        if price <= 0 or atr <= 0:
            return self.config.max_stock_trade_cash
        stop_distance = atr * self.config.stop_atr_multiple
        quantity_by_risk = max(1, int(self.config.target_stock_risk_cash / stop_distance))
        return min(self.config.max_stock_trade_cash, quantity_by_risk * price)

    @staticmethod
    def build_option_entry_request(
        symbol: str,
        contracts: int,
        ask: float,
        take_profit_price: float | None = None,
        stop_loss_price: float | None = None,
    ) -> LimitOrderRequest:
        if contracts <= 0:
            raise ValueError("Option entry contracts must be positive.")
        if ask <= 0:
            raise ValueError("Option entry ask must be positive.")
        order_class = None
        take_profit = None
        stop_loss = None
        if take_profit_price and stop_loss_price:
            order_class = OrderClass.BRACKET
            take_profit = TakeProfitRequest(limit_price=round_price(take_profit_price))
            stop_loss = StopLossRequest(stop_price=round_price(stop_loss_price))
        return LimitOrderRequest(
            symbol=symbol,
            qty=int(contracts),
            side=OrderSide.BUY,
            type=OrderType.LIMIT,
            time_in_force=TimeInForce.DAY,
            order_class=order_class,
            take_profit=take_profit,
            stop_loss=stop_loss,
            limit_price=round(ask, 2),
            position_intent=PositionIntent.BUY_TO_OPEN,
        )

    def find_option_contract(self, ticker: str, underlying_price: float, contract_type: ContractType, max_ask: float | None = None):
        today = datetime.now(NY_TZ).date()
        target_dte = (
            self.config.high_price_option_dte
            if underlying_price >= self.config.high_price_option_threshold
            else self.config.low_price_option_dte
        )
        min_dte = self.config.min_option_dte
        max_dte = self.config.max_option_dte
        if underlying_price >= self.config.high_price_option_threshold:
            min_dte = max(min_dte, max(1, target_dte - 1))
            max_dte = min(max_dte, target_dte + 2)
        if contract_type == ContractType.CALL:
            strike_gte = underlying_price * 0.95
            strike_lte = underlying_price * 1.25
        else:
            strike_gte = underlying_price * 0.75
            strike_lte = underlying_price * 1.05
        request = GetOptionContractsRequest(
            underlying_symbols=[ticker],
            status="active",
            type=contract_type,
            expiration_date_gte=today + timedelta(days=min_dte),
            expiration_date_lte=today + timedelta(days=max_dte),
            strike_price_gte=str(round(strike_gte, 2)),
            strike_price_lte=str(round(strike_lte, 2)),
            limit=100,
        )
        try:
            response = self.trading.get_option_contracts(request)
        except Exception as exc:
            logging.warning("Option contract lookup failed for %s: %s", ticker, exc)
            return None
        contracts = getattr(response, "option_contracts", None) or []
        if not contracts:
            return None
        choices = []
        realized_vol = self.realized_volatility(ticker)
        direction = "call" if contract_type == ContractType.CALL else "put"
        for contract in contracts:
            quote = self.get_option_quote(contract.symbol)
            if quote is None:
                continue
            bid, ask = quote
            if ask <= 0:
                continue
            if max_ask is not None and ask > max_ask:
                continue
            spread_pct = (ask - bid) / ask if ask else 1
            if spread_pct > self.config.max_option_spread_pct:
                continue
            strike = float(contract.strike_price)
            dte = (contract.expiration_date - today).days
            model_snapshot = black_scholes_snapshot(underlying_price, strike, max(1, dte), realized_vol, direction)
            greek_reasons = self.option_greek_reasons(model_snapshot, ask, direction)
            if greek_reasons:
                self.state.setdefault("last_option_model_checks", {})[contract.symbol] = {
                    "underlying": ticker,
                    "direction": direction,
                    "ask": ask,
                    "bid": bid,
                    "spread_pct": round(spread_pct, 4),
                    "model_price": round(float(model_snapshot.get("price", 0.0) or 0.0), 4),
                    "realized_vol": round(realized_vol, 4),
                    "dte": dte,
                    "greeks": model_snapshot,
                    "status": "blocked_greeks",
                    "reasons": greek_reasons,
                }
                continue
            dte_penalty = abs(dte - target_dte)
            if contract_type == ContractType.CALL:
                moneyness_penalty = max(0.0, (underlying_price - strike) / underlying_price) + abs(strike / underlying_price - 1.04)
            else:
                moneyness_penalty = max(0.0, (strike - underlying_price) / underlying_price) + abs(strike / underlying_price - 0.96)
            theta_decay_pct = abs(min(float(model_snapshot.get("theta", 0.0) or 0.0), 0.0)) / ask
            delta_theta_score = abs(float(model_snapshot.get("delta", 0.0) or 0.0)) / max(theta_decay_pct, 0.01)
            choices.append((dte_penalty, moneyness_penalty, spread_pct, -delta_theta_score, ask, contract, quote))
        if not choices:
            return None
        choices.sort(key=lambda item: (item[0], item[1], item[2], item[3], item[4]))
        return choices[0][5], choices[0][6]

    def get_option_quote(self, symbol: str) -> tuple[float, float] | None:
        request = OptionLatestQuoteRequest(symbol_or_symbols=symbol, feed=OptionsFeed.INDICATIVE)
        try:
            quotes = self.option_data.get_option_latest_quote(request)
        except Exception as exc:
            logging.warning("Option quote failed for %s: %s", symbol, exc)
            return None
        quote = quotes.get(symbol) if isinstance(quotes, dict) else None
        if quote is None:
            return None
        return float(quote.bid_price or 0), float(quote.ask_price or 0)

    def manage_option_exits(self, today: date) -> None:
        tracked = self.state.setdefault("option_positions", {})
        positions = self.get_option_positions()
        for symbol, position in list(positions.items()):
            entry = tracked.get(symbol)
            if not entry:
                continue
            quote = self.get_option_quote(symbol)
            if quote is None:
                continue
            bid, _ask = quote
            entry_price = float(entry["entry_price"])
            entry_date = datetime.fromisoformat(entry["entry_date"]).date()
            held_days = (today - entry_date).days
            underlying = str(entry.get("underlying", symbol))
            direction = str(entry.get("direction", "unknown"))
            current_underlying_price = self.latest_underlying_close(underlying)
            entry_underlying_price = float(entry.get("underlying_price_at_entry", current_underlying_price or 0.0) or 0.0)
            underlying_return = None
            if current_underlying_price and entry_underlying_price > 0:
                underlying_return = current_underlying_price / entry_underlying_price - 1
            best_bid = max(float(entry.get("best_bid", entry_price) or entry_price), bid)
            entry["best_bid"] = best_bid
            trail_stop = float(entry.get("trailing_stop_price", 0.0) or 0.0)
            if self.config.option_trailing_stop_enabled and entry_price > 0 and bid > 0:
                risk_per_contract = entry_price * self.config.option_stop_loss_pct
                if risk_per_contract > 0:
                    profit_r = max(0.0, (best_bid - entry_price) / risk_per_contract)
                    if profit_r >= self.config.option_trail_start_r:
                        locked_r = math.floor((profit_r - self.config.option_trail_start_r) / self.config.option_trail_step_r)
                        locked_r = max(0, locked_r)
                        candidate_stop = entry_price + (locked_r * risk_per_contract)
                        trail_stop = max(trail_stop, round_price(candidate_stop))
                        entry["trailing_stop_price"] = trail_stop
                        entry["trailing_profit_r"] = round(profit_r, 2)
            reason = None
            if trail_stop > 0 and bid <= trail_stop and best_bid > entry_price:
                reason = f"option trailing stop {trail_stop:.2f}"
            elif bid >= entry_price * (1 + self.config.option_profit_target_pct):
                reason = "option profit target"
            elif bid <= entry_price * (1 - self.config.option_stop_loss_pct):
                reason = "option stop loss"
            elif held_days >= self.config.option_max_hold_days:
                reason = f"option time stop {held_days}d"
            if reason:
                if bid <= 0:
                    logging.warning("Exit signal for %s ignored because bid is %.2f", symbol, bid)
                    continue
                qty = int(float(position.qty))
                entry_price = float(entry["entry_price"])
                pnl = (bid - entry_price) * OPTION_CONTRACT_MULTIPLIER * qty
                order = self.close_option_position(symbol, qty, bid, reason)
                if order is None:
                    continue
                self.record_trade(
                    {
                        "asset_type": "option",
                        "ticker": underlying,
                        "direction": direction,
                        "symbol": symbol,
                        "entry_date": entry_date.isoformat(),
                        "exit_date": today.isoformat(),
                        "entry_price": entry_price,
                        "exit_price": bid,
                        "contracts": qty,
                        "contract_multiplier": OPTION_CONTRACT_MULTIPLIER,
                        "pnl": pnl,
                        "return_pct": pnl / (entry_price * OPTION_CONTRACT_MULTIPLIER * qty) if entry_price > 0 and qty > 0 else 0,
                        "held_days": held_days,
                        "entry_spread_pct": entry.get("entry_spread_pct"),
                        "entry_model_price": entry.get("entry_model_price"),
                        "entry_realized_vol": entry.get("entry_realized_vol"),
                        "entry_greeks": entry.get("entry_greeks"),
                        "dte_at_entry": entry.get("dte_at_entry"),
                        "underlying_entry_price": entry_underlying_price or None,
                        "underlying_exit_price": current_underlying_price,
                        "underlying_return_pct": underlying_return,
                        "setup_features": entry.get("setup_features", {}),
                        "loss_diagnosis": self.option_loss_diagnosis(direction, underlying_return, bid, entry_price),
                        "reason": reason,
                        "exit_order_id": str(order.id),
                    }
                )
                tracked.pop(symbol, None)

    def latest_underlying_close(self, ticker: str) -> float | None:
        try:
            bars = self.fetch_all_bars().get(ticker)
        except Exception:
            return None
        if bars is None or bars.empty:
            return None
        value = bars.iloc[-1]["close"]
        if pd.isna(value):
            return None
        return float(value)

    @staticmethod
    def option_loss_diagnosis(direction: str, underlying_return: float | None, exit_bid: float, entry_price: float) -> str:
        if entry_price <= 0 or exit_bid >= entry_price:
            return "not_loss"
        if underlying_return is None:
            return "unknown_no_underlying_price"
        if direction == "call" and underlying_return < 0:
            return "direction_wrong"
        if direction == "put" and underlying_return > 0:
            return "direction_wrong"
        return "theta_spread_or_vol_decay"

    def close_option_position(self, symbol: str, qty: int, limit_price: float, reason: str, price_buffer_pct: float = 0.0) -> None:
        if qty <= 0 or limit_price <= 0:
            return None
        final_limit = max(0.01, round(limit_price * (1 - max(0.0, price_buffer_pct)), 2))
        request = self.build_option_exit_request(symbol, qty, final_limit)
        order = self.trading.submit_order(request)
        logging.info("SELL_TO_CLOSE %s contracts=%s limit=%.2f id=%s reason=%s", symbol, qty, final_limit, order.id, reason)
        return order

    @staticmethod
    def build_option_exit_request(symbol: str, contracts: int, bid: float) -> LimitOrderRequest:
        if contracts <= 0:
            raise ValueError("Option exit contracts must be positive.")
        if bid <= 0:
            raise ValueError("Option exit bid must be positive.")
        return LimitOrderRequest(
            symbol=symbol,
            qty=int(contracts),
            side=OrderSide.SELL,
            type=OrderType.LIMIT,
            time_in_force=TimeInForce.DAY,
            limit_price=round(bid, 2),
            position_intent=PositionIntent.SELL_TO_CLOSE,
        )

    def submit_market_order(
        self,
        ticker: str,
        quantity: int,
        reason: str,
        take_profit_price: float | None = None,
        stop_loss_price: float | None = None,
    ):
        side = OrderSide.BUY if quantity > 0 else OrderSide.SELL
        order_class = None
        take_profit = None
        stop_loss = None
        if side == OrderSide.BUY and take_profit_price and stop_loss_price:
            order_class = OrderClass.BRACKET
            take_profit = TakeProfitRequest(limit_price=round_price(take_profit_price))
            stop_loss = StopLossRequest(stop_price=round_price(stop_loss_price))
        request = MarketOrderRequest(
            symbol=ticker,
            qty=abs(quantity),
            side=side,
            time_in_force=TimeInForce.DAY,
            order_class=order_class,
            take_profit=take_profit,
            stop_loss=stop_loss,
        )
        order = self.trading.submit_order(request)
        logging.info("%s %s qty=%s id=%s reason=%s", side.value.upper(), ticker, abs(quantity), order.id, reason)
        return order


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Alpaca paper trading bot.")
    parser.add_argument("--once", action="store_true", help="Run one scan/trading pass and exit.")
    parser.add_argument("--loop", action="store_true", help="Keep running scans during market hours.")
    parser.add_argument("--interval-minutes", type=float, default=20.0, help="Minutes between scans in loop mode.")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    if not args.loop:
        AlpacaStockBot(StrategyConfig()).run_once()
        return

    interval_seconds = max(60, int(args.interval_minutes * 60))
    logging.info("Starting automated loop. Interval: %.1f minute(s). Press Ctrl+C to stop.", interval_seconds / 60)
    while True:
        try:
            bot = AlpacaStockBot(StrategyConfig())
            clock = bot.trading.get_clock()
            if clock.is_open:
                bot.run_once()
                sleep_seconds = interval_seconds
            else:
                next_open = clock.next_open
                if next_open.tzinfo is None:
                    next_open = next_open.replace(tzinfo=timezone.utc)
                seconds_until_open = max(60, int((next_open - datetime.now(timezone.utc)).total_seconds()))
                sleep_seconds = min(seconds_until_open, interval_seconds)
                logging.info("Market closed. Next open: %s. Checking again in %.1f minute(s).", clock.next_open, sleep_seconds / 60)
        except KeyboardInterrupt:
            logging.info("Stopping automated loop.")
            break
        except Exception:
            logging.exception("Automated loop pass failed; will retry after interval.")
            sleep_seconds = interval_seconds

        time.sleep(sleep_seconds)


if __name__ == "__main__":
    main()
