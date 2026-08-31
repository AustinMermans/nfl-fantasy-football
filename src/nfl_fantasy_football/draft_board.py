from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from .config import PROJECT_ROOT
from .draft_strategy import DEFAULT_ROSTER_SLOTS, format_draft_metrics
from .fantasy import DEPLOYMENT_SELECTION, _selected_long
from .scoring import load_scoring


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
    teams: int = 12,
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
        roster_slots=roster_slots,
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
        roster_slots=roster_slots,
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
        "scoring": "Traditional non-PPR",
        "scope": "Out-of-sample development ranking",
        "draftFormat": "12-team · 1 QB · 2 RB · 2 WR · 1 TE · 1 FLEX · 1 K",
        "draftMethod": "Format-derived starter value with live next-turn scarcity and roster fit",
        "draftConfig": {"teams": 12, "draftSlot": 1, "rosterSlots": DEFAULT_ROSTER_SLOTS},
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
) -> Path:
    """Publish a current preseason board without retrospective actual outcomes."""
    destination_dir = web_dir or PROJECT_ROOT / "web"
    players = build_player_rankings(fantasy, components, season=season)
    depth = (
        future_features.sort_values(["player_id", "week"])
        .groupby("player_id", as_index=False)
        .first()[
            [
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
                "report_primary_injury",
                "report_status",
                "practice_status",
            ]
        ]
        .set_index("player_id")
        .to_dict("index")
    )
    for player in players:
        role = depth.get(player["id"], {})
        player["depthRank"] = int(_number(role.get("depth_rank"), 0))
        player["depthSlot"] = int(_number(role.get("depth_slot"), 0))
        player["depthRole"] = _text(role.get("pos_name"))
        player["projectionNote"] = _text(role.get("role_adjustment")) or "none"
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
    injury_available = bool(future_features["current_injury_feed"].any())
    payload = {
        "generatedAt": datetime.now(UTC).isoformat(),
        "dataAsOf": data_as_of,
        "trainingThrough": season - 1,
        "projectionSeason": season,
        "forecastType": "preseason",
        "hasActuals": False,
        "scoring": "Traditional non-PPR",
        "scoringWeights": load_scoring(),
        "scope": f"{season} preseason forecast",
        "draftFormat": "12-team · 1 QB · 2 RB · 2 WR · 1 TE · 1 FLEX · 1 K",
        "draftMethod": "Format-derived starter value with current roster and depth chart",
        "draftConfig": {
            "teams": 12,
            "draftSlot": 1,
            "rosterSlots": DEFAULT_ROSTER_SLOTS,
            "benchSlots": 4,
            "rounds": 12,
            "objective": "expected optimal starter points",
        },
        "injuryReportsAvailable": injury_available,
        "injurySource": "nflverse/NFL game-status reports"
        if injury_available
        else "No current league game-status report published",
        "players": players,
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
