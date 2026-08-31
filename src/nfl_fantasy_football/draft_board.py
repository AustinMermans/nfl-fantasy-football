from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from .config import PROJECT_ROOT
from .fantasy import DEPLOYMENT_SELECTION, _selected_long


DISPLAY_FIELDS = (
    "passing_yards",
    "passing_tds",
    "passing_interceptions",
    "rushing_yards",
    "rushing_tds",
    "receiving_yards",
    "receiving_tds",
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
        "rushing_yards",
        "rushing_tds",
    ),
    "RB": (
        "rushing_yards",
        "rushing_tds",
        "receiving_yards",
        "receiving_tds",
        "fumbles_lost_total",
    ),
    "WR": (
        "receiving_yards",
        "receiving_tds",
        "rushing_yards",
        "rushing_tds",
        "fumbles_lost_total",
    ),
    "TE": ("receiving_yards", "receiving_tds", "fumbles_lost_total"),
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

DEFAULT_REPLACEMENT_RANKS = {"QB": 12, "RB": 30, "WR": 36, "TE": 12, "K": 12}
DEFAULT_DRAFT_WEIGHTS = {"QB": 0.55, "RB": 1.0, "WR": 1.0, "TE": 0.8, "K": 0.05}


def _number(value: object, digits: int = 1) -> float:
    return round(float(0.0 if pd.isna(value) else value), digits)


def _venue(game_id: str, team: str) -> str:
    home_team = str(game_id).rsplit("_", maxsplit=1)[-1]
    return "vs" if team == home_team else "at"


def build_player_rankings(
    fantasy_predictions: pd.DataFrame,
    component_predictions: pd.DataFrame,
    *,
    season: int | None = None,
    replacement_ranks: dict[str, int] | None = None,
    draft_weights: dict[str, float] | None = None,
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
    replacement_config = replacement_ranks or DEFAULT_REPLACEMENT_RANKS
    weight_config = draft_weights or DEFAULT_DRAFT_WEIGHTS
    replacement_points = {}
    for position, position_frame in totals.groupby("position"):
        ordered = position_frame.sort_values("projected_points", ascending=False)
        replacement_rank = min(replacement_config.get(position, len(ordered)), len(ordered))
        replacement_points[position] = float(
            ordered.iloc[replacement_rank - 1]["projected_points"]
        )
    totals["replacement_points"] = totals["position"].map(replacement_points)
    totals["value_over_replacement"] = (
        totals["projected_points"] - totals["replacement_points"]
    )
    totals["draft_value"] = totals.apply(
        lambda player: (
            player["value_over_replacement"]
            * weight_config.get(player["position"], 1.0)
            if player["value_over_replacement"] > 0
            else player["value_over_replacement"]
        ),
        axis=1,
    )
    draft_order = totals.sort_values(
        ["draft_value", "projected_points", "player_name"],
        ascending=[False, False, True],
    )
    draft_rank = {
        player_id: rank
        for rank, player_id in enumerate(draft_order["player_id"], start=1)
    }

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
                "projectedPoints": round(float(row.projected_points), 1),
                "actualPoints": round(float(row.actual_points), 1),
                "pointsPerGame": round(float(row.points_per_game), 2),
                "actualPointsPerGame": round(float(row.actual_points_per_game), 2),
                "projectedGames": int(row.projected_games),
                "modelLift": round(float(row.model_lift), 1),
                "draftRank": draft_rank[row.player_id],
                "actualRank": int(row.actual_rank),
                "draftValue": _number(row.draft_value),
                "valueOverReplacement": _number(row.value_over_replacement),
                "replacementPoints": _number(row.replacement_points),
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
        "draftFormat": "12-team · 1 QB · 2 RB · 2 WR · 1 TE · 1 FLEX",
        "draftMethod": "Value over replacement with one-QB, tight-end, and kicker opportunity-cost adjustments",
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
