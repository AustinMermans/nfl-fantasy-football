from __future__ import annotations

import pandas as pd

from .evaluation import regression_metrics
from .scoring import score_components, scoring_fields


DEPLOYMENT_SELECTION: dict[str, tuple[str, str]] = {
    "passing_yards": ("context", "hist"),
    "passing_tds": ("context", "hist"),
    "passing_interceptions": ("context", "hist"),
    "passing_2pt_conversions": ("context", "hist"),
    "rushing_yards": ("context", "hist"),
    "rushing_tds": ("market_context", "hist"),
    "rushing_2pt_conversions": ("workload", "hist"),
    "receptions": ("market_context", "hist"),
    "receiving_yards": ("market_context", "hist"),
    "receiving_tds": ("market_context", "hist"),
    "receiving_2pt_conversions": ("workload", "hist"),
    "special_teams_tds": ("workload", "hist"),
    "fumbles_lost_total": ("context", "hist"),
    "fg_made_0_19": ("context", "hist"),
    "fg_made_20_29": ("context", "hist"),
    "fg_made_30_39": ("workload", "hist"),
    "fg_made_40_49": ("context", "hist"),
    "fg_made_50_59": ("context", "hist"),
    "fg_made_60_": ("context", "hist"),
    "pat_made": ("recent_mean", "recent_mean"),
}

KEYS = [
    "game_id",
    "season",
    "week",
    "player_id",
    "player_name",
    "position",
    "team",
    "opponent_team",
]


def _selected_long(
    predictions: pd.DataFrame,
    selection: dict[str, tuple[str, str]],
) -> pd.DataFrame:
    selected = []
    for target, (feature_set, model) in selection.items():
        rows = predictions[
            predictions["target"].eq(target)
            & predictions["feature_set"].eq(feature_set)
            & predictions["model"].eq(model)
        ]
        if rows.empty:
            raise ValueError(f"missing selected predictions for {target}: {feature_set}/{model}")
        selected.append(rows)
    return pd.concat(selected, ignore_index=True)


def build_fantasy_point_predictions(
    prediction_frames: list[pd.DataFrame],
    player_games: pd.DataFrame,
    *,
    selection: dict[str, tuple[str, str]] | None = None,
) -> pd.DataFrame:
    predictions = pd.concat(prediction_frames, ignore_index=True)
    chosen = selection or DEPLOYMENT_SELECTION
    fields = [field for field in scoring_fields() if field in chosen]
    selected = _selected_long(predictions, {field: chosen[field] for field in fields})
    predicted = selected.pivot(index=KEYS, columns="target", values="predicted").reset_index()
    predicted["predicted_fantasy_points"] = score_components(predicted)
    actual = player_games[KEYS + fields].drop_duplicates(KEYS).copy()
    actual["actual_fantasy_points"] = score_components(actual)
    output = actual[KEYS + ["actual_fantasy_points"]].merge(
        predicted[KEYS + ["predicted_fantasy_points"]],
        on=KEYS,
        how="inner",
        validate="one_to_one",
    )

    baseline_selection = {field: ("recent_mean", "recent_mean") for field in fields}
    baseline = _selected_long(predictions, baseline_selection).pivot(
        index=KEYS, columns="target", values="predicted"
    ).reset_index()
    baseline["baseline_fantasy_points"] = score_components(baseline)
    output = output.merge(
        baseline[KEYS + ["baseline_fantasy_points"]],
        on=KEYS,
        how="left",
        validate="one_to_one",
    )

    relevance = player_games[KEYS + ["offense_pct_ewm4", "st_snaps_ewm4"]].drop_duplicates(KEYS)
    output = output.merge(relevance, on=KEYS, how="left", validate="one_to_one")
    output["fantasy_relevant"] = (
        output["offense_pct_ewm4"].fillna(0).ge(0.25)
        | (output["position"].eq("K") & output["st_snaps_ewm4"].fillna(0).gt(0))
    )
    return output


def evaluate_fantasy_points(predictions: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = []
    for season, season_frame in predictions.groupby("season"):
        for scope, frame in (
            ("all_active_roster", season_frame),
            ("fantasy_relevant", season_frame[season_frame["fantasy_relevant"]]),
        ):
            for model, column in (
                ("component_model", "predicted_fantasy_points"),
                ("recent_mean", "baseline_fantasy_points"),
            ):
                metrics = regression_metrics(
                    frame["actual_fantasy_points"].to_numpy(),
                    frame[column].to_numpy(),
                )
                rows.append(
                    {
                        "season": int(season),
                        "scope": scope,
                        "model": model,
                        "rows": len(frame),
                        **metrics,
                    }
                )
    by_season = pd.DataFrame(rows)
    summary = by_season.groupby(["scope", "model"], as_index=False).agg(
        seasons=("season", "nunique"),
        rows=("rows", "sum"),
        mean_mae=("mae", "mean"),
        mean_rmse=("rmse", "mean"),
        mean_spearman=("spearman", "mean"),
        mean_actual_points=("actual_mean", "mean"),
        mean_predicted_points=("predicted_mean", "mean"),
    )
    return by_season, summary
