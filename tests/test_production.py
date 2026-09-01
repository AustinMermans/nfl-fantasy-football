import pandas as pd

from nfl_fantasy_football.production import apply_point_calibration


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
