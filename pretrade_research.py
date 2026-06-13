import json
import logging
import os
import re
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from alpaca_stock_bot import AlpacaStockBot, NY_TZ, StrategyConfig, read_watchlist, save_watchlist


FOCUS_TICKERS = tuple(
    ticker.strip().upper()
    for ticker in os.getenv("BOT_RESEARCH_FOCUS_TICKERS", "F,AMC,SPY,TSLA,NVDA,AMD,QQQ").split(",")
    if ticker.strip()
)
BROAD_RESEARCH_SEED_TICKERS = (
    "SPY",
    "QQQ",
    "IWM",
    "DIA",
    "AAPL",
    "MSFT",
    "NVDA",
    "AMD",
    "AVGO",
    "TSLA",
    "PLTR",
    "SOFI",
    "F",
    "AMC",
    "SNOW",
    "HPE",
    "NOK",
    "SPCE",
    "APLD",
    "MU",
    "MRVL",
    "SMCI",
    "MARA",
    "IREN",
)


def env_int(name: str, default: int, min_value: int = 1, max_value: int = 100) -> int:
    try:
        value = int(float(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        value = default
    return max(min_value, min(max_value, value))


RESEARCH_MAX_TICKERS = env_int("BOT_RESEARCH_MAX_TICKERS", 28, min_value=5, max_value=60)
RESEARCH_SCAN_CANDIDATES = env_int("BOT_RESEARCH_SCAN_CANDIDATES", 16, min_value=3, max_value=40)


def research_path() -> Path:
    return Path(os.getenv("BOT_TICKER_RESEARCH_PATH", "ticker_research.json"))


def ensure_focus_tickers() -> list[str]:
    tickers = read_watchlist()
    changed = False
    for ticker in list(FOCUS_TICKERS) + list(BROAD_RESEARCH_SEED_TICKERS):
        if ticker not in tickers:
            tickers.append(ticker)
            changed = True
    if changed:
        save_watchlist(None, tickers)
    return tickers


def run_pretrade_research() -> dict:
    tickers = ensure_focus_tickers()
    add_research_focus_to_extra_tickers(tickers)
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
    candidate_tickers = [ticker for ticker, _data in candidates[:RESEARCH_SCAN_CANDIDATES]]
    research_tickers = []
    research_priority = (
        candidate_tickers
        + list(FOCUS_TICKERS)
        + list(BROAD_RESEARCH_SEED_TICKERS)
        + list(tickers)
    )
    for ticker in research_priority:
        if ticker not in research_tickers and len(research_tickers) < RESEARCH_MAX_TICKERS:
            research_tickers.append(ticker)

    reports = {}
    for ticker in research_tickers:
        reports[ticker] = research_ticker(bot, ticker, bars, news)

    market_catalysts = build_market_catalysts(reports)
    swing_plan = build_swing_plan(reports)

    payload = {
        "created_at": datetime.now(NY_TZ).isoformat(timespec="seconds"),
        "research_mode": "broad_watchlist_plus_scan",
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
        "market_catalysts": market_catalysts,
        "swing_plan": swing_plan,
    }

    path = research_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2, sort_keys=True)

    logging.info("Wrote pretrade ticker research to %s", path)
    return payload


def add_research_focus_to_extra_tickers(watchlist_tickers: list[str] | None = None) -> None:
    existing = [
        ticker.strip().upper()
        for ticker in os.getenv("BOT_EXTRA_TICKERS", "").split(",")
        if ticker.strip()
    ]
    merged = []
    watchlist_tickers = [str(ticker).strip().upper() for ticker in (watchlist_tickers or []) if str(ticker).strip()]
    for ticker in existing + list(FOCUS_TICKERS) + list(BROAD_RESEARCH_SEED_TICKERS) + watchlist_tickers:
        if ticker not in merged:
            merged.append(ticker)
    os.environ["BOT_EXTRA_TICKERS"] = ",".join(merged)


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
    macro_items = macro_news_for_ticker(news, ticker)
    catalyst = score_news_catalysts(bot, ticker, direction, recent_news, macro_items)
    earnings = earnings_context(news.get(ticker, []))
    swing_score = max(0.0, min(1.0, float(score) + catalyst["score_boost"] + earnings["score_boost"]))

    if risk_reasons:
        recommendation = "avoid"
    elif direction == "call" and swing_score >= bot.config.min_activity_option_score:
        recommendation = "prefer_call"
    elif direction == "put" and swing_score >= bot.config.min_activity_option_score:
        recommendation = "prefer_put"
    else:
        recommendation = "watch"

    reasons = []
    if score_reasons:
        reasons.extend(score_reasons[:3])
    if risk_reasons:
        reasons.extend(risk_reasons[:3])
    if catalyst["reasons"]:
        reasons.extend(catalyst["reasons"][:3])
    if earnings["reasons"]:
        reasons.extend(earnings["reasons"][:2])
    if not reasons:
        reasons.append(f"{direction or 'no direction'} setup score {swing_score:.2f}")

    return {
        "status": "ok",
        "recommendation": recommendation,
        "preferred_direction": direction,
        "score": round(float(score), 3),
        "swing_score": round(float(swing_score), 3),
        "price": round(price, 2),
        "rsi_14": round(rsi, 2),
        "atr_pct": round((atr / price) if price > 0 else 0.0, 4),
        "reasons": reasons,
        "catalysts": catalyst["items"],
        "earnings": earnings,
        "news": recent_news,
    }


def macro_news_for_ticker(news: dict, ticker: str) -> list[dict]:
    macro_sources = []
    for index_ticker in ("SPY", "QQQ", "DIA", "IWM"):
        for item in news.get(index_ticker, [])[:30]:
            if item.get("source_type") == "external_macro":
                macro_sources.append(item)
    if ticker in {"SPY", "QQQ", "DIA", "IWM"}:
        return macro_sources
    text_filters = {
        "F": ("ford", "auto", "autos", "tariff", "ev", "china"),
        "TSLA": ("tesla", "musk", "ev", "tariff", "china", "robotaxi"),
        "AAPL": ("apple", "iphone", "china", "tariff", "imports"),
        "NVDA": ("nvidia", "chip", "ai", "semiconductor", "export controls"),
        "AMD": ("amd", "chip", "ai", "semiconductor", "export controls"),
        "AVGO": ("broadcom", "chip", "ai", "semiconductor"),
        "MSFT": ("microsoft", "ai", "cloud", "data center"),
        "AMC": ("amc", "movie", "consumer", "meme"),
        "SPCE": ("space", "launch", "spacex", "defense"),
        "MARA": ("bitcoin", "crypto", "tariff", "rates"),
        "IREN": ("bitcoin", "crypto", "ai data center", "rates"),
    }
    terms = text_filters.get(ticker, (ticker.lower(),))
    return [item for item in macro_sources if any(term in news_blob(item).lower() for term in terms)]


def score_news_catalysts(bot: AlpacaStockBot, ticker: str, direction: str | None, ticker_news: list[dict], macro_news: list[dict]) -> dict:
    reasons = []
    items = []
    boost = 0.0
    for item in (ticker_news + summarize_news_items(macro_news))[:10]:
        text = f"{item.get('headline', '')} {item.get('summary', '')}"
        analysis = bot.analyze_market_news_impact(text)
        deal = detect_deal_catalyst(text)
        if analysis:
            impacted = ticker in set(analysis.get("tickers") or []) or ticker in {"SPY", "QQQ", "DIA", "IWM"}
            aligns = (direction == "call" and analysis.get("direction") == "up") or (
                direction == "put" and analysis.get("direction") == "down"
            )
            if impacted:
                confidence = float(analysis.get("confidence", 0.0) or 0.0)
                if aligns:
                    boost += min(0.10, confidence * 0.08)
                    reasons.append(
                        f"trusted market catalyst aligns {analysis.get('direction')}: "
                        f"{analysis.get('event', 'market_news')} ({confidence:.0%} confidence)"
                    )
                else:
                    boost -= min(0.08, confidence * 0.06)
                    reasons.append(
                        f"trusted market catalyst conflicts {analysis.get('direction')}: "
                        f"{analysis.get('event', 'market_news')} ({confidence:.0%} confidence)"
                    )
                items.append(
                    {
                        "type": analysis.get("event", "market_news"),
                        "direction": analysis.get("direction", "watch"),
                        "confidence": analysis.get("confidence", 0.0),
                        "headline": item.get("headline", "")[:180],
                        "summary": item.get("summary", "")[:260],
                        "key": catalyst_key(text),
                        "correlation": catalyst_correlation(ticker, analysis),
                    }
                )
        if deal:
            aligns = direction == "call" and deal["direction"] == "up"
            if aligns:
                boost += deal["boost"]
            elif direction == "put" and deal["direction"] == "up":
                boost -= min(0.05, deal["boost"])
            reasons.append(f"deal or policy catalyst {deal['direction']}: {ticker} has related exposure")
            items.append(
                {
                    "type": "deal",
                    "direction": deal["direction"],
                    "confidence": deal["confidence"],
                    "headline": item.get("headline", "")[:180],
                    "summary": item.get("summary", "")[:260],
                    "key": catalyst_key(text),
                    "correlation": f"{ticker} has policy/deal sensitivity in this setup.",
                }
            )
    return {"score_boost": max(-0.12, min(0.18, boost)), "reasons": dedupe(reasons), "items": items[:5]}


def catalyst_correlation(ticker: str, analysis: dict) -> str:
    event = str(analysis.get("event") or "market news").replace("_", " ")
    direction = str(analysis.get("direction") or "watch")
    affected = set(analysis.get("tickers") or [])
    if ticker in affected:
        return f"{ticker} is directly listed in the {event} impact map."
    if ticker in {"SPY", "QQQ", "DIA", "IWM"}:
        return f"{ticker} is a broad-market ETF, so the {direction} macro catalyst can move index risk appetite."
    return f"{ticker} is being treated as correlated through broad-market risk appetite, not as a direct headline target."


def catalyst_key(text: str) -> str:
    clean = re.sub(r"[^a-z0-9 ]+", " ", str(text or "").lower())
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean[:220]


def build_market_catalysts(reports: dict) -> list[dict]:
    grouped = {}
    for ticker, report in reports.items():
        if not isinstance(report, dict):
            continue
        for item in report.get("catalysts") or []:
            key = str(item.get("key") or catalyst_key(f"{item.get('headline', '')} {item.get('summary', '')}"))
            if not key:
                continue
            group = grouped.setdefault(
                key,
                {
                    "key": key,
                    "type": item.get("type", "market_news"),
                    "direction": item.get("direction", "watch"),
                    "confidence": float(item.get("confidence", 0.0) or 0.0),
                    "headline": str(item.get("headline") or "")[:220],
                    "summary": str(item.get("summary") or "")[:320],
                    "tickers": [],
                    "correlations": [],
                },
            )
            if ticker not in group["tickers"]:
                group["tickers"].append(ticker)
            correlation = str(item.get("correlation") or "").strip()
            if correlation and correlation not in group["correlations"]:
                group["correlations"].append(correlation)
            group["confidence"] = max(group["confidence"], float(item.get("confidence", 0.0) or 0.0))

    shared = [group for group in grouped.values() if len(group["tickers"]) >= 2]
    shared.sort(key=lambda group: (len(group["tickers"]), group["confidence"]), reverse=True)
    return shared[:3]


def detect_deal_catalyst(text: str) -> dict | None:
    lowered = str(text or "").lower()
    legal_or_media_noise = (
        "dominion voting",
        "voting systems",
        "defamation",
        "lawsuit",
        "settlement reached",
        "on-air claims",
        "fox news acknowledges",
    )
    market_specific_terms = (
        "trade deal",
        "tariff relief",
        "tariff exemption",
        "tariff rollback",
        "peace deal",
        "ceasefire",
        "defense contract",
        "government contract",
        "supply agreement",
        "strategic partnership",
        "investment",
        "approved",
        "approval",
    )
    negative_terms = (
        "terminated",
        "blocked",
        "cancelled",
        "canceled",
        "sanctions",
        "new tariff",
        "raise tariffs",
        "investigation",
    )
    policy_or_ticker_terms = (
        "trump",
        "white house",
        "china",
        "iran",
        "tariff",
        "tesla",
        "ford",
        "nvidia",
        "chips",
        "semiconductor",
        "ai",
        "spacex",
        "defense",
        "export controls",
    )
    if any(term in lowered for term in legal_or_media_noise) and not any(
        term in lowered for term in market_specific_terms
    ):
        return None
    if not any(term in lowered for term in market_specific_terms):
        return None
    if not any(term in lowered for term in policy_or_ticker_terms):
        return None
    direction = "down" if any(term in lowered for term in negative_terms) else "up"
    return {"direction": direction, "confidence": 0.68, "boost": 0.08 if direction == "up" else -0.06}


def swing_hold_plan(direction: str) -> str:
    option_type = "calls" if direction == "call" else "puts" if direction == "put" else "options"
    return (
        f"Swing {option_type} for 2-5 trading days when the setup stays valid. "
        "Prefer 3-10 DTE so theta is not forcing a same-day decision."
    )


def swing_entry_plan(report: dict) -> str:
    price = float(report.get("price", 0.0) or 0.0)
    atr_pct = float(report.get("atr_pct", 0.0) or 0.0)
    atr_dollars = price * atr_pct if price > 0 and atr_pct > 0 else 0.0
    if price > 0 and atr_dollars > 0:
        return (
            f"Use regular-hours confirmation near ${price:.2f}. "
            f"Do not chase a gap larger than about ${atr_dollars:.2f} from the research price."
        )
    if price > 0:
        return f"Use regular-hours confirmation near ${price:.2f}; avoid chasing a large opening gap."
    return "Use regular-hours confirmation; avoid chasing a large opening gap."


def swing_exit_plan() -> str:
    return (
        "Exit plan: target about +35% on option premium, stop about -15%, "
        "allow day-0 profit only if it is already +45% or better, and force-exit by day 5."
    )


def earnings_context(items: list[dict]) -> dict:
    reasons = []
    boost = 0.0
    for item in items[:8]:
        text = news_blob(item).lower()
        if "earnings" not in text and "revenue" not in text and "guidance" not in text:
            continue
        if any(term in text for term in ("beat", "beats", "raises guidance", "strong guidance", "better than expected")):
            boost += 0.07
            reasons.append(f"earnings positive: {snippet(text)}")
        elif any(term in text for term in ("miss", "misses", "cuts guidance", "weak guidance", "worse than expected")):
            boost -= 0.08
            reasons.append(f"earnings risk: {snippet(text)}")
    return {"score_boost": max(-0.10, min(0.12, boost)), "reasons": dedupe(reasons)}


def build_swing_plan(reports: dict) -> dict:
    ranked = []
    for ticker, report in reports.items():
        if not isinstance(report, dict) or report.get("status") != "ok":
            continue
        recommendation = str(report.get("recommendation", "watch"))
        if recommendation == "avoid":
            continue
        ranked.append((ticker, report))
    ranked.sort(key=lambda item: float(item[1].get("swing_score", item[1].get("score", 0.0)) or 0.0), reverse=True)
    if not ranked:
        return {"status": "none", "ticker": "", "direction": "", "score": 0.0, "reasons": ["No swing candidate passed research."]}
    ticker, report = ranked[0]
    reasons = report.get("reasons") or []
    return {
        "status": "ready" if report.get("recommendation") in {"prefer_call", "prefer_put"} else "watch",
        "ticker": ticker,
        "direction": report.get("preferred_direction", "watch"),
        "score": report.get("swing_score", report.get("score", 0.0)),
        "price": report.get("price", 0.0),
        "recommendation": report.get("recommendation", "watch"),
        "reasons": reasons[:5],
        "catalysts": report.get("catalysts", [])[:3],
        "hold_plan": swing_hold_plan(str(report.get("preferred_direction", "watch"))),
        "entry_plan": swing_entry_plan(report),
        "exit_plan": swing_exit_plan(),
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


def news_blob(item: dict) -> str:
    return " ".join(str(item.get(field, "") or "") for field in ("headline", "summary", "content"))


def snippet(text: str, limit: int = 150) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()[:limit]


def dedupe(items: list[str]) -> list[str]:
    seen = set()
    out = []
    for item in items:
        clean = snippet(item, 220)
        if clean and clean not in seen:
            out.append(clean)
            seen.add(clean)
    return out


def format_research_summary(payload: dict, max_tickers: int = 8, include_news: bool = True) -> str:
    reports = payload.get("reports") or {}
    candidate = payload.get("candidate") or {}
    researched = payload.get("researched_tickers") or []
    market_catalysts = payload.get("market_catalysts") or []
    shared_catalyst_keys = {str(item.get("key") or "") for item in market_catalysts if item.get("key")}
    shared_catalyst_keys.update(
        catalyst_key(f"{item.get('headline', '')} {item.get('summary', '')}")
        for item in market_catalysts
        if item.get("headline") or item.get("summary")
    )
    shared_catalyst_keys.discard("")
    lines = ["**Ticker research summary**"]
    created_at = payload.get("created_at")
    if created_at:
        lines.append(f"Updated: `{created_at}`")
    if researched:
        lines.append(f"Research universe: `{len(researched)}` tickers from watchlist + best scan candidates")
    if candidate:
        lines.append(
            "Best next-session idea: "
            f"`{candidate.get('ticker', 'n/a')}` `{candidate.get('direction', 'n/a')}` "
            f"score `{float(candidate.get('score', 0.0) or 0.0):.2f}`"
        )
    else:
        lines.append("Best next-session idea: `none`")

    if market_catalysts:
        lines.append("")
        lines.append("**Market catalyst**")
        for catalyst in market_catalysts[:2]:
            direction = str(catalyst.get("direction") or "watch")
            event = str(catalyst.get("type") or "market_news").replace("_", " ")
            headline = str(catalyst.get("headline") or catalyst.get("summary") or "").strip()
            tickers = ", ".join((catalyst.get("tickers") or [])[:8])
            confidence = float(catalyst.get("confidence", 0.0) or 0.0)
            lines.append(f"- {direction.upper()} {event} ({confidence:.0%}) for `{tickers}`")
            if headline:
                lines.append(f"  {headline[:240]}")
            correlations = catalyst.get("correlations") or []
            if correlations:
                lines.append(f"  Correlation: {str(correlations[0])[:220]}")

    swing = payload.get("swing_plan") or {}
    if swing.get("ticker"):
        lines.append("")
        lines.append("**Swing plan**")
        lines.append(
            f"`{swing.get('ticker')}` `{swing.get('direction', 'watch')}` "
            f"score `{float(swing.get('score', 0.0) or 0.0):.2f}` "
            f"near `${float(swing.get('price', 0.0) or 0.0):.2f}`"
        )
        for key in ("hold_plan", "entry_plan", "exit_plan"):
            value = str(swing.get(key, "") or "").strip()
            if value:
                lines.append(f"- {value}")
        for reason in (swing.get("reasons") or [])[:3]:
            lines.append(f"- why: {str(reason)[:170]}")
        for catalyst in (swing.get("catalysts") or [])[:2]:
            if str(catalyst.get("key") or "") in shared_catalyst_keys:
                lines.append("- catalyst: uses the market catalyst above; not repeating the full news text")
                continue
            direction = str(catalyst.get("direction", "watch"))
            headline = str(catalyst.get("headline") or catalyst.get("summary") or "").strip()
            if headline:
                lines.append(f"- catalyst {direction}: {headline[:170]}")

    lines.append("")
    for ticker, report in top_research_reports(reports, max_tickers=max_tickers):
        recommendation = str(report.get("recommendation", "watch"))
        direction = str(report.get("preferred_direction", "n/a"))
        score = float(report.get("swing_score", report.get("score", 0.0)) or 0.0)
        price = float(report.get("price", 0.0) or 0.0)
        rsi = float(report.get("rsi_14", 0.0) or 0.0)
        marker = research_marker(recommendation, direction)
        lines.append(f"{marker} `{ticker}` {recommendation} / {direction} score `{score:.2f}` price `${price:.2f}` RSI `{rsi:.1f}`")
        reasons = report.get("reasons") or []
        for reason in reasons[:2]:
            lines.append(f"- {str(reason)[:160]}")
        if include_news:
            news = report.get("news") or []
            non_shared_news = [
                item
                for item in news
                if catalyst_key(f"{item.get('headline', '')} {item.get('summary', '')}") not in shared_catalyst_keys
            ]
            if non_shared_news:
                headline = str(non_shared_news[0].get("headline") or "").strip()
                summary = str(non_shared_news[0].get("summary") or "").strip()
                snippet = headline or summary
                if snippet:
                    lines.append(f"- news: {snippet[:180]}")

    text = "\n".join(lines)
    if len(text) > 1900:
        text = text[:1850].rstrip() + "\n...trimmed"
    return text


def top_research_reports(reports: dict, max_tickers: int = 8) -> list[tuple[str, dict]]:
    def sort_key(item: tuple[str, dict]) -> tuple[int, float]:
        report = item[1] or {}
        recommendation = str(report.get("recommendation", "watch"))
        priority = {
            "prefer_call": 4,
            "prefer_put": 4,
            "watch": 2,
            "avoid": 1,
        }.get(recommendation, 0)
        return priority, float(report.get("swing_score", report.get("score", 0.0)) or 0.0)

    clean = [(str(ticker).upper(), report) for ticker, report in reports.items() if isinstance(report, dict)]
    clean.sort(key=sort_key, reverse=True)
    return clean[:max_tickers]


def research_marker(recommendation: str, direction: str) -> str:
    text = f"{recommendation} {direction}".lower()
    if "put" in text or "avoid" in text:
        return "🔴⬇️"
    if "call" in text:
        return "🔵⬆️"
    return "🔵"


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    print(json.dumps(run_pretrade_research(), indent=2))


if __name__ == "__main__":
    main()
