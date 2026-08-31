from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.metrics import mean_absolute_error, mean_poisson_deviance, mean_squared_error

from .features import feature_sets
from .model import RecentMeanRegressor, build_estimator


TARGET_POSITIONS = {
    "completions": ("QB",),
    "attempts": ("QB",),
    "passing_yards": ("QB",),
    "passing_tds": ("QB",),
    "passing_interceptions": ("QB",),
    "passing_2pt_conversions": ("QB",),
    "carries": ("QB", "RB", "FB", "WR"),
    "rushing_yards": ("QB", "RB", "FB", "WR"),
    "rushing_tds": ("QB", "RB", "FB", "WR"),
    "rushing_2pt_conversions": ("QB", "RB", "FB", "WR", "TE"),
    "targets": ("RB", "FB", "WR", "TE"),
    "receptions": ("RB", "FB", "WR", "TE"),
    "receiving_yards": ("RB", "FB", "WR", "TE"),
    "receiving_tds": ("RB", "FB", "WR", "TE"),
    "receiving_2pt_conversions": ("RB", "FB", "WR", "TE"),
    "special_teams_tds": ("RB", "FB", "WR", "TE", "K"),
    "fumbles_lost_total": ("QB", "RB", "FB", "WR", "TE", "K"),
    "fg_made_0_19": ("K",),
    "fg_made_20_29": ("K",),
    "fg_made_30_39": ("K",),
    "fg_made_40_49": ("K",),
    "fg_made_50_59": ("K",),
    "fg_made_60_": ("K",),
    "pat_made": ("K",),
    "pat_missed": ("K",),
}


@dataclass(frozen=True)
class BacktestSpec:
    first_test_season: int
    last_test_season: int
    seed: int = 20260830
    min_player_games: int = 2


def regression_metrics(actual: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    predicted = np.clip(np.asarray(predicted, dtype=float), 1e-6, None)
    actual = np.asarray(actual, dtype=float)
    rank = (
        0.0
        if np.ptp(actual) == 0 or np.ptp(predicted) == 0
        else spearmanr(actual, predicted).statistic
    )
    poisson_deviance = (
        float(mean_poisson_deviance(actual, predicted))
        if np.all(actual >= 0)
        else float("nan")
    )
    return {
        "mae": float(mean_absolute_error(actual, predicted)),
        "rmse": float(mean_squared_error(actual, predicted) ** 0.5),
        "poisson_deviance": poisson_deviance,
        "spearman": float(0.0 if np.isnan(rank) else rank),
        "actual_mean": float(actual.mean()),
        "predicted_mean": float(predicted.mean()),
    }


def walk_forward_backtest(
    features: pd.DataFrame,
    target: str,
    spec: BacktestSpec,
    *,
    model_names: tuple[str, ...] = ("recent_mean", "linear", "hist"),
    set_names: tuple[str, ...] = (
        "recent_mean",
        "player_form",
        "workload",
        "screened",
        "context",
        "market_context",
    ),
) -> tuple[pd.DataFrame, pd.DataFrame]:
    positions = TARGET_POSITIONS[target]
    frame = features[
        features["position"].isin(positions)
        & features["player_games_prior"].ge(spec.min_player_games)
    ].copy()
    sets = feature_sets(target)
    nonnegative_target = bool(frame[target].min() >= 0)
    rows: list[dict[str, float | int | str]] = []
    predictions: list[pd.DataFrame] = []

    for season in range(spec.first_test_season, spec.last_test_season + 1):
        train = frame[frame["season"] < season]
        test = frame[frame["season"] == season]
        if train.empty or test.empty:
            continue
        for set_name in set_names:
            columns = sets[set_name]
            compatible_models = ("recent_mean",) if set_name == "recent_mean" else model_names[1:]
            for model_name in compatible_models:
                if model_name == "recent_mean":
                    estimator = RecentMeanRegressor(columns[0]).fit(train[columns], train[target])
                else:
                    estimator = build_estimator(
                        model_name,
                        seed=spec.seed,
                        nonnegative_target=nonnegative_target,
                    )
                    estimator.fit(train[columns], train[target])
                predicted = np.clip(estimator.predict(test[columns]), 1e-6, None)
                relevant = (
                    test["offense_pct_ewm4"].fillna(0).ge(0.25)
                    | (
                        test["position"].eq("K")
                        & test["st_snaps_ewm4"].fillna(0).gt(0)
                    )
                ).to_numpy()
                for scope, mask in (
                    ("all_active_roster", np.ones(len(test), dtype=bool)),
                    ("fantasy_relevant", relevant),
                ):
                    if not mask.any():
                        continue
                    rows.append(
                        {
                            "target": target,
                            "scope": scope,
                            "test_season": season,
                            "feature_set": set_name,
                            "model": model_name,
                            "train_rows": len(train),
                            "test_rows": int(mask.sum()),
                            **regression_metrics(
                                test[target].to_numpy()[mask], predicted[mask]
                            ),
                        }
                    )
                output = test[[
                    "game_id", "season", "week", "player_id", "player_name", "position", "team", "opponent_team"
                ]].copy()
                output["target"] = target
                output["feature_set"] = set_name
                output["model"] = model_name
                output["actual"] = test[target].to_numpy()
                output["predicted"] = predicted
                predictions.append(output)
    return pd.DataFrame(rows), pd.concat(predictions, ignore_index=True)


def summarize_backtest(metrics: pd.DataFrame) -> pd.DataFrame:
    summary = metrics.groupby(
        ["target", "scope", "feature_set", "model"], as_index=False
    ).agg(
        seasons=("test_season", "nunique"),
        rows=("test_rows", "sum"),
        mean_mae=("mae", "mean"),
        mean_rmse=("rmse", "mean"),
        mean_poisson_deviance=("poisson_deviance", "mean"),
        mean_spearman=("spearman", "mean"),
        mean_predicted=("predicted_mean", "mean"),
    )
    summary["rank"] = summary.groupby(["target", "scope"])["mean_rmse"].rank(
        method="dense"
    ).astype(int)
    return summary.sort_values(["target", "rank", "mean_rmse"]).reset_index(drop=True)
