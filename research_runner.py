import csv
import itertools
import json
import logging
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

from alpaca_stock_bot import AlpacaStockBot, StrategyConfig, NY_TZ


RESULTS_DIR = Path("research_results")
RESULTS_DIR.mkdir(exist_ok=True)


PARAMETER_GRID = {
    "breakout_lookback_days": [5, 10, 20],
    "min_score": [0.50, 0.58, 0.66],
    "min_cross_sectional_score": [0.48, 0.52, 0.58],
    "stop_atr_multiple": [2.0, 2.5, 3.0],
    "take_profit_atr_multiple": [3.0, 4.0],
    "max_hold_days": [15, 25, 35],
    "target_stock_risk_cash": [25.0, 35.0, 50.0],
}


def fetch_research_bars(config: StrategyConfig) -> dict[str, pd.DataFrame]:
    bot = AlpacaStockBot(config)
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=max(config.history_days, 900))
    request = StockBarsRequest(
        symbol_or_symbols=list(config.tickers),
        timeframe=TimeFrame.Day,
        start=start,
        end=end,
        feed=bot.data_feed,
    )
    raw = bot.data.get_stock_bars(request).df
    bars = {}
    for ticker in config.tickers:
        try:
            df = raw.loc[ticker].copy().sort_index()
        except KeyError:
            logging.warning("No research bars returned for %s", ticker)
            continue
        bars[ticker] = bot.add_indicators(df)
    return bars


def score_stock(config: StrategyConfig, df: pd.DataFrame, index: int) -> tuple[float, float]:
    lookback = config.breakout_lookback_days
    if index < 220 or index < lookback + 1:
        return 0.0, 0.0

    window = df.iloc[: index + 1]
    latest = window.iloc[-1]
    raw_values = (
        latest["close"],
        latest["ema_50"],
        latest["ema_200"],
        latest["rsi_14"],
        latest["atr_14"],
        window["high"].iloc[-lookback - 1 : -1].max(),
    )
    if any(pd.isna(value) for value in raw_values):
        return 0.0, 0.0
    price, fast, slow, rsi, atr, prior_high = (float(value) for value in raw_values)

    if price <= 0 or slow <= 0 or atr <= 0 or prior_high <= 0:
        return 0.0, 0.0
    if price <= slow or fast <= slow:
        return 0.0, 0.0
    if rsi < 50 or rsi > 72:
        return 0.0, 0.0
    if price <= prior_high:
        return 0.0, 0.0

    trend_score = min((fast / slow - 1) / 0.08, 1)
    rsi_score = 1 - min(abs(rsi - 60) / 22, 1)
    atr_score = 1 - min((atr / price) / 0.08, 1)
    breakout_score = min((price / prior_high - 1) / 0.03, 1)
    signal_score = (trend_score * 0.30) + (rsi_score * 0.25) + (atr_score * 0.20) + (breakout_score * 0.25)
    rank_score = cross_sectional_score(config, signal_score, df, index)
    return signal_score, rank_score


def cross_sectional_score(config: StrategyConfig, signal_score: float, df: pd.DataFrame, index: int) -> float:
    if index < 130:
        return signal_score
    latest = df.iloc[index]
    price = float(latest["close"])
    atr = float(latest["atr_14"])
    close_3m = float(df["close"].iloc[index - 63])
    close_6m = float(df["close"].iloc[index - 126])
    if price <= 0 or atr <= 0 or close_3m <= 0 or close_6m <= 0:
        return signal_score
    momentum_3m = price / close_3m - 1
    momentum_6m = price / close_6m - 1
    momentum_score = max(0.0, min(((momentum_3m * 0.55) + (momentum_6m * 0.45)) / 0.35, 1.0))
    volatility_score = 1 - min((atr / price) / config.max_atr_pct, 1)
    return max(0.0, min((signal_score * 0.60) + (momentum_score * 0.25) + (volatility_score * 0.15), 1.0))


def bucket_for(ticker: str) -> str:
    return AlpacaStockBot.ticker_bucket(ticker)


def bucket_counts(positions: dict) -> dict[str, int]:
    counts = {}
    for ticker in positions:
        bucket = bucket_for(ticker)
        counts[bucket] = counts.get(bucket, 0) + 1
    return counts


def volatility_sized_cash(config: StrategyConfig, df: pd.DataFrame, index: int, price: float) -> float:
    atr = float(df.iloc[index]["atr_14"])
    if price <= 0 or atr <= 0:
        return config.max_stock_trade_cash
    stop_distance = atr * config.stop_atr_multiple
    qty = max(1, int(config.target_stock_risk_cash / stop_distance))
    return min(config.max_stock_trade_cash, qty * price)


def market_clear(config: StrategyConfig, bars: dict[str, pd.DataFrame], index_by_ticker: dict[str, int]) -> bool:
    score = 0
    for ticker in ("SPY", "QQQ", "DIA"):
        df = bars.get(ticker)
        index = index_by_ticker.get(ticker)
        if df is None or index is None or index < 220:
            continue
        latest = df.iloc[index]
        price = float(latest["close"])
        fast = float(latest["ema_50"])
        slow = float(latest["ema_200"])
        rsi = float(latest["rsi_14"])
        if price > slow and fast > slow and rsi >= 45:
            score += 1
    return score >= config.min_market_score


def simulate(config: StrategyConfig, bars: dict[str, pd.DataFrame]) -> dict:
    cash = 1000.0
    equity_curve = []
    positions = {}
    last_exit_dates = {}
    trades = []

    dates = sorted(set().union(*[set(df.index.date) for df in bars.values()]))
    for current_date in dates:
        index_by_ticker = {}
        for ticker, df in bars.items():
            matches = [i for i, idx in enumerate(df.index) if idx.date() == current_date]
            if matches:
                index_by_ticker[ticker] = matches[-1]

        portfolio_value = cash
        for ticker, position in positions.items():
            df = bars[ticker]
            index = index_by_ticker.get(ticker)
            if index is not None:
                portfolio_value += position["qty"] * float(df.iloc[index]["close"])
            else:
                portfolio_value += position["qty"] * position["last_price"]
        equity_curve.append({"date": current_date.isoformat(), "equity": portfolio_value})

        for ticker in list(positions):
            df = bars[ticker]
            index = index_by_ticker.get(ticker)
            if index is None:
                continue
            latest = df.iloc[index]
            price = float(latest["close"])
            atr = float(latest["atr_14"])
            fast = float(latest["ema_50"])
            slow = float(latest["ema_200"])
            position = positions[ticker]
            position["last_price"] = price
            held_days = (current_date - position["entry_date"]).days

            reason = None
            if atr > 0 and price <= position["entry_price"] - config.stop_atr_multiple * atr:
                reason = "ATR stop"
            elif atr > 0 and price >= position["entry_price"] + config.take_profit_atr_multiple * atr:
                reason = "ATR target"
            elif held_days >= config.max_hold_days:
                reason = f"time stop {held_days}d"
            elif fast < slow:
                reason = "trend failed"

            if reason:
                cash += position["qty"] * price
                pnl = (price - position["entry_price"]) * position["qty"]
                trades.append(
                    {
                        "ticker": ticker,
                        "entry_date": position["entry_date"].isoformat(),
                        "exit_date": current_date.isoformat(),
                        "entry_price": position["entry_price"],
                        "exit_price": price,
                        "qty": position["qty"],
                        "pnl": pnl,
                        "reason": reason,
                    }
                )
                last_exit_dates[ticker] = current_date
                positions.pop(ticker)

        if len(positions) >= config.max_positions:
            continue
        if not market_clear(config, bars, index_by_ticker):
            continue

        candidates = []
        current_buckets = bucket_counts(positions)
        for ticker, df in bars.items():
            if ticker in positions or ticker not in index_by_ticker:
                continue
            if current_buckets.get(bucket_for(ticker), 0) >= config.max_positions_per_bucket:
                continue
            last_exit = last_exit_dates.get(ticker)
            if last_exit and (current_date - last_exit).days < config.cooldown_days:
                continue
            index = index_by_ticker[ticker]
            signal_score, rank_score = score_stock(config, df, index)
            if signal_score < config.min_score or rank_score < config.min_cross_sectional_score:
                continue
            price = float(df.iloc[index]["close"])
            if price <= 0:
                continue
            candidates.append({"ticker": ticker, "score": rank_score, "signal_score": signal_score, "price": price, "index": index})

        candidates.sort(key=lambda row: row["score"], reverse=True)
        best = candidates[0] if candidates else None
        if best:
            portfolio_value = equity_curve[-1]["equity"]
            available_cash = max(0.0, cash - config.min_cash_buffer)
            vol_cash = volatility_sized_cash(config, bars[best["ticker"]], best["index"], best["price"])
            order_cash = min(portfolio_value * config.position_pct, available_cash, vol_cash, config.max_stock_trade_cash)
            qty = int(order_cash / best["price"])
            if qty > 0:
                cash -= qty * best["price"]
                positions[best["ticker"]] = {
                    "qty": qty,
                    "entry_price": best["price"],
                    "entry_date": current_date,
                    "last_price": best["price"],
                    "score": best["score"],
                }

    final_equity = equity_curve[-1]["equity"] if equity_curve else 1000.0
    peak = 1000.0
    max_drawdown = 0.0
    for point in equity_curve:
        equity = point["equity"]
        peak = max(peak, equity)
        drawdown = 0 if peak <= 0 else (peak - equity) / peak
        max_drawdown = max(max_drawdown, drawdown)

    wins = [trade for trade in trades if trade["pnl"] > 0]
    losses = [trade for trade in trades if trade["pnl"] <= 0]
    gross_profit = sum(trade["pnl"] for trade in wins)
    gross_loss = abs(sum(trade["pnl"] for trade in losses))
    profit_factor = gross_profit / gross_loss if gross_loss else (999.0 if gross_profit > 0 else 0.0)
    buy_hold_return = benchmark_return(bars)

    return {
        "return_pct": (final_equity / 1000.0 - 1) * 100,
        "final_equity": final_equity,
        "max_drawdown_pct": max_drawdown * 100,
        "trade_count": len(trades),
        "win_rate_pct": (len(wins) / len(trades) * 100) if trades else 0.0,
        "profit_factor": profit_factor,
        "benchmark_return_pct": buy_hold_return,
        "beats_benchmark": ((final_equity / 1000.0 - 1) * 100) > buy_hold_return,
    }


def benchmark_return(bars: dict[str, pd.DataFrame]) -> float:
    df = bars.get("SPY")
    if df is None:
        df = bars.get("QQQ")
    if df is None or len(df) < 2:
        return 0.0
    first = float(df["close"].iloc[0])
    last = float(df["close"].iloc[-1])
    if first <= 0:
        return 0.0
    return (last / first - 1) * 100


def parameter_sets():
    keys = list(PARAMETER_GRID)
    for values in itertools.product(*[PARAMETER_GRID[key] for key in keys]):
        yield dict(zip(keys, values))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    base = StrategyConfig(history_days=900)
    bars = fetch_research_bars(base)
    results = []

    for number, params in enumerate(parameter_sets(), start=1):
        config = replace(base, **params)
        metrics = simulate(config, bars)
        result = {**params, **metrics}
        result["experiment"] = number
        results.append(result)
        logging.info(
            "experiment=%s return=%.2f%% dd=%.2f%% trades=%s",
            number,
            metrics["return_pct"],
            metrics["max_drawdown_pct"],
            metrics["trade_count"],
        )

    results.sort(
        key=lambda row: (
            row["beats_benchmark"],
            row["return_pct"],
            row["profit_factor"],
            -row["max_drawdown_pct"],
            row["trade_count"],
        ),
        reverse=True,
    )
    timestamp = datetime.now(NY_TZ).strftime("%Y%m%d_%H%M%S")
    csv_path = RESULTS_DIR / f"leaderboard_{timestamp}.csv"
    json_path = RESULTS_DIR / f"best_{timestamp}.json"

    with csv_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(results[0]))
        writer.writeheader()
        writer.writerows(results)

    with json_path.open("w", encoding="utf-8") as file:
        json.dump({"base_config": asdict(base), "best": results[:10]}, file, indent=2)

    print(f"Wrote {csv_path}")
    print(f"Wrote {json_path}")
    print(json.dumps(results[:5], indent=2))


if __name__ == "__main__":
    main()
