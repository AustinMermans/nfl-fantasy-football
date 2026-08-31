import numpy as np
import pandas as pd

from nfl_fantasy_football.participation import probability_metrics


def test_probability_metrics_reward_better_forecast() -> None:
    actual = pd.Series([0, 0, 1, 1])
    good = probability_metrics(actual, np.array([0.1, 0.2, 0.8, 0.9]))
    bad = probability_metrics(actual, np.array([0.5, 0.5, 0.5, 0.5]))
    assert good["log_loss"] < bad["log_loss"]
    assert good["brier"] < bad["brier"]
