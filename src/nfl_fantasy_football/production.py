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
from .rookies import rookie_prior_table
from .scoring import score_components, scoring_fields


CURRENT_INPUT_URLS = {
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
            "roster": f"roster_weekly_{season}.parquet",
            "depth": f"depth_charts_{season}.parquet",
            "injury": f"injuries_{season}.parquet",
        }[name]
        destination = RAW_DIR / destination_name
        if refresh_current or not destination.exists():
            try:
                _download(template.format(season=season), destination)
            except HTTPError as error:
                if name != "injury" or error.code != 404:
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
    future["gameday"] = pd.to_datetime(future["gameday"], errors="coerce")
    future["birth_date"] = pd.to_datetime(future["birth_date"], errors="coerce")
    future["draft_year"] = pd.to_numeric(future["draft_year"], errors="coerce")
    future["draft_pick"] = pd.to_numeric(future["draft_pick"], errors="coerce")
    future["years_exp"] = pd.to_numeric(future["years_exp"], errors="coerce")
    future["age"] = (future["gameday"] - future["birth_date"]).dt.days / 365.25
    future["years_since_draft"] = season - future["draft_year"]
    return future.sort_values(["week", "game_id", "player_id"]), as_of


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


def apply_current_role_adjustments(
    components: pd.DataFrame,
    future_features: pd.DataFrame,
    history: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Apply empirical rookie priors and cap stale-history reserve forecasts."""
    preliminary = fantasy_forecasts(components, future_features)
    totals = preliminary.groupby(
        ["player_id", "player_name", "position", "team"], as_index=False
    )["predicted_fantasy_points"].sum()
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
            ]
        ]
    )
    roles["is_rookie"] = roles["draft_year"].eq(roles["season"]) | roles[
        "years_exp"
    ].eq(0)
    rookie_priors = rookie_prior_table(history, totals, roles)
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
    ).merge(rookie_priors, on="player_id", how="left")
    adjustments["role_prior_points"] = adjustments["role_prior_points"].fillna(
        adjustments["position"].map(position_prior)
    )
    rookie = adjustments["is_rookie"]
    reserve = adjustments.apply(
        lambda row: row["depth_rank"] > STARTING_DEPTH[row["position"]], axis=1
    )
    above_role = adjustments["predicted_fantasy_points"].gt(
        adjustments["role_prior_points"]
    )
    adjustments["adjusted_points"] = adjustments["predicted_fantasy_points"]
    adjustments.loc[rookie, "adjusted_points"] = adjustments.loc[
        rookie, "rookie_prior_mean"
    ].fillna(adjustments.loc[rookie, "role_prior_points"])
    adjustments.loc[~rookie & reserve & above_role, "adjusted_points"] = adjustments.loc[
        ~rookie & reserve & above_role, "role_prior_points"
    ]
    adjustments["adjustment_reason"] = "none"
    adjustments.loc[rookie, "adjustment_reason"] = "empirical rookie prior"
    adjustments.loc[~rookie & reserve & above_role, "adjustment_reason"] = (
        "reserve-role cap"
    )
    adjustments["role_scale"] = (
        adjustments["adjusted_points"]
        / adjustments["predicted_fantasy_points"].clip(lower=1.0)
    )
    scale = adjustments.set_index("player_id")["role_scale"]
    adjusted = components.copy()
    adjusted["predicted"] = adjusted["predicted"] * adjusted["player_id"].map(
        scale
    ).fillna(1.0)
    audit = adjustments[adjustments["adjustment_reason"].ne("none")][
        [
            "player_id",
            "player_name",
            "position",
            "team",
            "depth_rank",
            "predicted_fantasy_points",
            "role_prior_points",
            "adjusted_points",
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
    return adjusted, audit


def build_preseason_forecasts(
    season: int,
    *,
    refresh: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, str]:
    if refresh:
        refresh_production_inputs(season)
    history = load_player_games(list(range(2012, season)))
    future, as_of = current_preseason_games(season)
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
    fantasy = fantasy_forecasts(components, future_features)
    role_audit.to_csv(
        PROJECT_ROOT / "results" / "current_role_adjustments.csv", index=False
    )
    return fantasy, components, future_features, as_of


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
