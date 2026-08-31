import pandas as pd

from nfl_fantasy_football.fantasy import evaluate_fantasy_points


def test_fantasy_evaluation_compares_component_and_baseline() -> None:
    frame = pd.DataFrame(
        {
            "season": [2024, 2024],
            "fantasy_relevant": [True, True],
            "actual_fantasy_points": [10.0, 20.0],
            "predicted_fantasy_points": [11.0, 19.0],
            "baseline_fantasy_points": [5.0, 25.0],
        }
    )
    _, summary = evaluate_fantasy_points(frame)
    relevant = summary[summary["scope"].eq("fantasy_relevant")]
    component = relevant[relevant["model"].eq("component_model")].iloc[0]
    baseline = relevant[relevant["model"].eq("recent_mean")].iloc[0]
    assert component["mean_rmse"] < baseline["mean_rmse"]
