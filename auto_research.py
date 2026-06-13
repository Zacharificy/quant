import csv
import json
import logging
import os
import time
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path

from alpaca_stock_bot import NY_TZ, StrategyConfig
from research_runner import fetch_research_bars, parameter_sets, simulate


RESULTS_DIR = Path(os.getenv("BOT_RESEARCH_RESULTS_DIR", "research_results"))
RESULTS_DIR.mkdir(exist_ok=True)

CURRENT_SETTINGS_PATH = Path(os.getenv("BOT_LEARNED_SETTINGS_PATH", "learned_settings.json"))
MIN_TRADES = 15
MAX_DRAWDOWN_PCT = 18.0
MIN_PROFIT_FACTOR = 1.20
MIN_RETURN_IMPROVEMENT_PCT = 3.0


def load_current_settings() -> dict:
    if not CURRENT_SETTINGS_PATH.exists():
        return {}
    with CURRENT_SETTINGS_PATH.open("r", encoding="utf-8") as file:
        return json.load(file)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2, sort_keys=True)


def passes_guardrails(row: dict) -> bool:
    return (
        row["trade_count"] >= MIN_TRADES
        and row["max_drawdown_pct"] <= MAX_DRAWDOWN_PCT
        and row["profit_factor"] >= MIN_PROFIT_FACTOR
    )


def candidate_rank(row: dict) -> tuple:
    # Prefer robust paper candidates over flashy overfit-looking runs.
    risk_adjusted = row["return_pct"] / max(row["max_drawdown_pct"], 1.0)
    return (risk_adjusted, row["return_pct"], row["profit_factor"], row["trade_count"])


def run_autoresearch(apply: bool = False) -> dict:
    max_experiments = int(float(os.getenv("BOT_AUTORESEARCH_MAX_EXPERIMENTS", "0") or 0))
    yield_seconds = max(0.0, float(os.getenv("BOT_AUTORESEARCH_YIELD_SECONDS", "0.15") or 0.0))
    base = StrategyConfig(history_days=900)
    current_settings = load_current_settings()
    if current_settings:
        allowed = {key: value for key, value in current_settings.items() if hasattr(base, key)}
        base = replace(base, **allowed)

    bars = fetch_research_bars(base)
    baseline = simulate(base, bars)
    logging.info(
        "baseline return=%.2f%% dd=%.2f%% trades=%s",
        baseline["return_pct"],
        baseline["max_drawdown_pct"],
        baseline["trade_count"],
    )

    rows = []
    for number, params in enumerate(parameter_sets(), start=1):
        if max_experiments > 0 and number > max_experiments:
            logging.info("stopping parameter autoresearch at configured max experiments=%s", max_experiments)
            break
        config = replace(base, **params)
        metrics = simulate(config, bars)
        row = {**params, **metrics, "experiment": number}
        rows.append(row)
        logging.info(
            "experiment=%s return=%.2f%% dd=%.2f%% trades=%s",
            number,
            metrics["return_pct"],
            metrics["max_drawdown_pct"],
            metrics["trade_count"],
        )
        if yield_seconds:
            time.sleep(yield_seconds)

    viable = [row for row in rows if passes_guardrails(row)]
    viable.sort(key=candidate_rank, reverse=True)
    best = viable[0] if viable else None

    should_apply = False
    reason = "no viable candidate passed guardrails"
    if best:
        improvement = best["return_pct"] - baseline["return_pct"]
        should_apply = improvement >= MIN_RETURN_IMPROVEMENT_PCT
        reason = (
            f"best improves return by {improvement:.2f}%"
            if should_apply
            else f"best improvement {improvement:.2f}% is below {MIN_RETURN_IMPROVEMENT_PCT:.2f}% threshold"
        )

    timestamp = datetime.now(NY_TZ).strftime("%Y%m%d_%H%M%S")
    leaderboard_path = RESULTS_DIR / f"autoresearch_leaderboard_{timestamp}.csv"
    recommendation_path = RESULTS_DIR / f"autoresearch_recommendation_{timestamp}.json"

    rows.sort(key=lambda row: row["return_pct"], reverse=True)
    with leaderboard_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    recommendation = {
        "created_at": datetime.now(NY_TZ).isoformat(timespec="seconds"),
        "guardrails": {
            "min_trades": MIN_TRADES,
            "max_drawdown_pct": MAX_DRAWDOWN_PCT,
            "min_profit_factor": MIN_PROFIT_FACTOR,
            "min_return_improvement_pct": MIN_RETURN_IMPROVEMENT_PCT,
        },
        "baseline": baseline,
        "current_settings": asdict(base),
        "best_candidate": best,
        "apply_requested": apply,
        "should_apply": should_apply,
        "reason": reason,
        "leaderboard_path": str(leaderboard_path),
    }

    if apply and should_apply and best:
        typed_fields = {
            "breakout_lookback_days": int,
            "min_score": float,
            "min_cross_sectional_score": float,
            "stop_atr_multiple": float,
            "take_profit_atr_multiple": float,
            "max_hold_days": int,
            "target_stock_risk_cash": float,
        }
        learned = {}
        for key, caster in typed_fields.items():
            if key in best:
                learned[key] = caster(best[key])
        learned["source"] = str(recommendation_path)
        learned["applied_at"] = datetime.now(NY_TZ).isoformat(timespec="seconds")
        write_json(CURRENT_SETTINGS_PATH, learned)
        recommendation["applied_settings"] = learned

    write_json(recommendation_path, recommendation)
    print(f"Wrote {leaderboard_path}")
    print(f"Wrote {recommendation_path}")
    if apply and recommendation.get("applied_settings"):
        print(f"Applied settings to {CURRENT_SETTINGS_PATH}")
    else:
        print(f"Did not apply settings: {reason}")
    print(json.dumps(recommendation, indent=2))
    return recommendation


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Run guarded autoresearch for the Alpaca bot.")
    parser.add_argument("--apply", action="store_true", help="Write learned_settings.json if the best candidate passes guardrails.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run_autoresearch(apply=args.apply)


if __name__ == "__main__":
    main()
