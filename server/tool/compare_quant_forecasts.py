"""Evaluate established financial time-series models on a separate Toss holdout."""

import argparse
import hashlib
import json
from datetime import date
from importlib.metadata import version
from pathlib import Path

import numpy as np
from arch import arch_model
from scipy.special import ndtr
from statsmodels.api import OLS, add_constant
from statsmodels.tsa.regime_switching.markov_regression import MarkovRegression
from threadpoolctl import threadpool_limits

from app.ml.candidates import TEMPERATURES, ordered_probabilities, temperature_scale
from app.ml.experiment import evaluate, research_gate
from app.ml.pipeline import BAR, KST, read_csv, samples, validate_bars

STEPS = 12
LOWER, UPPER = 100 * np.log([0.995, 1.005])
CUTOFFS = (date(2025, 11, 17), date(2025, 12, 1), date(2026, 1, 2))


def day(timestamp):
    return timestamp.astimezone(KST).date()


def observations(bars):
    resets = np.array(
        [i == 0 or bar.opened_at - bars[i - 1].opened_at != BAR for i, bar in enumerate(bars)]
    )
    returns = np.array(
        [
            100 * np.log(b.close / (b.open if resets[i] else bars[i - 1].close))
            for i, b in enumerate(bars)
        ]
    )
    index = {b.as_of: i for i, b in enumerate(bars)}
    rows = [
        {**row, "index": index[row["as_of"]], "target_index": index[row["target_at"]]}
        for row in samples(bars)
    ]
    return resets, returns, rows


def gaussian(mean, variance):
    scale = np.sqrt(np.maximum(1e-10, variance))
    down = ndtr((LOWER - mean) / scale)
    up = ndtr((mean - UPPER) / scale)
    return np.column_stack((up, 1 - up - down, down))


def variance_forecasts(innovations, resets, initial, weights, *, omega, alpha, beta):
    values = []
    variance = initial
    for observed, reset in zip(innovations, resets, strict=True):
        if reset:
            variance = initial
        variance = omega + alpha * observed**2 + beta * variance
        step_variance = variance
        total = 0.0
        for weight in weights:
            total += weight * step_variance
            step_variance = omega + (alpha + beta) * step_variance
        values.append(total)
    return np.array(values)


def garch(innovations, resets, fit_end, weights):
    fitted = arch_model(
        innovations[:fit_end], mean="Zero", vol="GARCH", p=1, q=1, rescale=False
    ).fit(disp="off")
    if fitted.convergence_flag != 0:
        raise ValueError(f"GARCH optimizer did not converge: {fitted.convergence_flag}")
    p = fitted.params
    return variance_forecasts(
        innovations,
        resets,
        np.var(innovations[:fit_end]),
        weights,
        omega=p["omega"],
        alpha=p["alpha[1]"],
        beta=p["beta[1]"],
    ), dict(p)


def markov_probabilities(returns, resets, fit_end):
    model = MarkovRegression(returns[:fit_end], k_regimes=2, switching_variance=True)
    fitted = model.fit(disp=False, maxiter=300)
    if not fitted.mle_retvals["converged"]:
        raise ValueError("Markov-switching optimizer did not converge")
    parameters = dict(zip(model.param_names, fitted.params, strict=True))
    transition = fitted.regime_transition[:, :, 0]
    means = np.array([parameters[f"const[{i}]"] for i in range(2)])
    variances = np.array([parameters[f"sigma2[{i}]"] for i in range(2)])
    stationary = np.array([transition[0, 1], transition[1, 0]])
    stationary /= stationary.sum()
    # Under conditionally Gaussian innovations, the 12-step sum depends on
    # how many steps are spent in each regime, regardless of their order.
    states = []
    counts = np.arange(STEPS + 1)
    mixtures = gaussian(
        (STEPS - counts) * means[0] + counts * means[1],
        (STEPS - counts) * variances[0] + counts * variances[1],
    )
    for initial in range(2):
        mass = np.zeros((2, STEPS + 1))
        mass[initial, 0] = 1
        for _ in range(STEPS):
            next_mass = transition @ mass
            mass[0] = next_mass[0]
            mass[1, 0] = 0
            mass[1, 1:] = next_mass[1, :-1]
        states.append(mass.sum(axis=0) @ mixtures)
    states = np.array(states)
    posterior = stationary
    result = []
    for observed, reset in zip(returns, resets, strict=True):
        predicted = stationary if reset else transition @ posterior
        log_density = -0.5 * (np.log(variances) + (observed - means) ** 2 / variances)
        posterior = predicted * np.exp(log_density - log_density.max())
        posterior /= posterior.sum()
        result.append(posterior @ states)
    return np.array(result), parameters


def forecast_models(returns, resets, rows, training, fit_end):
    targets = np.array([r["index"] for r in rows])
    train_targets = np.array([r["index"] for r in training])
    weights = np.ones(STEPS)
    ewma = variance_forecasts(
        returns, resets, np.var(returns[:fit_end]), weights, omega=0, alpha=0.06, beta=0.94
    )
    forecasts = {"riskmetrics-ewma": gaussian(0, ewma[targets])}
    parameters = {"riskmetrics-ewma": {"decay": 0.94}}

    standardized = np.sort(
        [
            returns[r["index"] + 1 : r["target_index"] + 1].sum() / np.sqrt(ewma[r["index"]])
            for r in training
        ]
    )
    scale = np.sqrt(ewma[targets])
    down = standardized.searchsorted(LOWER / scale, side="left") / len(standardized)
    up = 1 - standardized.searchsorted(UPPER / scale, side="right") / len(standardized)
    forecasts["ewma-filtered-historical"] = np.column_stack((up, 1 - up - down, down))
    parameters["ewma-filtered-historical"] = {"decay": 0.94}

    lagged = np.r_[0.0, returns[:-1]]
    eligible = ~resets[:fit_end]
    ar = OLS(returns[:fit_end][eligible], add_constant(lagged[:fit_end][eligible])).fit()
    intercept, phi = ar.params
    mean = np.zeros(len(returns))
    step = returns.copy()
    for _ in range(STEPS):
        step = intercept + phi * step
        mean += step
    ar_weights = (phi ** np.arange(STEPS)).cumsum()[::-1] ** 2
    forecasts["arima-1-0-0"] = gaussian(mean[targets], ar_weights.sum() * ar.mse_resid)
    parameters["arima-1-0-0"] = {"intercept": intercept, "ar1": phi}

    variance, parameters["garch-1-1"] = garch(returns, resets, fit_end, weights)
    forecasts["garch-1-1"] = gaussian(0, variance[targets])
    lagged[resets] = 0
    innovations = returns - intercept - phi * lagged
    variance, garch_params = garch(innovations, resets, fit_end, ar_weights)
    forecasts["ar-garch"] = gaussian(mean[targets], variance[targets])
    parameters["ar-garch"] = {**parameters["arima-1-0-0"], **garch_params}

    squared = returns**2
    har_input = np.column_stack(
        [
            np.log(np.maximum(1e-10, np.convolve(squared, np.ones(n), mode="full")[targets]))
            for n in (3, 6, 12)
        ]
    )
    har_target = np.array(
        [
            np.log(max(1e-10, squared[r["index"] + 1 : r["target_index"] + 1].sum()))
            for r in training
        ]
    )
    har = OLS(har_target, add_constant(har_input[: len(train_targets)])).fit()
    variance = np.exp(har.predict(add_constant(har_input))) * np.exp(har.resid).mean()
    forecasts["intraday-har-rv"] = gaussian(0, variance)
    parameters["intraday-har-rv"] = {"input_bars": [3, 6, 12], "coefficients": har.params.tolist()}

    markov, parameters["markov-switching"] = markov_probabilities(returns, resets, fit_end)
    forecasts["markov-switching"] = markov[targets]
    return forecasts, parameters


def compare(bars):
    validate_bars(bars)
    resets, returns, rows = observations(bars)
    calibration_start, selection_start, test_start = CUTOFFS
    splits = [
        [r for r in rows if day(r["target_at"]) < calibration_start],
        [
            r
            for r in rows
            if calibration_start <= day(r["as_of"]) and day(r["target_at"]) < selection_start
        ],
        [
            r
            for r in rows
            if selection_start <= day(r["as_of"]) and day(r["target_at"]) < test_start
        ],
        [r for r in rows if day(r["as_of"]) >= test_start],
    ]
    if sum(map(len, splits)) != len(rows) or any(
        len(group) < 100 or {r["y"] for r in group} != {0, 1, 2} for group in splits
    ):
        raise ValueError(f"Insufficient or overlapping split data: {list(map(len, splits))}")
    training, calibration, selection, testing = splits
    fit_end = next(i for i, bar in enumerate(bars) if day(bar.as_of) >= calibration_start)
    forecasts, parameters = forecast_models(returns, resets, rows, training, fit_end)
    forecasts = {
        name: ordered_probabilities(probabilities, [0, 1, 2])
        for name, probabilities in forecasts.items()
    }
    a, b, c = np.cumsum([len(training), len(calibration), len(selection)])
    prior = [sum(r["y"] == i for r in training) / len(training) for i in range(3)]
    validation_baseline = evaluate(selection, [prior] * len(selection))
    candidates = {}
    for name, probs in forecasts.items():
        temperature = min(
            TEMPERATURES,
            key=lambda t: evaluate(calibration, temperature_scale(probs[a:b], t))["log_loss"],
        )
        validation = evaluate(selection, temperature_scale(probs[b:c], temperature))
        candidates[name] = dict(
            parameters=parameters[name],
            temperature=temperature,
            validation=validation,
            validation_gate=research_gate(validation, validation_baseline),
        )
    nominee = max(
        candidates,
        key=lambda name: (
            candidates[name]["validation_gate"]["passed"],
            candidates[name]["validation"]["macro_f1"],
            -candidates[name]["validation"]["brier"],
        ),
    )
    baseline = evaluate(testing, [prior] * len(testing))
    for name, result in candidates.items():
        test = evaluate(testing, temperature_scale(forecasts[name][c:], result["temperature"]))
        result.update(test=test, test_gate=research_gate(test, baseline))
    return dict(
        bars=len(bars),
        splits={
            name: dict(
                count=len(group),
                start=group[0]["as_of"].isoformat(),
                end=group[-1]["target_at"].isoformat(),
            )
            for name, group in zip(
                ("training", "calibration", "selection", "test"), splits, strict=True
            )
        },
        baseline=baseline,
        candidates=candidates,
        selected_before_holdout=nominee,
        confirmed_model=nominee if candidates[nominee]["test_gate"]["passed"] else None,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = dict(
        source="Toss Open API completed 5m OHLCV",
        cutoff_dates_kst=[str(d) for d in CUTOFFS],
        horizon_minutes=60,
        threshold_percent=0.5,
        confidence_threshold=0.65,
        packages={p: version(p) for p in ("arch", "statsmodels", "numpy", "scipy")},
        source_code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        symbols={},
    )
    with threadpool_limits(limits=1):
        for symbol in ("005930", "000660"):
            files = sorted(args.data.glob(f"{symbol}-*.csv"))
            bars = [bar for file in files for bar in read_csv(file)]
            if (
                not bars
                or day(bars[0].as_of) != date(2025, 9, 1)
                or day(bars[-1].as_of) != date(2026, 1, 30)
            ):
                raise ValueError(f"{symbol}: incomplete fixed data range")
            result = compare(bars)
            result["input_sha256"] = {
                path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in files
            }
            report["symbols"][symbol] = result
            print(symbol, result["selected_before_holdout"], result["confirmed_model"], flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(report, output, ensure_ascii=False, indent=2, allow_nan=False)


if __name__ == "__main__":
    main()
