from __future__ import annotations

from dataclasses import dataclass, field
from math import exp
from typing import Mapping, Sequence

import pandas as pd


WEEKLY_OUTCOME_PARAMETERS: dict[str, dict[str, float | int]] = {
    "K": {
        "sampleSize": 735,
        "forecastThreshold": 7.7196,
        "relativeError68": 0.5043,
        "rmse": 4.4601,
    },
    "QB": {
        "sampleSize": 1983,
        "forecastThreshold": 15.4596,
        "relativeError68": 0.4655,
        "rmse": 8.2488,
    },
    "RB": {
        "sampleSize": 3189,
        "forecastThreshold": 8.3337,
        "relativeError68": 0.6373,
        "rmse": 7.4906,
    },
    "TE": {
        "sampleSize": 3717,
        "forecastThreshold": 2.7461,
        "relativeError68": 0.8553,
        "rmse": 4.6725,
    },
    "WR": {
        "sampleSize": 6279,
        "forecastThreshold": 5.5463,
        "relativeError68": 0.7515,
        "rmse": 6.2904,
    },
}


@dataclass(frozen=True)
class LeagueConfig:
    """Rules that turn player outcomes into roster and draft utility."""

    teams: int = 12
    draft_slot: int = 1
    rounds: int = 12
    bench_slots: int = 4
    roster_slots: Mapping[str, int] = field(
        default_factory=lambda: {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "K": 1}
    )
    scoring: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 2 <= self.teams <= 32:
            raise ValueError("teams must be between 2 and 32")
        if not 1 <= self.draft_slot <= self.teams:
            raise ValueError("draft_slot must identify a team in the league")
        if self.rounds < 1 or self.bench_slots < 0:
            raise ValueError("rounds and bench_slots must be nonnegative")


@dataclass(frozen=True)
class PlayerDistribution:
    player_id: str
    position: str
    mean_points: float
    p10: float
    p50: float
    p90: float


def conditional_survival(cdf_now: float, cdf_next_pick: float) -> float:
    """Probability a player survives given that the player is available now."""
    if not 0.0 <= cdf_now <= 1.0 or not 0.0 <= cdf_next_pick <= 1.0:
        raise ValueError("CDF values must be probabilities")
    if cdf_next_pick < cdf_now:
        raise ValueError("a CDF cannot decrease between draft picks")
    remaining = 1.0 - cdf_now
    return 0.0 if remaining <= 0.0 else (1.0 - cdf_next_pick) / remaining


def quantal_response_probabilities(
    utilities: Sequence[float], *, rationality: float = 1.0
) -> list[float]:
    """Convert opponent utilities into stable softmax choice probabilities."""
    if rationality < 0:
        raise ValueError("rationality must be nonnegative")
    if not utilities:
        return []
    scaled = [rationality * float(value) for value in utilities]
    anchor = max(scaled)
    weights = [exp(value - anchor) for value in scaled]
    total = sum(weights)
    return [weight / total for weight in weights]


def bench_option_value(outcomes: Sequence[float], replacement_points: float) -> float:
    """Expected payoff above replacement for a stashable uncertain player."""
    if not outcomes:
        return 0.0
    return sum(max(0.0, float(value) - replacement_points) for value in outcomes) / len(outcomes)


def estimate_weekly_outcome_parameters(
    predictions: pd.DataFrame,
) -> dict[str, dict[str, float | int]]:
    """Estimate robust weekly forecast noise from out-of-sample predictions.

    The upper half of each position's forecast distribution approximates the
    player pool that reaches managed fantasy rosters. Relative residuals use a
    three-point denominator floor so low-volume positions cannot explode.
    """
    required = {
        "position",
        "actual_fantasy_points",
        "predicted_fantasy_points",
        "fantasy_relevant",
    }
    missing = required.difference(predictions.columns)
    if missing:
        raise ValueError(f"predictions missing columns: {sorted(missing)}")

    eligible = predictions.loc[
        predictions["fantasy_relevant"].fillna(False)
        & predictions["position"].isin(("QB", "RB", "WR", "TE", "K"))
    ].copy()
    parameters: dict[str, dict[str, float | int]] = {}
    for position, rows in eligible.groupby("position", observed=True):
        threshold = float(rows["predicted_fantasy_points"].median())
        rows = rows.loc[rows["predicted_fantasy_points"] >= threshold]
        residual = rows["actual_fantasy_points"] - rows["predicted_fantasy_points"]
        relative_error = residual.abs() / rows["predicted_fantasy_points"].clip(lower=3.0)
        parameters[str(position)] = {
            "sampleSize": int(len(rows)),
            "forecastThreshold": round(threshold, 4),
            "relativeError68": round(float(relative_error.quantile(0.68)), 4),
            "rmse": round(float((residual.pow(2).mean()) ** 0.5), 4),
        }
    return parameters


def bayesian_model_update(
    prior: Mapping[str, float], likelihood: Mapping[str, float]
) -> dict[str, float]:
    """Update a finite mixture of opponent-room models after an observed pick."""
    if set(prior) != set(likelihood) or not prior:
        raise ValueError("prior and likelihood must contain the same models")
    weights = {
        name: float(prior[name]) * float(likelihood[name]) for name in prior
    }
    if any(value < 0 for value in weights.values()) or sum(weights.values()) <= 0:
        raise ValueError("Bayesian weights must be nonnegative with positive mass")
    total = sum(weights.values())
    return {name: value / total for name, value in weights.items()}
