from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.optimize import minimize, minimize_scalar
from scipy.special import expit, logit
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score


METHODS = ("identity", "intercept", "temperature", "platt", "beta", "isotonic")


def _clip(values) -> np.ndarray:
    return np.clip(np.asarray(values, dtype=float), 1e-6, 1 - 1e-6)


@dataclass
class ProbabilityCalibrator:
    method: str
    parameters: dict[str, float] = field(default_factory=dict)
    isotonic: IsotonicRegression | None = None

    def predict(self, probability) -> np.ndarray:
        probability = _clip(probability)
        score = logit(probability)
        if self.method == "identity":
            output = probability
        elif self.method == "intercept":
            output = expit(score + self.parameters["intercept"])
        elif self.method == "temperature":
            output = expit(self.parameters["slope"] * score)
        elif self.method == "platt":
            output = expit(
                self.parameters["slope"] * score + self.parameters["intercept"]
            )
        elif self.method == "beta":
            output = expit(
                self.parameters["a"] * np.log(probability)
                - self.parameters["b"] * np.log1p(-probability)
                + self.parameters["intercept"]
            )
        elif self.method == "isotonic" and self.isotonic is not None:
            output = self.isotonic.predict(probability)
        else:
            raise ValueError(self.method)
        return _clip(output)


def fit_calibrator(method: str, probability, target) -> ProbabilityCalibrator:
    probability = _clip(probability)
    target = np.asarray(target, dtype=int)
    score = logit(probability)
    if method == "identity":
        return ProbabilityCalibrator(method)
    if method == "intercept":
        result = minimize_scalar(
            lambda value: log_loss(target, expit(score + value)),
            bounds=(-5, 5),
            method="bounded",
        )
        return ProbabilityCalibrator(method, {"intercept": float(result.x)})
    if method == "temperature":
        result = minimize_scalar(
            lambda value: log_loss(target, expit(value * score)),
            bounds=(0.05, 5),
            method="bounded",
        )
        return ProbabilityCalibrator(method, {"slope": float(result.x)})
    if method == "platt":
        result = minimize(
            lambda value: log_loss(target, expit(value[0] * score + value[1])),
            x0=np.array([1.0, 0.0]),
            bounds=[(0.05, 5), (-5, 5)],
            method="L-BFGS-B",
        )
        return ProbabilityCalibrator(
            method, {"slope": float(result.x[0]), "intercept": float(result.x[1])}
        )
    if method == "beta":
        design = np.column_stack([np.log(probability), -np.log1p(-probability)])
        result = minimize(
            lambda value: log_loss(target, expit(design @ value[:2] + value[2])),
            x0=np.array([1.0, 1.0, 0.0]),
            bounds=[(0.001, 10), (0.001, 10), (-10, 10)],
            method="L-BFGS-B",
        )
        return ProbabilityCalibrator(
            method,
            {
                "a": float(result.x[0]),
                "b": float(result.x[1]),
                "intercept": float(result.x[2]),
            },
        )
    if method == "isotonic":
        estimator = IsotonicRegression(
            y_min=0.001, y_max=0.999, increasing=True, out_of_bounds="clip"
        ).fit(probability, target)
        return ProbabilityCalibrator(method, isotonic=estimator)
    raise ValueError(method)


def _calibration_curve(probability: np.ndarray, target: np.ndarray) -> np.ndarray:
    frame = pd.DataFrame({"probability": probability, "target": target})
    frame["bin"] = pd.qcut(frame["probability"], 20, duplicates="drop")
    observed = frame.groupby("bin", observed=True)["target"].transform("mean")
    return observed.to_numpy(dtype=float)


def calibration_metrics(target, probability) -> dict[str, float]:
    target = np.asarray(target, dtype=int)
    probability = _clip(probability)
    observed = _calibration_curve(probability, target)
    absolute = np.abs(observed - probability)
    score = logit(probability)
    calibration = minimize(
        lambda value: log_loss(target, expit(value[0] + value[1] * score)),
        x0=np.array([0.0, 1.0]),
        bounds=[(-10, 10), (-10, 10)],
        method="L-BFGS-B",
    )
    isotonic = IsotonicRegression(
        y_min=0, y_max=1, increasing=True, out_of_bounds="clip"
    ).fit_transform(probability, target)
    brier = float(brier_score_loss(target, probability))
    calibrated_brier = float(brier_score_loss(target, isotonic))
    uncertainty = float(np.mean(np.square(target - target.mean())))
    return {
        "log_loss": float(log_loss(target, probability)),
        "brier": brier,
        "roc_auc": float(roc_auc_score(target, probability)),
        "calibration_intercept": float(calibration.x[0]),
        "calibration_slope": float(calibration.x[1]),
        "ici": float(absolute.mean()),
        "e50": float(np.quantile(absolute, 0.5)),
        "e90": float(np.quantile(absolute, 0.9)),
        "emax": float(absolute.max()),
        "murphy_miscalibration": brier - calibrated_brier,
        "murphy_discrimination": uncertainty - calibrated_brier,
        "murphy_uncertainty": uncertainty,
    }


def nested_calibration_backtest(
    predictions: pd.DataFrame,
    *,
    minimum_history_seasons: int = 2,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    seasons = sorted(predictions["season"].unique())
    rows: list[dict[str, float | int | str]] = []
    for index, season in enumerate(seasons):
        if index < minimum_history_seasons:
            continue
        history = predictions[predictions["season"] < season]
        test = predictions[predictions["season"] == season]
        for method in METHODS:
            calibrator = fit_calibrator(method, history["probability"], history["played"])
            probability = calibrator.predict(test["probability"])
            rows.append(
                {
                    "test_season": int(season),
                    "method": method,
                    "calibration_rows": len(history),
                    "test_rows": len(test),
                    **calibration_metrics(test["played"], probability),
                }
            )
    by_season = pd.DataFrame(rows)
    metrics = [
        column for column in by_season.columns
        if column not in {"test_season", "method", "calibration_rows", "test_rows"}
    ]
    summary = by_season.groupby("method", as_index=False).agg(
        seasons=("test_season", "nunique"),
        rows=("test_rows", "sum"),
        **{f"mean_{column}": (column, "mean") for column in metrics},
    )
    summary["rank"] = summary["mean_log_loss"].rank(method="dense").astype(int)
    return by_season, summary.sort_values(["rank", "mean_brier"]).reset_index(drop=True)

