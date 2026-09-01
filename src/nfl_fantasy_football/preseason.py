from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .scoring import score_components


DEFAULT_COMPONENT_WEIGHT = 0.25
COMPONENT_WEIGHT_BY_POSITION = {
    "QB": 0.0,
    "RB": DEFAULT_COMPONENT_WEIGHT,
    "WR": DEFAULT_COMPONENT_WEIGHT,
    "TE": DEFAULT_COMPONENT_WEIGHT,
    "K": DEFAULT_COMPONENT_WEIGHT,
}
MIN_PRIOR_POINTS = 20.0
SEASON_FEATURES = (
    "prior_points",
    "prior2_points",
    "prior_points_per_game",
    "prior2_points_per_game",
    "prior_games",
    "prior2_games",
    "prior_played",
    "prior2_played",
    "prior_offense_pct",
    "prior2_offense_pct",
    "age",
    "years_exp",
    "draft_pick",
    "career_seasons",
)


def season_player_panel(history: pd.DataFrame) -> pd.DataFrame:
    """Aggregate player seasons and attach exact prior-season predictors."""
    frame = history.copy()
    frame["fantasy_points"] = score_components(frame)
    frame["played_game"] = (
        frame["offense_snaps"].fillna(0).gt(0)
        | frame["st_snaps"].fillna(0).gt(0)
    ).astype(float)
    panel = frame.groupby(["season", "player_id"], as_index=False).agg(
        player_name=("player_name", "last"),
        position=("position", "last"),
        team=("team", "last"),
        age=("age", "first"),
        years_exp=("years_exp", "first"),
        draft_pick=("draft_pick", "first"),
        points=("fantasy_points", "sum"),
        games=("game_id", "nunique"),
        played=("played_game", "sum"),
        offense_pct=("offense_pct", "mean"),
    )
    base = panel.copy()
    for lag, prefix in ((1, "prior"), (2, "prior2")):
        previous = base[
            ["season", "player_id", "points", "games", "played", "offense_pct"]
        ].copy()
        previous["season"] += lag
        previous = previous.rename(
            columns={
                "points": f"{prefix}_points",
                "games": f"{prefix}_games",
                "played": f"{prefix}_played",
                "offense_pct": f"{prefix}_offense_pct",
            }
        )
        panel = panel.merge(previous, on=["season", "player_id"], how="left")
    panel["prior_points_per_game"] = panel["prior_points"] / panel[
        "prior_games"
    ].clip(lower=1)
    panel["prior2_points_per_game"] = panel["prior2_points"] / panel[
        "prior2_games"
    ].clip(lower=1)
    panel["career_seasons"] = panel.groupby("player_id").cumcount().astype(float)
    return panel.sort_values(["season", "player_id"]).reset_index(drop=True)


def current_preseason_rows(
    panel: pd.DataFrame,
    current_roles: pd.DataFrame,
    *,
    season: int,
) -> pd.DataFrame:
    """Create one point-in-time player row using only completed seasons."""
    columns = [
        "player_id",
        "player_name",
        "position",
        "team",
        "age",
        "years_exp",
        "draft_pick",
    ]
    current = (
        current_roles.sort_values(["player_id", "week"])
        .groupby("player_id", as_index=False)
        .first()[columns]
    )
    current["season"] = season
    for lag, prefix in ((1, "prior"), (2, "prior2")):
        previous = panel[panel["season"].eq(season - lag)][
            ["player_id", "points", "games", "played", "offense_pct"]
        ].rename(
            columns={
                "points": f"{prefix}_points",
                "games": f"{prefix}_games",
                "played": f"{prefix}_played",
                "offense_pct": f"{prefix}_offense_pct",
            }
        )
        current = current.merge(previous, on="player_id", how="left")
    current["prior_points_per_game"] = current["prior_points"] / current[
        "prior_games"
    ].clip(lower=1)
    current["prior2_points_per_game"] = current["prior2_points"] / current[
        "prior2_games"
    ].clip(lower=1)
    career = panel[panel["season"].lt(season)].groupby("player_id").size()
    current["career_seasons"] = current["player_id"].map(career).fillna(0.0)
    return current


def _design_matrices(
    train: pd.DataFrame, test: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    train_design = pd.get_dummies(
        train[[*SEASON_FEATURES, "position"]], columns=["position"]
    ).astype(float)
    test_design = pd.get_dummies(
        test[[*SEASON_FEATURES, "position"]], columns=["position"]
    ).reindex(columns=train_design.columns, fill_value=0).astype(float)
    return train_design, test_design


def _fit_season_ensemble(
    train: pd.DataFrame,
    test: pd.DataFrame,
    *,
    seed: int,
) -> np.ndarray:
    train_design, test_design = _design_matrices(train, test)
    ridge = make_pipeline(
        SimpleImputer(strategy="median", add_indicator=True),
        StandardScaler(),
        Ridge(alpha=100.0),
    ).fit(train_design, train["points"])
    histogram = make_pipeline(
        SimpleImputer(strategy="median", add_indicator=True),
        HistGradientBoostingRegressor(
            learning_rate=0.05,
            max_iter=100,
            max_leaf_nodes=8,
            l2_regularization=10.0,
            random_state=seed,
        ),
    ).fit(train_design, train["points"])
    return 0.6 * np.clip(ridge.predict(test_design), 0.0, None) + 0.4 * np.clip(
        histogram.predict(test_design), 0.0, None
    )


def fit_preseason_means(
    history: pd.DataFrame,
    current_roles: pd.DataFrame,
    *,
    season: int,
    seed: int = 20260830,
) -> pd.DataFrame:
    """Predict veteran season totals with a deliberately compact ensemble."""
    panel = season_player_panel(history)
    current = current_preseason_rows(panel, current_roles, season=season)
    train = panel[
        panel["season"].lt(season)
        & panel["prior_points"].ge(MIN_PRIOR_POINTS)
    ].copy()
    eligible = current["prior_points"].ge(MIN_PRIOR_POINTS)
    output = current[["player_id"]].copy()
    output["preseason_mean"] = np.nan
    if not eligible.any():
        return output

    prediction = _fit_season_ensemble(
        train, current[eligible], seed=seed
    )
    output.loc[eligible, "preseason_mean"] = prediction
    return output


def walk_forward_preseason_backtest(
    history: pd.DataFrame,
    *,
    first_test_season: int = 2018,
    last_test_season: int = 2024,
    seed: int = 20260830,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Evaluate season totals with an expanding, strictly prior-season window."""
    panel = season_player_panel(history)
    folds: list[pd.DataFrame] = []
    for season in range(first_test_season, last_test_season + 1):
        train = panel[
            panel["season"].lt(season)
            & panel["prior_points"].ge(MIN_PRIOR_POINTS)
        ].copy()
        test = panel[
            panel["season"].eq(season)
            & panel["prior_points"].ge(MIN_PRIOR_POINTS)
        ].copy()
        if train.empty or test.empty:
            continue
        fold = test[
            ["season", "player_id", "player_name", "position", "points", "prior_points"]
        ].copy()
        fold["season_ensemble"] = _fit_season_ensemble(
            train, test, seed=seed + season
        )
        top_cutoff = float(test["prior_points"].quantile(0.9))
        fold["prior_top_decile"] = fold["prior_points"].ge(top_cutoff)
        folds.append(fold)
    predictions = pd.concat(folds, ignore_index=True)

    rows: list[dict[str, object]] = []
    for season, fold in predictions.groupby("season", observed=True):
        for subgroup, mask in (
            ("all", pd.Series(True, index=fold.index)),
            ("prior_top_decile", fold["prior_top_decile"]),
        ):
            subset = fold[mask]
            for model, column in (
                ("prior_season", "prior_points"),
                ("season_ensemble", "season_ensemble"),
            ):
                error = subset[column] - subset["points"]
                rows.append(
                    {
                        "season": int(season),
                        "subgroup": subgroup,
                        "model": model,
                        "n": int(len(subset)),
                        "rmse": float(np.sqrt(np.mean(np.square(error)))),
                        "mae": float(np.mean(np.abs(error))),
                        "bias": float(np.mean(error)),
                        "spearman": float(subset[column].corr(subset["points"], method="spearman")),
                    }
                )
    by_season = pd.DataFrame(rows)
    summary = by_season.groupby(["subgroup", "model"], as_index=False).agg(
        seasons=("season", "nunique"),
        mean_n=("n", "mean"),
        mean_rmse=("rmse", "mean"),
        mean_mae=("mae", "mean"),
        mean_bias=("bias", "mean"),
        mean_spearman=("spearman", "mean"),
    )
    return predictions, by_season, summary
