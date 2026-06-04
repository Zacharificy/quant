import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import MarketOrderRequest
from dotenv import load_dotenv


NY_TZ = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class StrategyConfig:
    tickers: tuple[str, ...] = (
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
    max_positions: int = 2
    position_pct: float = 0.45
    min_cash_buffer: float = 25.0
    breakout_lookback_days: int = 20
    cooldown_days: int = 7
    stop_atr_multiple: float = 2.5
    take_profit_atr_multiple: float = 4.0
    max_hold_days: int = 25
    min_score: float = 0.68
    history_days: int = 280


def load_state(path: Path) -> dict:
    if not path.exists():
        return {"positions": {}, "last_exit_dates": {}}
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as file:
        json.dump(state, file, indent=2, sort_keys=True)
    tmp_path.replace(path)


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


class AlpacaStockBot:
    def __init__(self, config: StrategyConfig):
        load_dotenv()
        self.config = config
        self.state_path = Path(os.getenv("BOT_STATE_PATH", "alpaca_stock_bot_state.json"))
        self.state = load_state(self.state_path)

        api_key = os.getenv("ALPACA_PAPER_API_KEY")
        secret_key = os.getenv("ALPACA_PAPER_SECRET_KEY")
        paper = os.getenv("ALPACA_PAPER", "true").lower() == "true"
        if not api_key or not secret_key:
            raise RuntimeError("Missing ALPACA_PAPER_API_KEY or ALPACA_PAPER_SECRET_KEY in .env")
        if not paper:
            raise RuntimeError("This script is locked to paper mode. Set ALPACA_PAPER=true.")

        self.trading = TradingClient(api_key, secret_key, paper=True)
        self.data = StockHistoricalDataClient(api_key, secret_key)

    def run_once(self) -> None:
        clock = self.trading.get_clock()
        if not clock.is_open:
            logging.info("Market is closed. Next open: %s", clock.next_open)
            return

        today = datetime.now(NY_TZ).date()
        bars = self.fetch_all_bars()
        positions = self.get_positions()
        self.sync_state_with_positions(positions)
        self.manage_exits(today, bars, positions)

        positions = self.get_positions()
        if len(positions) >= self.config.max_positions:
            logging.info("Max positions already open: %d", len(positions))
            save_state(self.state_path, self.state)
            return

        candidate = self.find_best_stock(today, bars, positions)
        if candidate is None:
            logging.info("No stock passed the scanner today.")
            save_state(self.state_path, self.state)
            return

        ticker, score, price = candidate
        self.enter_position(ticker, score, price)
        save_state(self.state_path, self.state)

    def fetch_all_bars(self) -> dict[str, pd.DataFrame]:
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=self.config.history_days)
        request = StockBarsRequest(
            symbol_or_symbols=list(self.config.tickers),
            timeframe=TimeFrame.Day,
            start=start,
            end=end,
        )
        raw = self.data.get_stock_bars(request).df
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

    def add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df["ema_50"] = df["close"].ewm(span=50, adjust=False).mean()
        df["ema_200"] = df["close"].ewm(span=200, adjust=False).mean()
        df["rsi_14"] = compute_rsi(df["close"], 14)
        df["atr_14"] = compute_atr(df, 14)
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
                    self.submit_market_order(ticker, -qty, reason)
                    tracked.pop(ticker, None)
                    self.state.setdefault("last_exit_dates", {})[ticker] = today.isoformat()

    def find_best_stock(self, today, bars: dict[str, pd.DataFrame], positions: dict[str, object]):
        best = None
        for ticker, df in bars.items():
            if ticker in positions:
                continue
            if self.in_cooldown(ticker, today):
                continue
            score = self.score_stock(ticker, df)
            if score < self.config.min_score:
                continue
            price = float(df.iloc[-1]["close"])
            if best is None or score > best[1]:
                best = (ticker, score, price)
        return best

    def score_stock(self, ticker: str, df: pd.DataFrame) -> float:
        lookback = self.config.breakout_lookback_days
        if len(df) < 220 or len(df) < lookback + 1:
            return 0

        latest = df.iloc[-1]
        price = float(latest["close"])
        fast = float(latest["ema_50"])
        slow = float(latest["ema_200"])
        rsi = float(latest["rsi_14"])
        atr = float(latest["atr_14"])
        prior_high = float(df["high"].iloc[-lookback - 1 : -1].max())

        if price <= 0 or slow <= 0 or atr <= 0 or prior_high <= 0:
            return 0
        if price <= slow or fast <= slow:
            return 0
        if rsi < 50 or rsi > 72:
            return 0
        if price <= prior_high:
            return 0

        trend_score = min((fast / slow - 1) / 0.08, 1)
        rsi_score = 1 - min(abs(rsi - 60) / 22, 1)
        atr_score = 1 - min((atr / price) / 0.08, 1)
        breakout_score = min((price / prior_high - 1) / 0.03, 1)
        return (trend_score * 0.30) + (rsi_score * 0.25) + (atr_score * 0.20) + (breakout_score * 0.25)

    def in_cooldown(self, ticker: str, today) -> bool:
        raw = self.state.get("last_exit_dates", {}).get(ticker)
        if raw is None:
            return False
        last_exit = datetime.fromisoformat(raw).date()
        return (today - last_exit).days < self.config.cooldown_days

    def enter_position(self, ticker: str, score: float, price: float) -> None:
        account = self.trading.get_account()
        buying_power = float(account.buying_power)
        cash = float(account.cash)
        target_cash = float(account.portfolio_value) * self.config.position_pct
        available_cash = max(0, min(cash, buying_power) - self.config.min_cash_buffer)
        order_cash = min(target_cash, available_cash)
        quantity = int(order_cash / price)

        if quantity <= 0:
            logging.info("Skip %s: price %.2f is too high for available cash %.2f", ticker, price, available_cash)
            return

        self.submit_market_order(ticker, quantity, f"stock breakout score={score:.2f}")
        self.state.setdefault("positions", {})[ticker] = {
            "entry_price": price,
            "entry_date": datetime.now(NY_TZ).date().isoformat(),
        }

    def submit_market_order(self, ticker: str, quantity: int, reason: str) -> None:
        side = OrderSide.BUY if quantity > 0 else OrderSide.SELL
        request = MarketOrderRequest(
            symbol=ticker,
            qty=abs(quantity),
            side=side,
            time_in_force=TimeInForce.DAY,
        )
        order = self.trading.submit_order(request)
        logging.info("%s %s qty=%s id=%s reason=%s", side.value.upper(), ticker, abs(quantity), order.id, reason)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    bot = AlpacaStockBot(StrategyConfig())
    bot.run_once()


if __name__ == "__main__":
    main()
