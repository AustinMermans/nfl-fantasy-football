from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError

import numpy as np
import pandas as pd

from .config import PROJECT_ROOT
from .data import RAW_DIR, STAT_COLUMNS, _download, download_nflverse, load_player_games
from .evaluation import TARGET_POSITIONS
from .fantasy import DEPLOYMENT_SELECTION, KEYS, _selected_long
from .features import build_features, feature_sets
from .injury import estimate_injury_risk_profiles
from .model import RecentMeanRegressor, build_estimator
from .preseason import fit_preseason_means
from .rest_of_season import blend_remaining_projection
from .rookies import rookie_prior_table
from .scoring import score_components, scoring_fields


CURRENT_INPUT_URLS = {
    "stats": (
        "https://github.com/nflverse/nflverse-data/releases/download/stats_player/"
        "stats_player_week_{season}.parquet"
    ),
    "snaps": (
        "https://github.com/nflverse/nflverse-data/releases/download/snap_counts/"
        "snap_counts_{season}.parquet"
    ),
    "roster": (
        "https://github.com/nflverse/nflverse-data/releases/download/weekly_rosters/"
        "roster_weekly_{season}.parquet"
    ),
    "depth": (
        "https://github.com/nflverse/nflverse-data/releases/download/depth_charts/"
        "depth_charts_{season}.parquet"
    ),
    "injury": (
        "https://github.com/nflverse/nflverse-data/releases/download/injuries/"
        "injuries_{season}.parquet"
    ),
}

DEPTH_LIMITS = {"QB": 10, "RB": 20, "FB": 10, "WR": 20, "TE": 10, "K": 5}
STARTING_DEPTH = {"QB": 1, "RB": 2, "FB": 1, "WR": 3, "TE": 1, "K": 1}


def refresh_production_inputs(
    season: int,
    *,
    first_season: int = 2012,
    refresh_current: bool = True,
) -> None:
    """Download completed history plus the current roster and depth chart."""
    download_nflverse(list(range(first_season, season)), refresh=False)
    for name, template in CURRENT_INPUT_URLS.items():
        destination_name = {
            "stats": f"stats_player_week_{season}.parquet",
            "snaps": f"snap_counts_{season}.parquet",
            "roster": f"roster_weekly_{season}.parquet",
            "depth": f"depth_charts_{season}.parquet",
            "injury": f"injuries_{season}.parquet",
        }[name]
        destination = RAW_DIR / destination_name
        if refresh_current or not destination.exists():
            try:
                _download(template.format(season=season), destination)
            except HTTPError as error:
                if name not in {"stats", "snaps", "injury"} or error.code != 404:
                    raise
                destination.unlink(missing_ok=True)
    if refresh_current:
        _download(
            "https://github.com/nflverse/nfldata/raw/master/data/games.csv",
            RAW_DIR / "games.csv",
        )
        _download(
            "https://github.com/nflverse/nflverse-data/releases/download/players/players.parquet",
            RAW_DIR / "players.parquet",
        )


def _latest_depth_chart(season: int) -> tuple[pd.DataFrame, str]:
    depth = pd.read_parquet(RAW_DIR / f"depth_charts_{season}.parquet")
    as_of = str(depth["dt"].max())
    latest = depth[depth["dt"].eq(as_of)].copy()
    latest["position"] = latest["pos_abb"].replace({"PK": "K"})
    latest = latest[latest["position"].isin(DEPTH_LIMITS)]
    latest = latest[
        latest.apply(
            lambda row: int(row["pos_rank"]) <= DEPTH_LIMITS[row["position"]],
            axis=1,
        )
    ]
    return (
        latest[
            ["team", "gsis_id", "position", "pos_slot", "pos_rank", "pos_name"]
        ].drop_duplicates(["team", "gsis_id", "position"], keep="first"),
        as_of,
    )


def current_preseason_games(season: int) -> tuple[pd.DataFrame, str]:
    """Create future player-game rows from today's active roster and depth chart."""
    rosters = pd.read_parquet(RAW_DIR / f"roster_weekly_{season}.parquet")
    rosters = rosters[
        rosters["game_type"].eq("REG")
        & rosters["status"].eq("ACT")
        & rosters["position"].isin(DEPTH_LIMITS)
        & rosters["gsis_id"].notna()
    ].drop_duplicates(["team", "gsis_id"], keep="last")
    depth, as_of = _latest_depth_chart(season)
    roster = rosters.merge(
        depth,
        on=["team", "gsis_id", "position"],
        how="inner",
        validate="one_to_one",
    )

    schedules = pd.read_csv(RAW_DIR / "games.csv", low_memory=False)
    schedule = schedules[
        schedules["season"].eq(season) & schedules["game_type"].eq("REG")
    ].copy()
    shared = [
        "game_id",
        "season",
        "week",
        "gameday",
        "home_team",
        "away_team",
        "spread_line",
        "total_line",
        "roof",
        "surface",
        "temp",
        "wind",
    ]
    home = schedule[shared + ["home_rest"]].rename(
        columns={
            "home_team": "team",
            "away_team": "opponent_team",
            "home_rest": "rest_days",
        }
    )
    home["home"] = 1.0
    away = schedule[shared + ["away_rest"]].rename(
        columns={
            "away_team": "team",
            "home_team": "opponent_team",
            "away_rest": "rest_days",
        }
    )
    away["home"] = 0.0
    team_games = pd.concat([home, away], ignore_index=True)

    roster_columns = [
        "team",
        "gsis_id",
        "pfr_id",
        "full_name",
        "position",
        "birth_date",
        "height",
        "weight",
        "years_exp",
        "rookie_year",
        "draft_number",
        "pos_slot",
        "pos_rank",
        "pos_name",
    ]
    future = roster[roster_columns].merge(
        team_games, on="team", how="inner", validate="many_to_many"
    ).rename(
        columns={
            "gsis_id": "player_id",
            "full_name": "player_name",
            "rookie_year": "draft_year",
            "draft_number": "draft_pick",
            "pos_rank": "depth_rank",
            "pos_slot": "depth_slot",
        }
    )
    future["pfr_player_id"] = future["pfr_id"]
    for column in ("offense_snaps", "offense_pct", "defense_snaps", "st_snaps", "played"):
        future[column] = 0.0
    for column in STAT_COLUMNS:
        future[column] = 0.0
    injury_columns = (
        "report_primary_injury",
        "report_secondary_injury",
        "report_status",
        "practice_primary_injury",
        "practice_secondary_injury",
        "practice_status",
    )
    injury_path = RAW_DIR / f"injuries_{season}.parquet"
    future["current_injury_feed"] = False
    if injury_path.exists():
        injuries = pd.read_parquet(injury_path)

        def first_non_null(values: pd.Series):
            non_null = values.dropna()
            return non_null.iloc[-1] if not non_null.empty else None

        injury_week = (
            injuries[injuries["game_type"].eq("REG")]
            .groupby(["season", "week", "team", "gsis_id"], as_index=False)[
                list(injury_columns)
            ]
            .agg(first_non_null)
            .rename(columns={"gsis_id": "player_id"})
        )
        future = future.merge(
            injury_week,
            on=["season", "week", "team", "player_id"],
            how="left",
            validate="many_to_one",
        )
        future["current_injury_feed"] = bool(
            injury_week[list(injury_columns)].notna().any().any()
        )
    else:
        for column in injury_columns:
            future[column] = None
    has_injury_report = future[list(injury_columns)].notna().any(axis=1)
    future["report_week"] = future["week"].where(has_injury_report)
    future["gameday"] = pd.to_datetime(future["gameday"], errors="coerce")
    future["birth_date"] = pd.to_datetime(future["birth_date"], errors="coerce")
    future["draft_year"] = pd.to_numeric(future["draft_year"], errors="coerce")
    future["draft_pick"] = pd.to_numeric(future["draft_pick"], errors="coerce")
    future["years_exp"] = pd.to_numeric(future["years_exp"], errors="coerce")
    future["age"] = (future["gameday"] - future["birth_date"]).dt.days / 365.25
    future["years_since_draft"] = season - future["draft_year"]
    return future.sort_values(["week", "game_id", "player_id"]), as_of


def completed_regular_games(season: int) -> pd.DataFrame:
    """Return games with published final scores, including partial NFL weeks."""
    schedules = pd.read_csv(RAW_DIR / "games.csv", low_memory=False)
    completed = schedules[
        schedules["season"].eq(season)
        & schedules["game_type"].eq("REG")
        & schedules["home_score"].notna()
        & schedules["away_score"].notna()
    ][["game_id", "week", "gameday"]].copy()
    return completed.sort_values(["week", "gameday", "game_id"])


def current_season_history(season: int, completed: pd.DataFrame) -> pd.DataFrame:
    required = (
        RAW_DIR / f"stats_player_week_{season}.parquet",
        RAW_DIR / f"snap_counts_{season}.parquet",
        RAW_DIR / f"roster_weekly_{season}.parquet",
    )
    if completed.empty or not all(path.exists() for path in required):
        return pd.DataFrame()
    current = load_player_games([season])
    return current[current["game_id"].isin(set(completed["game_id"]))].copy()


def observed_completed_games(
    score_complete: pd.DataFrame, current_history: pd.DataFrame
) -> pd.DataFrame:
    """Keep final games only after their player stats and snaps are available."""
    if current_history.empty or "game_id" not in current_history:
        return score_complete.iloc[0:0].copy()
    observed_game_ids = set(current_history["game_id"].dropna().unique())
    return score_complete[score_complete["game_id"].isin(observed_game_ids)].copy()


def preseason_feature_snapshots(
    history: pd.DataFrame, future: pd.DataFrame
) -> pd.DataFrame:
    """Build each future week independently so unplayed games never become history."""
    snapshots = []
    season = int(future["season"].iloc[0])
    for _, week_rows in future.groupby("week", sort=True):
        combined = pd.concat([history, week_rows], ignore_index=True, sort=False)
        featured = build_features(combined)
        snapshots.append(featured[featured["season"].eq(season)])
    return pd.concat(snapshots, ignore_index=True).sort_values(
        ["week", "game_id", "player_id"]
    )


def component_forecasts(
    history_features: pd.DataFrame,
    future_features: pd.DataFrame,
    *,
    seed: int = 20260830,
    min_player_games: int = 2,
) -> pd.DataFrame:
    outputs = []
    for target, selected_spec in DEPLOYMENT_SELECTION.items():
        positions = TARGET_POSITIONS[target]
        train = history_features[
            history_features["position"].isin(positions)
            & history_features["player_games_prior"].ge(min_player_games)
        ]
        test = future_features[future_features["position"].isin(positions)]
        specifications = [selected_spec]
        if selected_spec != ("recent_mean", "recent_mean"):
            specifications.append(("recent_mean", "recent_mean"))
        for feature_set, model_name in specifications:
            columns = feature_sets(target)[feature_set]
            if model_name == "recent_mean":
                estimator = RecentMeanRegressor(columns[0]).fit(
                    train[columns], train[target]
                )
            else:
                estimator = build_estimator(
                    model_name,
                    seed=seed,
                    nonnegative_target=bool(train[target].min() >= 0),
                )
                try:
                    estimator.fit(train[columns], train[target])
                except ValueError as error:
                    raise ValueError(
                        f"failed production fit for {target}: {feature_set}/{model_name}; "
                        f"rows={len(train)}, target_sum={train[target].sum()}"
                    ) from error
            predicted = np.clip(estimator.predict(test[columns]), 1e-6, None)
            output = test[KEYS].copy()
            output["target"] = target
            output["feature_set"] = feature_set
            output["model"] = model_name
            output["actual"] = np.nan
            output["predicted"] = predicted
            outputs.append(output)
    return pd.concat(outputs, ignore_index=True)


def fantasy_forecasts(
    components: pd.DataFrame, future_features: pd.DataFrame
) -> pd.DataFrame:
    fields = [field for field in scoring_fields() if field in DEPLOYMENT_SELECTION]
    selected = _selected_long(
        components, {field: DEPLOYMENT_SELECTION[field] for field in fields}
    )
    predicted = selected.pivot(index=KEYS, columns="target", values="predicted").reset_index()
    predicted["predicted_fantasy_points"] = score_components(predicted)
    baseline = _selected_long(
        components, {field: ("recent_mean", "recent_mean") for field in fields}
    ).pivot(index=KEYS, columns="target", values="predicted").reset_index()
    baseline["baseline_fantasy_points"] = score_components(baseline)
    output = predicted[KEYS + ["predicted_fantasy_points"]].merge(
        baseline[KEYS + ["baseline_fantasy_points"]], on=KEYS, validate="one_to_one"
    )
    output["actual_fantasy_points"] = 0.0
    output["fantasy_relevant"] = True
    return output


def apply_point_calibration(
    fantasy: pd.DataFrame, role_audit: pd.DataFrame
) -> pd.DataFrame:
    """Calibrate fantasy-point means without changing the underlying stat line."""
    scale = role_audit.set_index("player_id")["point_calibration_scale"]
    output = fantasy.copy()
    output["predicted_fantasy_points"] *= output["player_id"].map(scale).fillna(1.0)
    return output


def veteran_reserve_cap_mask(adjustments: pd.DataFrame) -> pd.Series:
    """Identify experienced reserves whose blended mean exceeds their role prior."""
    reserve = adjustments.apply(
        lambda row: row["depth_rank"] > STARTING_DEPTH[row["position"]], axis=1
    )
    return (
        ~adjustments["is_rookie"]
        & reserve
        & adjustments["adjusted_points"].gt(adjustments["role_prior_points"])
    )


def apply_current_role_adjustments(
    components: pd.DataFrame,
    future_features: pd.DataFrame,
    history: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Apply empirical rookie priors and cap stale-history reserve forecasts."""
    preliminary = fantasy_forecasts(components, future_features)
    totals = preliminary.groupby(
        ["player_id", "player_name", "position", "team"], as_index=False
    ).agg(
        predicted_fantasy_points=("predicted_fantasy_points", "sum"),
        future_games=("game_id", "nunique"),
    )
    roles = (
        future_features.sort_values(["player_id", "week"])
        .groupby("player_id", as_index=False)
        .first()[
            [
                "player_id",
                "depth_rank",
                "player_games_prior",
                "draft_pick",
                "draft_year",
                "years_exp",
                "season",
                "age",
            ]
        ]
    )
    roles["is_rookie"] = roles["draft_year"].eq(roles["season"]) | roles[
        "years_exp"
    ].eq(0)
    season = int(roles["season"].iloc[0])
    current_played = (
        history[
            history["season"].eq(season)
            & history["played"].fillna(0).gt(0)
        ]
        .groupby("player_id")["game_id"]
        .nunique()
    )
    roles["current_games_played"] = roles["player_id"].map(current_played).fillna(0.0)
    full_season_equivalent = totals.copy()
    full_season_equivalent["predicted_fantasy_points"] *= (
        17.0 / full_season_equivalent["future_games"].clip(lower=1)
    )
    rookie_priors = rookie_prior_table(
        history[history["season"].lt(season)], full_season_equivalent, roles
    )
    preseason_means = fit_preseason_means(
        history, future_features, season=season
    )
    totals = totals.merge(roles, on="player_id", validate="one_to_one")
    experienced = totals[totals["player_games_prior"].gt(0)]
    role_prior = experienced.groupby(
        ["position", "depth_rank"], as_index=False
    )["predicted_fantasy_points"].median().rename(
        columns={"predicted_fantasy_points": "role_prior_points"}
    )
    position_prior = experienced.groupby("position")[
        "predicted_fantasy_points"
    ].median()
    adjustments = totals.merge(
        role_prior, on=["position", "depth_rank"], how="left"
    ).merge(rookie_priors, on="player_id", how="left").merge(
        preseason_means, on="player_id", how="left"
    )
    adjustments["role_prior_points"] = adjustments["role_prior_points"].fillna(
        adjustments["position"].map(position_prior)
    )
    rookie = adjustments["is_rookie"]
    adjustments["adjusted_points"] = adjustments["predicted_fantasy_points"]
    adjustments["preseason_projection"] = adjustments["preseason_mean"]
    adjustments["preseason_projection_source"] = "season ensemble"
    veteran_fallback = ~rookie & adjustments["preseason_projection"].isna()
    adjustments.loc[veteran_fallback, "preseason_projection"] = adjustments.loc[
        veteran_fallback, "role_prior_points"
    ]
    adjustments.loc[veteran_fallback, "preseason_projection_source"] = (
        "current role-prior fallback"
    )
    adjustments.loc[rookie, "preseason_projection"] = adjustments.loc[
        rookie, "rookie_prior_mean"
    ].fillna(adjustments.loc[rookie, "role_prior_points"])
    adjustments.loc[rookie, "preseason_projection_source"] = "rookie analog prior"
    shrinkage = adjustments["preseason_projection"].notna()
    blended = adjustments.loc[shrinkage].apply(
        lambda row: blend_remaining_projection(
            row["preseason_projection"],
            row["predicted_fantasy_points"],
            remaining_games=int(row["future_games"]),
            games_played=float(row["current_games_played"]),
            position=str(row["position"]),
        ),
        axis=1,
    )
    adjustments.loc[shrinkage, "adjusted_points"] = blended.map(lambda value: value[0])
    adjustments["inseason_component_weight"] = 1.0
    adjustments.loc[shrinkage, "inseason_component_weight"] = blended.map(
        lambda value: value[1]
    )
    adjustments["adjustment_reason"] = "none"
    adjustments.loc[shrinkage & ~rookie, "adjustment_reason"] = (
        "preseason/in-season empirical-Bayes blend"
    )
    adjustments.loc[rookie, "adjustment_reason"] = "rookie prior/in-season blend"
    reserve_cap = veteran_reserve_cap_mask(adjustments)
    adjustments.loc[reserve_cap, "adjusted_points"] = adjustments.loc[
        reserve_cap, "role_prior_points"
    ]
    adjustments.loc[reserve_cap, "adjustment_reason"] = "reserve-role cap"
    adjustments["point_calibration_scale"] = (
        adjustments["adjusted_points"]
        / adjustments["predicted_fantasy_points"].clip(lower=1.0)
    )
    adjustments["role_scale"] = adjustments["point_calibration_scale"]
    audit = adjustments[
        [
            "player_id",
            "player_name",
            "position",
            "team",
            "depth_rank",
            "predicted_fantasy_points",
            "role_prior_points",
            "adjusted_points",
            "preseason_mean",
            "preseason_projection",
            "preseason_projection_source",
            "future_games",
            "current_games_played",
            "inseason_component_weight",
            "point_calibration_scale",
            "role_scale",
            "adjustment_reason",
            "rookie_p10",
            "rookie_p50",
            "rookie_p90",
            "rookie_cohort_effective_n",
            "rookie_draft_pick",
            "rookie_role_center",
        ]
    ].sort_values(["position", "depth_rank", "player_name"])
    return components.copy(), audit


def build_preseason_forecasts(
    season: int,
    *,
    refresh: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, str]:
    fantasy, components, features, as_of, _, _ = build_season_forecasts(
        season, refresh=refresh
    )
    return fantasy, components, features, as_of


def build_season_forecasts(
    season: int,
    *,
    refresh: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, str, pd.DataFrame, int]:
    if refresh:
        refresh_production_inputs(season)
    prior_history = load_player_games(list(range(2012, season)))
    score_complete = completed_regular_games(season)
    current_history = current_season_history(season, score_complete)
    completed = observed_completed_games(score_complete, current_history)
    history = pd.concat(
        [prior_history, current_history], ignore_index=True, sort=False
    ) if not current_history.empty else prior_history
    future, as_of = current_preseason_games(season)
    if not completed.empty:
        future = future[~future["game_id"].isin(set(completed["game_id"]))].copy()
    if future.empty:
        raise ValueError(f"no unplayed regular-season games remain for {season}")
    history_features = build_features(history)
    future_features = preseason_feature_snapshots(history, future)
    injury_profiles = estimate_injury_risk_profiles(history, future)
    injury_profiles.to_csv(
        PROJECT_ROOT / "results" / "current_injury_risk_profiles.csv", index=False
    )
    injury_profiles = injury_profiles.set_index("player_id")
    for column in injury_profiles.columns:
        future_features[column] = future_features["player_id"].map(
            injury_profiles[column]
        )
    components = component_forecasts(history_features, future_features)
    components, role_audit = apply_current_role_adjustments(
        components, future_features, history
    )
    adjustment_reason = role_audit.set_index("player_id")["adjustment_reason"]
    future_features["role_adjustment"] = future_features["player_id"].map(
        adjustment_reason
    ).fillna("none")
    for column in (
        "rookie_p10",
        "rookie_p50",
        "rookie_p90",
        "rookie_cohort_effective_n",
    ):
        values = role_audit.set_index("player_id")[column]
        future_features[column] = future_features["player_id"].map(values)
    for column in (
        "preseason_projection",
        "preseason_projection_source",
        "current_games_played",
        "future_games",
        "inseason_component_weight",
    ):
        values = role_audit.set_index("player_id")[column]
        future_features[column] = future_features["player_id"].map(values)
    fantasy = fantasy_forecasts(components, future_features)
    fantasy = apply_point_calibration(fantasy, role_audit)
    role_audit.to_csv(
        PROJECT_ROOT / "results" / "current_role_adjustments.csv", index=False
    )
    completed_week = int(completed["week"].max()) if not completed.empty else 0
    return fantasy, components, future_features, as_of, current_history, completed_week


def write_production_artifacts(
    fantasy: pd.DataFrame,
    components: pd.DataFrame,
    future_features: pd.DataFrame,
    *,
    results_dir: Path | None = None,
) -> None:
    results = results_dir or PROJECT_ROOT / "results"
    results.mkdir(parents=True, exist_ok=True)
    fantasy.to_parquet(results / "current_fantasy_forecasts.parquet", index=False)
    components.to_parquet(results / "current_component_forecasts.parquet", index=False)
    future_features.to_parquet(results / "current_feature_snapshots.parquet", index=False)
    (results / "current_forecast_generated_at.txt").write_text(
        datetime.now(UTC).isoformat() + "\n", encoding="utf-8"
    )
