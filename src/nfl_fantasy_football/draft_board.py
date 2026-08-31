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


def build_player_rankings(
    fantasy_predictions: pd.DataFrame,
    component_predictions: pd.DataFrame,
    *,
    season: int | None = None,
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
        baseline_points=("baseline_fantasy_points", "sum"),
        projected_games=("game_id", "nunique"),
    )
    totals = totals.merge(latest, on="player_id", validate="one_to_one")
    totals["points_per_game"] = (
        totals["projected_points"] / totals["projected_games"]
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

    totals = totals.sort_values(
        ["projected_points", "points_per_game", "player_name"],
        ascending=[False, False, True],
    ).reset_index(drop=True)
    totals["overall_rank"] = totals.index + 1
    totals["position_rank"] = (
        totals.groupby("position")["projected_points"]
        .rank(method="first", ascending=False)
        .astype(int)
    )

    rows: list[dict[str, object]] = []
    for row in totals.itertuples(index=False):
        stats = {}
        for field in DISPLAY_FIELDS:
            value = getattr(row, field, 0.0)
            stats[field] = round(float(0.0 if pd.isna(value) else value), 1)
        rows.append(
            {
                "id": row.player_id,
                "name": row.player_name,
                "position": row.position,
                "team": row.team,
                "rank": int(row.overall_rank),
                "positionRank": int(row.position_rank),
                "projectedPoints": round(float(row.projected_points), 1),
                "pointsPerGame": round(float(row.points_per_game), 2),
                "projectedGames": int(row.projected_games),
                "modelLift": round(float(row.model_lift), 1),
                "stats": stats,
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
