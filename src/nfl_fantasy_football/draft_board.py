from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from .config import PROJECT_ROOT
from .draft_probability import WEEKLY_OUTCOME_PARAMETERS, estimate_weekly_outcome_parameters
from .draft_strategy import format_draft_metrics
from .fantasy import DEPLOYMENT_SELECTION, _selected_long
from .injury import FALLBACK_DURATION, FALLBACK_HAZARD
from .rest_of_season import availability_adjusted_projection
from .scoring import load_scoring, score_components


LEAGUE_ROSTER_SLOTS = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 2, "K": 1}

DISPLAY_FIELDS = (
    "receptions",
    "passing_yards",
    "passing_tds",
    "passing_interceptions",
    "passing_2pt_conversions",
    "rushing_yards",
    "rushing_tds",
    "rushing_2pt_conversions",
    "receiving_yards",
    "receiving_tds",
    "receiving_2pt_conversions",
    "special_teams_tds",
    "fumbles_lost_total",
    "fg_made_0_19",
    "fg_made_20_29",
    "fg_made_30_39",
    "fg_made_40_49",
    "fg_made_50_59",
    "fg_made_60_",
    "pat_made",
)

POSITION_DISPLAY_FIELDS = {
    "QB": (
        "passing_yards",
        "passing_tds",
        "passing_interceptions",
        "passing_2pt_conversions",
        "rushing_yards",
        "rushing_tds",
        "rushing_2pt_conversions",
    ),
    "RB": (
        "rushing_yards",
        "rushing_tds",
        "receptions",
        "receiving_yards",
        "receiving_tds",
        "receiving_2pt_conversions",
        "fumbles_lost_total",
    ),
    "WR": (
        "receiving_yards",
        "receiving_tds",
        "receptions",
        "receiving_2pt_conversions",
        "rushing_yards",
        "rushing_tds",
        "fumbles_lost_total",
    ),
    "TE": (
        "receptions",
        "receiving_yards",
        "receiving_tds",
        "receiving_2pt_conversions",
        "fumbles_lost_total",
    ),
    "K": (
        "fg_made_0_19",
        "fg_made_20_29",
        "fg_made_30_39",
        "fg_made_40_49",
        "fg_made_50_59",
        "fg_made_60_",
        "pat_made",
    ),
}

def _number(value: object, digits: int = 1) -> float:
    return round(float(0.0 if pd.isna(value) else value), digits)


def _number_or(value: object, default: float, digits: int = 4) -> float:
    return round(float(default if pd.isna(value) else value), digits)


def _text(value: object) -> str:
    return "" if pd.isna(value) else str(value)


def _venue(game_id: str, team: str) -> str:
    home_team = str(game_id).rsplit("_", maxsplit=1)[-1]
    return "vs" if team == home_team else "at"


def build_player_rankings(
    fantasy_predictions: pd.DataFrame,
    component_predictions: pd.DataFrame,
    *,
    season: int | None = None,
    teams: int = 10,
    roster_slots: dict[str, int] | None = None,
) -> list[dict[str, object]]:
    """Aggregate one season of out-of-sample game forecasts into player rankings."""
    selected_season = int(season or fantasy_predictions["season"].max())
    fantasy = fantasy_predictions[
        fantasy_predictions["season"].eq(selected_season)
        & fantasy_predictions["fantasy_relevant"]
    ].copy()
    if fantasy.empty:
        raise ValueError(f"no fantasy-relevant predictions for {selected_season}")

    latest = (
        fantasy.sort_values(["player_id", "week"])
        .groupby("player_id", as_index=False)
        .tail(1)[["player_id", "player_name", "position", "team"]]
    )
    totals = fantasy.groupby("player_id", as_index=False).agg(
        projected_points=("predicted_fantasy_points", "sum"),
        actual_points=("actual_fantasy_points", "sum"),
        baseline_points=("baseline_fantasy_points", "sum"),
        projected_games=("game_id", "nunique"),
    )
    totals = totals.merge(latest, on="player_id", validate="one_to_one")
    totals["points_per_game"] = (
        totals["projected_points"] / totals["projected_games"]
    )
    totals["actual_points_per_game"] = (
        totals["actual_points"] / totals["projected_games"]
    )
    totals["model_lift"] = totals["projected_points"] - totals["baseline_points"]

    available = {
        target: selection
        for target, selection in DEPLOYMENT_SELECTION.items()
        if target in DISPLAY_FIELDS
        and target in set(component_predictions["target"].unique())
    }
    selected = _selected_long(component_predictions, available)
    selected = selected[selected["season"].eq(selected_season)]
    components = selected.pivot_table(
        index="player_id", columns="target", values="predicted", aggfunc="sum"
    ).reset_index()
    totals = totals.merge(components, on="player_id", how="left")
    game_components = selected.pivot_table(
        index=["player_id", "game_id"],
        columns="target",
        values="predicted",
        aggfunc="first",
    ).reset_index()
    game_predictions = fantasy.merge(
        game_components, on=["player_id", "game_id"], how="left"
    ).sort_values(["player_id", "week"])
    games_by_player = {
        player_id: player_games
        for player_id, player_games in game_predictions.groupby("player_id")
    }

    totals = totals.sort_values(
        ["projected_points", "points_per_game", "player_name"],
        ascending=[False, False, True],
    ).reset_index(drop=True)
    totals["overall_rank"] = totals.index + 1
    totals["actual_rank"] = (
        totals["actual_points"].rank(method="first", ascending=False).astype(int)
    )
    totals["position_rank"] = (
        totals.groupby("position")["projected_points"]
        .rank(method="first", ascending=False)
        .astype(int)
    )
    totals["actual_position_rank"] = (
        totals.groupby("position")["actual_points"]
        .rank(method="first", ascending=False)
        .astype(int)
    )
    (
        totals["replacement_points"],
        totals["draft_value"],
        totals["draft_rank"],
    ) = format_draft_metrics(
        totals,
        "projected_points",
        teams=teams,
        roster_slots=roster_slots or LEAGUE_ROSTER_SLOTS,
    )
    totals["value_over_replacement"] = totals["draft_value"]
    (
        totals["actual_replacement_points"],
        totals["actual_draft_value"],
        totals["actual_draft_rank"],
    ) = format_draft_metrics(
        totals,
        "actual_points",
        teams=teams,
        roster_slots=roster_slots or LEAGUE_ROSTER_SLOTS,
    )
    totals["actual_value_over_replacement"] = totals["actual_draft_value"]

    rows: list[dict[str, object]] = []
    for row in totals.itertuples(index=False):
        stats = {
            field: _number(getattr(row, field, 0.0)) for field in DISPLAY_FIELDS
        }
        game_rows = []
        for game in games_by_player[row.player_id].itertuples(index=False):
            game_stats = {
                field: _number(getattr(game, field, 0.0))
                for field in POSITION_DISPLAY_FIELDS.get(row.position, ())
            }
            game_rows.append(
                {
                    "week": int(game.week),
                    "gameId": game.game_id,
                    "team": game.team,
                    "opponent": game.opponent_team,
                    "venue": _venue(game.game_id, game.team),
                    "projectedPoints": _number(game.predicted_fantasy_points, 2),
                    "actualPoints": _number(game.actual_fantasy_points, 2),
                    "baselinePoints": _number(game.baseline_fantasy_points, 2),
                    "stats": game_stats,
                }
            )
        rows.append(
            {
                "id": row.player_id,
                "name": row.player_name,
                "position": row.position,
                "team": row.team,
                "rank": int(row.overall_rank),
                "positionRank": int(row.position_rank),
                "actualPositionRank": int(row.actual_position_rank),
                "projectedPoints": round(float(row.projected_points), 1),
                "actualPoints": round(float(row.actual_points), 1),
                "pointsPerGame": round(float(row.points_per_game), 2),
                "actualPointsPerGame": round(float(row.actual_points_per_game), 2),
                "projectedGames": int(row.projected_games),
                "modelLift": round(float(row.model_lift), 1),
                "draftRank": int(row.draft_rank),
                "actualDraftRank": int(row.actual_draft_rank),
                "actualRank": int(row.actual_rank),
                "draftValue": _number(row.draft_value),
                "actualDraftValue": _number(row.actual_draft_value),
                "valueOverReplacement": _number(row.value_over_replacement),
                "actualValueOverReplacement": _number(
                    row.actual_value_over_replacement
                ),
                "replacementPoints": _number(row.replacement_points),
                "actualReplacementPoints": _number(row.actual_replacement_points),
                "stats": stats,
                "games": game_rows,
            }
        )
    return rows


def export_draft_board(
    *,
    results_dir: Path | None = None,
    web_dir: Path | None = None,
    season: int | None = None,
) -> Path:
    results = results_dir or PROJECT_ROOT / "results"
    destination_dir = web_dir or PROJECT_ROOT / "web"
    fantasy = pd.read_parquet(results / "fantasy_point_predictions.parquet")
    component_predictions = pd.concat(
        [
            pd.read_parquet(results / "development_predictions.parquet"),
            pd.read_parquet(results / "expanded_predictions.parquet"),
        ],
        ignore_index=True,
    )
    selected_season = int(season or fantasy["season"].max())
    payload = {
        "generatedAt": datetime.now(UTC).isoformat(),
        "projectionSeason": selected_season,
        "scoring": "Murphs house half-PPR",
        "scope": "Out-of-sample development ranking",
        "draftFormat": "10-team · 1 QB · 2 RB · 2 WR · 1 TE · 2 FLEX · 1 K · 8 bench",
        "draftMethod": "Weekly managed-lineup value with bench, bye, and outcome uncertainty",
        "draftConfig": {
            "teams": 10,
            "draftSlot": 10,
            "rosterSlots": LEAGUE_ROSTER_SLOTS,
            "rosterMaximums": {"QB": 4, "RB": 8, "WR": 8, "TE": 3, "K": 3},
            "benchSlots": 8,
            "rounds": 17,
            "objective": "expected managed weekly lineup points",
        },
        "benchModel": {
            "weeks": 18,
            "simulations": 16,
            "parametersByPosition": estimate_weekly_outcome_parameters(fantasy),
            "source": "2018-2024 expanding-window out-of-sample residuals",
            "replacementPolicy": "weekly position-level waiver fill",
        },
        "players": build_player_rankings(
            fantasy, component_predictions, season=selected_season
        ),
    }
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / "projections.js"
    destination.write_text(
        "window.NFL_DRAFT_DATA = "
        + json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
        + ";\n",
        encoding="utf-8",
    )
    return destination


def export_preseason_board(
    fantasy: pd.DataFrame,
    components: pd.DataFrame,
    future_features: pd.DataFrame,
    *,
    season: int,
    data_as_of: str,
    web_dir: Path | None = None,
    actual_history: pd.DataFrame | None = None,
    completed_week: int = 0,
) -> Path:
    """Publish the draft board plus point-in-time rest-of-season values."""
    destination_dir = web_dir or PROJECT_ROOT / "web"
    destination = destination_dir / "projections.js"
    previous_draft_points: dict[str, float] = {}
    if completed_week and destination.exists():
        raw = destination.read_text(encoding="utf-8").strip()
        prefix = "window.NFL_DRAFT_DATA = "
        if raw.startswith(prefix):
            previous = json.loads(raw[len(prefix):].removesuffix(";"))
            previous_draft_points = {
                str(player["id"]): float(
                    player.get("draftProjectedPoints", player["projectedPoints"])
                )
                for player in previous.get("players", [])
            }
    players = build_player_rankings(fantasy, components, season=season)
    profile_columns = [
        "injury_weekly_hazard",
        "injury_mean_duration",
        "injury_expected_missed_games",
        "injury_baseline_hazard",
        "injury_history_episodes",
        "injury_history_missed_games",
        "injury_size_multiplier",
        "height",
        "weight",
        "bmi",
    ]
    depth_columns = [
        "player_id",
        "depth_rank",
        "depth_slot",
        "pos_name",
        "role_adjustment",
        "rookie_p10",
        "rookie_p50",
        "rookie_p90",
        "rookie_cohort_effective_n",
        "current_injury_feed",
        "preseason_projection",
        "current_games_played",
        "future_games",
        "inseason_component_weight",
        "report_primary_injury",
        "report_status",
        "practice_status",
        *[column for column in profile_columns if column in future_features],
    ]
    depth = (
        future_features.sort_values(["player_id", "week"])
        .groupby("player_id", as_index=False)
        .first()[depth_columns]
        .set_index("player_id")
        .to_dict("index")
    )
    actual_frame = (
        actual_history.copy()
        if actual_history is not None and not actual_history.empty
        else pd.DataFrame()
    )
    actual_summary: dict[str, dict[str, float]] = {}
    actual_games: dict[str, pd.DataFrame] = {}
    if not actual_frame.empty:
        actual_frame["actual_fantasy_points"] = score_components(actual_frame)
        summary = actual_frame.groupby("player_id", as_index=False).agg(
            actual_points=("actual_fantasy_points", "sum"),
            completed_games=("game_id", "nunique"),
            games_played=("played", "sum"),
        )
        actual_summary = summary.set_index("player_id").to_dict("index")
        actual_games = {
            player_id: games.sort_values(["week", "gameday", "game_id"])
            for player_id, games in actual_frame.groupby("player_id")
        }
    for player in players:
        role = depth.get(player["id"], {})
        player["depthRank"] = int(_number(role.get("depth_rank"), 0))
        player["depthSlot"] = int(_number(role.get("depth_slot"), 0))
        player["depthRole"] = _text(role.get("pos_name"))
        player["projectionNote"] = _text(role.get("role_adjustment")) or "none"
        player["draftProjectedPoints"] = round(
            previous_draft_points.get(player["id"], player["projectedPoints"]), 1
        )
        player["inseasonGames"] = int(
            _number(role.get("current_games_played"), 0)
        )
        player["inseasonComponentWeight"] = _number_or(
            role.get("inseason_component_weight"), 0.0
        )
        rookie_range = pd.notna(role.get("rookie_p50"))
        player["projectionRange"] = {
            "p10": _number(role.get("rookie_p10")) if rookie_range else player["projectedPoints"],
            "p50": _number(role.get("rookie_p50")) if rookie_range else player["projectedPoints"],
            "p90": _number(role.get("rookie_p90")) if rookie_range else player["projectedPoints"],
            "source": "historical rookie analogs"
            if pd.notna(role.get("rookie_p50"))
            else "point forecast",
            "effectiveSample": _number(role.get("rookie_cohort_effective_n", 0.0)),
        }
        player["injury"] = {
            "bodyPart": _text(role.get("report_primary_injury")),
            "gameStatus": _text(role.get("report_status")),
            "practiceStatus": _text(role.get("practice_status")),
        }
        position = player["position"]
        player["injuryRisk"] = {
            "weeklyHazard": _number_or(
                role.get("injury_weekly_hazard"), FALLBACK_HAZARD[position]
            ),
            "meanDuration": _number_or(
                role.get("injury_mean_duration"), FALLBACK_DURATION[position]
            ),
            "expectedMissedGames": _number_or(
                role.get("injury_expected_missed_games"),
                17 * FALLBACK_HAZARD[position] * FALLBACK_DURATION[position],
            ),
            "baselineHazard": _number_or(
                role.get("injury_baseline_hazard"), FALLBACK_HAZARD[position]
            ),
            "historyEpisodes": int(_number(role.get("injury_history_episodes"), 0)),
            "historyMissedGames": int(
                _number(role.get("injury_history_missed_games"), 0)
            ),
            "sizeMultiplier": _number_or(role.get("injury_size_multiplier"), 1.0),
            "height": _number_or(role.get("height"), 0.0, 1),
            "weight": _number_or(role.get("weight"), 0.0, 1),
            "bmi": _number_or(role.get("bmi"), 0.0, 1),
        }
        expected_points, expected_games, expected_missed = availability_adjusted_projection(
            player["projectedPoints"],
            remaining_games=player["projectedGames"],
            weekly_hazard=player["injuryRisk"]["weeklyHazard"],
            mean_duration=player["injuryRisk"]["meanDuration"],
            current_status=player["injury"]["gameStatus"],
        )
        player["injuryRisk"]["fullSeasonExpectedMissedGames"] = player[
            "injuryRisk"
        ]["expectedMissedGames"]
        player["injuryRisk"]["expectedMissedGames"] = round(expected_missed, 2)
        player["restOfSeasonPoints"] = player["projectedPoints"]
        player["restOfSeasonExpectedPoints"] = round(expected_points, 1)
        player["restOfSeasonExpectedGames"] = round(expected_games, 2)
        range_scale = expected_points / max(player["draftProjectedPoints"], 1e-9)
        player["restOfSeasonRange"] = {
            "p10": round(player["projectionRange"]["p10"] * range_scale, 1),
            "p50": round(player["projectionRange"]["p50"] * range_scale, 1),
            "p90": round(player["projectionRange"]["p90"] * range_scale, 1),
            "source": player["projectionRange"]["source"],
            "effectiveSample": player["projectionRange"]["effectiveSample"],
        }
        actual = actual_summary.get(player["id"], {})
        player["actualPoints"] = _number(actual.get("actual_points", 0.0))
        player["completedGames"] = int(_number(actual.get("completed_games", 0)))
        player["gamesPlayed"] = int(_number(actual.get("games_played", 0)))
        player["actualPointsPerGame"] = round(
            player["actualPoints"] / max(player["gamesPlayed"], 1), 2
        )
        player["projectedFinish"] = round(
            player["actualPoints"] + player["restOfSeasonExpectedPoints"], 1
        )
        completed_rows = []
        for game in actual_games.get(player["id"], pd.DataFrame()).itertuples(index=False):
            completed_rows.append(
                {
                    "week": int(game.week),
                    "gameId": game.game_id,
                    "team": game.team,
                    "opponent": game.opponent_team,
                    "venue": _venue(game.game_id, game.team),
                    "projectedPoints": 0.0,
                    "actualPoints": _number(game.actual_fantasy_points, 2),
                    "baselinePoints": 0.0,
                    "completed": True,
                    "stats": {
                        field: _number(getattr(game, field, 0.0))
                        for field in POSITION_DISPLAY_FIELDS.get(player["position"], ())
                    },
                }
            )
        player["games"] = completed_rows + [
            {**game, "completed": False} for game in player["games"]
        ]

    ros_frame = pd.DataFrame(
        [
            {
                "player_id": player["id"],
                "player_name": player["name"],
                "position": player["position"],
                "rest_of_season_expected_points": player[
                    "restOfSeasonExpectedPoints"
                ],
            }
            for player in players
        ]
    )
    replacement, value, ros_rank = format_draft_metrics(
        ros_frame,
        "rest_of_season_expected_points",
        teams=10,
        roster_slots=LEAGUE_ROSTER_SLOTS,
    )
    ros_frame["replacement"] = replacement
    ros_frame["value"] = value
    ros_frame["ros_rank"] = ros_rank
    ros_frame["points_rank"] = ros_frame["rest_of_season_expected_points"].rank(
        method="first", ascending=False
    ).astype(int)
    ros_metrics = ros_frame.set_index("player_id").to_dict("index")
    finish_rank = {
        player["id"]: rank
        for rank, player in enumerate(
            sorted(players, key=lambda item: (-item["projectedFinish"], item["name"])),
            start=1,
        )
    }
    actual_rank = {
        player["id"]: rank
        for rank, player in enumerate(
            sorted(players, key=lambda item: (-item["actualPoints"], item["name"])),
            start=1,
        )
    }
    actual_position_rank: dict[str, int] = {}
    for position in {player["position"] for player in players}:
        ordered = sorted(
            (player for player in players if player["position"] == position),
            key=lambda item: (-item["actualPoints"], item["name"]),
        )
        actual_position_rank.update(
            {player["id"]: rank for rank, player in enumerate(ordered, start=1)}
        )
    for player in players:
        metric = ros_metrics[player["id"]]
        player["restOfSeasonRank"] = int(metric["ros_rank"])
        player["restOfSeasonPointsRank"] = int(metric["points_rank"])
        player["restOfSeasonReplacementPoints"] = _number(metric["replacement"])
        player["restOfSeasonValueOverReplacement"] = _number(metric["value"])
        player["projectedFinishRank"] = int(finish_rank[player["id"]])
        player["actualRank"] = int(actual_rank[player["id"]])
        player["actualPositionRank"] = int(actual_position_rank[player["id"]])
    injury_available = bool(future_features["current_injury_feed"].any())
    prediction_path = PROJECT_ROOT / "results" / "fantasy_point_predictions.parquet"
    outcome_parameters = (
        estimate_weekly_outcome_parameters(pd.read_parquet(prediction_path))
        if prediction_path.exists()
        else WEEKLY_OUTCOME_PARAMETERS
    )
    payload = {
        "generatedAt": datetime.now(UTC).isoformat(),
        "dataAsOf": data_as_of,
        "trainingThrough": season - 1,
        "projectionSeason": season,
        "forecastType": "rest_of_season" if completed_week else "preseason",
        "hasActuals": bool(actual_summary),
        "completedWeek": completed_week,
        "remainingWeeks": sorted(
            int(week) for week in future_features["week"].unique()
        ),
        "scoring": "Murphs house half-PPR",
        "scoringWeights": load_scoring(),
        "scope": (
            f"{season} rest-of-season forecast after Week {completed_week}"
            if completed_week
            else f"{season} preseason forecast"
        ),
        "draftFormat": "10-team · 1 QB · 2 RB · 2 WR · 1 TE · 2 FLEX · 1 K · 8 bench",
        "draftMethod": "Weekly managed-lineup value with bench, bye, and outcome uncertainty",
        "draftConfig": {
            "teams": 10,
            "draftSlot": 10,
            "rosterSlots": LEAGUE_ROSTER_SLOTS,
            "rosterMaximums": {"QB": 4, "RB": 8, "WR": 8, "TE": 3, "K": 3},
            "benchSlots": 8,
            "rounds": 17,
            "objective": "expected managed weekly lineup points",
        },
        "benchModel": {
            "weeks": 18,
            "simulations": 16,
            "parametersByPosition": outcome_parameters,
            "source": "2018-2024 expanding-window out-of-sample residuals",
            "replacementPolicy": "weekly position-level waiver fill",
        },
        "injuryModel": {
            "source": "2012-2025 point-in-time active-roster absences and injury reports",
            "historyPriorGames": 34,
            "durationPriorEpisodes": 2,
            "sizeAdjustment": "within-position BMI tercile empirical-Bayes risk ratio",
            "projectionTreatment": "mean-preserving availability paths",
        },
        "injuryReportsAvailable": injury_available,
        "injurySource": "nflverse/NFL game-status reports"
        if injury_available
        else "No current league game-status report published",
        "players": players,
    }
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        "window.NFL_DRAFT_DATA = "
        + json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
        + ";\n",
        encoding="utf-8",
    )
    return destination
