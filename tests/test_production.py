import pandas as pd

from nfl_fantasy_football.data import ensure_columns
from nfl_fantasy_football.production import (
    apply_point_calibration,
    preseason_feature_snapshots,
    veteran_reserve_cap_mask,
)


def test_missing_optional_injury_columns_are_filled_with_nulls() -> None:
    injuries = pd.DataFrame(
        {
            "report_status": ["Questionable"],
            "practice_primary_injury": ["Knee"],
            "practice_status": ["Limited"],
        }
    )
    expected = (
        "report_primary_injury",
        "report_secondary_injury",
        "report_status",
        "practice_primary_injury",
        "practice_secondary_injury",
        "practice_status",
    )

    normalized = ensure_columns(injuries, expected)

    assert list(normalized.columns) == [
        "report_status",
        "practice_primary_injury",
        "practice_status",
        "report_primary_injury",
        "report_secondary_injury",
        "practice_secondary_injury",
    ]
    assert normalized["report_status"].iloc[0] == "Questionable"
    assert normalized["report_primary_injury"].isna().all()
    assert normalized["report_secondary_injury"].isna().all()
    assert normalized["practice_secondary_injury"].isna().all()


def test_feature_snapshots_exclude_current_season_history_rows() -> None:
    def row(game_id: str, week: int, played: float) -> dict[str, object]:
        return {
            "game_id": game_id,
            "gameday": pd.Timestamp("2026-09-01") + pd.Timedelta(days=7 * week),
            "season": 2026,
            "week": week,
            "player_id": "player-1",
            "player_name": "Player One",
            "position": "WR",
            "team": "A",
            "opponent_team": "B",
            "offense_snaps": 40.0 * played,
            "offense_pct": 0.7 * played,
            "st_snaps": 0.0,
            "played": played,
            "home": 1.0,
            "rest_days": 7.0,
            "roof": "outdoors",
            "surface": "grass",
            "temp": 70.0,
            "wind": 5.0,
            "spread_line": -2.5,
            "total_line": 45.0,
        }

    history = pd.DataFrame([row("played-game", 1, 1.0)])
    future = pd.DataFrame([row("future-game-2", 2, 0.0), row("future-game-3", 3, 0.0)])

    snapshots = preseason_feature_snapshots(history, future)

    assert snapshots["game_id"].tolist() == ["future-game-2", "future-game-3"]
    assert snapshots["player_games_prior"].tolist() == [1.0, 1.0]


def test_point_calibration_changes_points_without_scaling_baseline() -> None:
    fantasy = pd.DataFrame(
        {
            "player_id": ["p1", "p1"],
            "predicted_fantasy_points": [10.0, 15.0],
            "baseline_fantasy_points": [8.0, 9.0],
        }
    )
    audit = pd.DataFrame({"player_id": ["p1"], "point_calibration_scale": [2.0]})

    calibrated = apply_point_calibration(fantasy, audit)

    assert calibrated["predicted_fantasy_points"].tolist() == [20.0, 30.0]
    assert calibrated["baseline_fantasy_points"].tolist() == [8.0, 9.0]
    assert fantasy["predicted_fantasy_points"].tolist() == [10.0, 15.0]


def test_veteran_reserve_cap_uses_post_blend_points() -> None:
    adjustments = pd.DataFrame(
        {
            "position": ["QB", "QB", "QB", "RB"],
            "depth_rank": [2, 1, 2, 3],
            "is_rookie": [False, False, True, False],
            "predicted_fantasy_points": [25.0, 25.0, 25.0, 40.0],
            "adjusted_points": [80.0, 80.0, 80.0, 40.0],
            "role_prior_points": [35.0, 35.0, 35.0, 50.0],
        }
    )

    mask = veteran_reserve_cap_mask(adjustments)

    assert mask.tolist() == [True, False, False, False]
