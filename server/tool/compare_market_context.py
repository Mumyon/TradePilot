"""Measure the incremental effect of observed KOSPI bars on 1h forecasts."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from threadpoolctl import threadpool_limits

from app.ml.pipeline import feature_rows, read_csv, validate_bars
from tool.walk_forward_toss_models import SYMBOLS, prepare, trading_date, walk_forward


def matched_market_inputs(data, stock_bars, market_bars):
    validate_bars(market_bars)
    rows, x, kernels, targets, volatility = data
    market_features = {r["as_of"]: r["x"] for r in feature_rows(market_bars)}
    market_index = {b.as_of: i for i, b in enumerate(market_bars)}
    stock_index = {b.as_of: i for i, b in enumerate(stock_bars)}
    stock_prices = np.log([b.close for b in stock_bars])
    market_prices = np.log([b.close for b in market_bars])
    indices, context = [], []
    for i, row in enumerate(rows):
        stamp = row["as_of"]
        if stamp not in market_features:
            continue
        own, other = stock_index[stamp], market_index[stamp]
        own_returns = np.diff(stock_prices[own - 24 : own + 1])
        index_returns = np.diff(market_prices[other - 24 : other + 1])
        x_centered = index_returns - index_returns.mean()
        y_centered = own_returns - own_returns.mean()
        index_variance = x_centered @ x_centered
        beta = float(np.clip((x_centered @ y_centered) / max(1e-10, index_variance), -3, 3))
        residual = own_returns - beta * index_returns
        context.append(
            [
                *market_features[stamp],
                beta,
                np.sqrt(index_variance / len(index_returns)),
                np.sqrt(np.mean(residual**2)),
                *(index_returns[-n:].sum() for n in (3, 6, 12, 24)),
                *(residual[-n:].sum() for n in (3, 6, 12, 24)),
            ]
        )
        indices.append(i)
    if not indices:
        raise ValueError("No same-time completed market bars")
    subset = (
        [rows[i] for i in indices],
        x[indices],
        kernels[indices],
        targets[indices],
        volatility[indices],
    )
    return subset, (subset[0], np.column_stack((subset[1], context)), *subset[2:])


def adaptive_prior(rows, origins, training_prior, *, half_life_seconds=3 * 86400):
    """Use only outcomes whose target bar has already closed at the forecast origin."""
    prior = np.array(training_prior)
    candidates = sorted(rows, key=lambda row: row["target_at"])
    evidence = np.zeros(3)
    next_outcome = 0
    last_update = candidates[0]["target_at"]
    result = []
    for origin in origins:
        as_of = rows[origin]["as_of"]
        while next_outcome < len(candidates) and candidates[next_outcome]["target_at"] <= as_of:
            outcome = candidates[next_outcome]
            elapsed = (outcome["target_at"] - last_update).total_seconds()
            evidence *= 2 ** (-elapsed / half_life_seconds)
            evidence[outcome["y"]] += 1
            last_update = outcome["target_at"]
            next_outcome += 1
        elapsed = max(0, (as_of - last_update).total_seconds())
        decayed = evidence * 2 ** (-elapsed / half_life_seconds)
        result.append((decayed + 30 * prior) / (decayed.sum() + 30))
    return np.array(result)


def adaptive_candidates(rows, _train, future, prior, forecasts):
    recent = adaptive_prior(rows, future, prior)
    weights = np.sqrt(recent / np.array(prior))
    candidates = {"adaptive-prior": recent}
    for name in ("cross-stock-logistic", "cross-stock-catboost", "student-t-return-regression"):
        adjusted = forecasts[name] * weights
        candidates[f"adaptive-{name}"] = adjusted / adjusted.sum(axis=1, keepdims=True)
    return candidates


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    files = {symbol: sorted(args.data.glob(f"{symbol}-*.csv")) for symbol in (*SYMBOLS, "KOSPI")}
    bars = {
        symbol: [b for file in paths for b in read_csv(file)] for symbol, paths in files.items()
    }
    report = dict(
        source="Toss Open API stock and KOSPI completed 5m candles",
        source_sha256={
            name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
            for name in ("compare_market_context.py", "walk_forward_toss_models.py")
        },
        input_sha256={
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for paths in files.values()
            for path in paths
        },
        symbols={},
    )
    with threadpool_limits(limits=1):
        for symbol, peer in (SYMBOLS, SYMBOLS[::-1]):
            base = prepare(bars[symbol], bars[peer])
            matched, market = matched_market_inputs(base, bars[symbol], bars["KOSPI"])
            result = {}
            for name, data in (("stock-only", matched), ("with-kospi", market)):
                result[name] = walk_forward(data, extra_candidates=adaptive_candidates)
                print(symbol, name, len(result[name]["folds"]), "windows", flush=True)
            result["data_start"] = str(trading_date(bars[symbol][0].opened_at))
            result["data_end"] = str(trading_date(bars[symbol][-1].as_of))
            report["symbols"][symbol] = result
    args.output.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)
    with args.output.open("x", encoding="utf-8") as output:
        output.write(serialized)


if __name__ == "__main__":
    main()
