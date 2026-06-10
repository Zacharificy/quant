import json
import logging
import os
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from alpaca_stock_bot import AlpacaStockBot, NY_TZ, StrategyConfig, read_watchlist, save_watchlist


FOCUS_TICKERS = tuple(
    ticker.strip().upper()
    for ticker in os.getenv("BOT_RESEARCH_FOCUS_TICKERS", "F,AMC,SPY").split(",")
    if ticker.strip()
)


def research_path() -> Path:
    return Path(os.getenv("BOT_TICKER_RESEARCH_PATH", "ticker_research.json"))


def ensure_focus_tickers() -> list[str]:
    tickers = read_watchlist()
    changed = False
    for ticker in FOCUS_TICKERS:
        if ticker not in tickers:
            tickers.append(ticker)
            changed = True
    if changed:
        save_watchlist(None, tickers)
    return tickers


def run_pretrade_research() -> dict:
    tickers = ensure_focus_tickers()
    config = replace(StrategyConfig(), tickers=tuple(tickers))
    bot = AlpacaStockBot(config)
    today = datetime.now(NY_TZ).date()
    bars = bot.fetch_all_bars()
    news = bot.fetch_recent_news()
    positions = bot.get_positions()
    bot.sync_state_with_positions(positions)
    candidate = bot.find_best_option_trade(today, bars, positions, news)
    scan = bot.state.get("last_option_scan") or {}

    candidates = sorted(
        (
            (ticker, data)
            for ticker, data in (scan.get("candidates") or {}).items()
            if data.get("status") in {"passed", "watchlist"}
        ),
        key=lambda item: float(item[1].get("score", 0.0)),
        reverse=True,
    )
    candidate_tickers = [ticker for ticker, _data in candidates[:5]]
    research_tickers = []
    for ticker in list(FOCUS_TICKERS) + candidate_tickers:
        if ticker not in research_tickers:
            research_tickers.append(ticker)

    reports = {}
    for ticker in research_tickers:
        reports[ticker] = research_ticker(bot, ticker, bars, news)

    payload = {
        "created_at": datetime.now(NY_TZ).isoformat(timespec="seconds"),
        "focus_tickers": list(FOCUS_TICKERS),
        "candidate": {
            "ticker": candidate[0],
            "score": round(float(candidate[1]), 3),
            "direction": candidate[3],
        }
        if candidate
        else None,
        "researched_tickers": research_tickers,
        "reports": reports,
    }

    path = research_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2, sort_keys=True)

    logging.info("Wrote pretrade ticker research to %s", path)
    return payload


def research_ticker(bot: AlpacaStockBot, ticker: str, bars: dict, news: dict) -> dict:
    df = bars.get(ticker)
    if df is None or df.empty:
        return {
            "status": "unavailable",
            "recommendation": "avoid",
            "reasons": ["no price history returned"],
        }

    direction, score, score_reasons = bot.score_directional_trade(ticker, df)
    latest = df.iloc[-1]
    price = float(latest["close"])
    rsi = float(latest.get("rsi_14", 0.0) or 0.0)
    atr = float(latest.get("atr_14", 0.0) or 0.0)
    risk_reasons = bot.ticker_risk_reasons(ticker, df, news.get(ticker, []))
    recent_news = summarize_news_items(news.get(ticker, []))

    if risk_reasons:
        recommendation = "avoid"
    elif direction == "call" and score >= bot.config.min_activity_option_score:
        recommendation = "prefer_call"
    elif direction == "put" and score >= bot.config.min_activity_option_score:
        recommendation = "prefer_put"
    else:
        recommendation = "watch"

    reasons = []
    if score_reasons:
        reasons.extend(score_reasons[:3])
    if risk_reasons:
        reasons.extend(risk_reasons[:3])
    if not reasons:
        reasons.append(f"{direction or 'no direction'} setup score {score:.2f}")

    return {
        "status": "ok",
        "recommendation": recommendation,
        "preferred_direction": direction,
        "score": round(float(score), 3),
        "price": round(price, 2),
        "rsi_14": round(rsi, 2),
        "atr_pct": round((atr / price) if price > 0 else 0.0, 4),
        "reasons": reasons,
        "news": recent_news,
    }


def summarize_news_items(items: list[dict]) -> list[dict]:
    summaries = []
    for item in items[:5]:
        headline = str(item.get("headline", "")).strip()
        body = str(item.get("summary") or item.get("content") or "").strip()
        if not headline and not body:
            continue
        summaries.append(
            {
                "headline": headline[:180],
                "summary": body[:260],
                "source": str(item.get("source") or item.get("source_domain") or "")[:120],
                "url": str(item.get("url") or "")[:240],
            }
        )
    return summaries


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    print(json.dumps(run_pretrade_research(), indent=2))


if __name__ == "__main__":
    main()
