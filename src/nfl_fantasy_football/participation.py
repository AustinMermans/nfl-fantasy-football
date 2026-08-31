from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler


def participation_feature_sets() -> dict[str, list[str]]:
    history = [
        "player_games_prior",
        "position_code",
        "played_lag1",
        "played_ewm4",
        "played_ewm12",
        "offense_pct_lag1",
        "offense_pct_ewm4",
        "offense_pct_ewm12",
        "offense_snaps_ewm4",
        "offense_snaps_ewm12",
        "st_snaps_ewm4",
        "st_snaps_ewm12",
    ]
    injury = history + [
        "injury_reported",
        "report_out",
        "report_doubtful",
        "report_questionable",
        "practice_dnp",
        "practice_limited",
    ]
    context = injury + ["home", "rest_days", "week", "age", "years_since_draft"]
    return {"history": history, "injury": injury, "context": context}


def _estimator(name: str, seed: int):
    if name == "logistic":
        return make_pipeline(
            SimpleImputer(strategy="median", add_indicator=True),
            StandardScaler(),
            LogisticRegression(C=0.25, max_iter=500),
        )
    if name == "hist":
        return make_pipeline(
            SimpleImputer(strategy="median", add_indicator=True),
            HistGradientBoostingClassifier(
                learning_rate=0.06,
                max_iter=180,
                max_leaf_nodes=15,
                l2_regularization=2.0,
                random_state=seed,
            ),
        )
    raise ValueError(name)


def probability_metrics(actual: pd.Series, probability: np.ndarray) -> dict[str, float]:
    probability = np.clip(probability, 1e-6, 1 - 1e-6)
    return {
        "log_loss": float(log_loss(actual, probability)),
        "brier": float(brier_score_loss(actual, probability)),
        "roc_auc": float(roc_auc_score(actual, probability)),
        "actual_rate": float(actual.mean()),
        "predicted_rate": float(probability.mean()),
    }


def walk_forward_participation(
    frame: pd.DataFrame,
    *,
    first_test_season: int,
    last_test_season: int,
    min_player_games: int,
    seed: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    data = frame[frame["player_games_prior"].ge(min_player_games)].copy()
    sets = participation_feature_sets()
    rows: list[dict[str, float | int | str]] = []
    outputs: list[pd.DataFrame] = []
    for season in range(first_test_season, last_test_season + 1):
        train = data[data["season"] < season]
        test = data[data["season"] == season]
        for set_name, columns in sets.items():
            for model_name in ("logistic", "hist"):
                estimator = _estimator(model_name, seed)
                estimator.fit(train[columns], train["played"])
                probability = estimator.predict_proba(test[columns])[:, 1]
                rows.append(
                    {
                        "test_season": season,
                        "feature_set": set_name,
                        "model": model_name,
                        "train_rows": len(train),
                        "test_rows": len(test),
                        **probability_metrics(test["played"], probability),
                    }
                )
                output = test[[
                    "game_id", "season", "week", "player_id", "player_name",
                    "position", "team", "opponent_team", "played",
                ]].copy()
                output["feature_set"] = set_name
                output["model"] = model_name
                output["probability"] = probability
                outputs.append(output)
    return pd.DataFrame(rows), pd.concat(outputs, ignore_index=True)


def summarize_participation(metrics: pd.DataFrame) -> pd.DataFrame:
    summary = metrics.groupby(["feature_set", "model"], as_index=False).agg(
        seasons=("test_season", "nunique"),
        rows=("test_rows", "sum"),
        mean_log_loss=("log_loss", "mean"),
        mean_brier=("brier", "mean"),
        mean_roc_auc=("roc_auc", "mean"),
        mean_actual_rate=("actual_rate", "mean"),
        mean_predicted_rate=("predicted_rate", "mean"),
    )
    summary["rank"] = summary["mean_log_loss"].rank(method="dense").astype(int)
    return summary.sort_values(["rank", "mean_brier"]).reset_index(drop=True)
