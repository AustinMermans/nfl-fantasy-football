import pandas as pd

from nfl_fantasy_football.production import (
    apply_point_calibration,
    veteran_reserve_cap_mask,
)


def test_point_calibration_changes_points_without_scaling_baseline() -> None:
    fantasy = pd.DataFrame(
        {
            "player_id": ["p1", "p1"],
            "predicted_fantasy_points": [10.0, 15.0],
            "baseline_fantasy_points": [8.0, 9.0],
        }
    )
    audit = pd.DataFrame(
        {"player_id": ["p1"], "point_calibration_scale": [2.0]}
    )

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
