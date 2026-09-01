import pytest
import pandas as pd

from nfl_fantasy_football.draft_probability import (
    LeagueConfig,
    bayesian_model_update,
    bench_option_value,
    conditional_survival,
    estimate_weekly_outcome_parameters,
    quantal_response_probabilities,
)


def test_conditional_survival_conditions_on_current_availability() -> None:
    assert conditional_survival(0.25, 0.625) == pytest.approx(0.5)


def test_quantal_response_is_normalized_and_favors_utility() -> None:
    probabilities = quantal_response_probabilities([0.0, 1.0, 2.0], rationality=2.0)
    assert sum(probabilities) == pytest.approx(1.0)
    assert probabilities[2] > probabilities[1] > probabilities[0]


def test_bench_option_value_only_counts_upside_over_replacement() -> None:
    assert bench_option_value([40.0, 100.0, 160.0], 100.0) == pytest.approx(20.0)


def test_weekly_outcome_parameters_use_draft_relevant_oos_rows() -> None:
    predictions = pd.DataFrame(
        {
            "position": ["RB"] * 6 + ["QB"] * 2,
            "actual_fantasy_points": [1.0, 2.0, 3.0, 8.0, 12.0, 18.0, 10.0, 16.0],
            "predicted_fantasy_points": [1.0, 2.0, 3.0, 6.0, 10.0, 12.0, 11.0, 15.0],
            "fantasy_relevant": [True] * 7 + [False],
        }
    )

    parameters = estimate_weekly_outcome_parameters(predictions)

    assert parameters["RB"]["sampleSize"] == 3
    assert parameters["RB"]["forecastThreshold"] == pytest.approx(4.5)
    assert parameters["RB"]["relativeError68"] > 0
    assert parameters["QB"]["sampleSize"] == 1


def test_league_config_rejects_invalid_draft_slot() -> None:
    with pytest.raises(ValueError):
        LeagueConfig(teams=10, draft_slot=11)


def test_bayesian_room_update_moves_mass_toward_likely_model() -> None:
    posterior = bayesian_model_update(
        {"balanced": 0.5, "rb_heavy": 0.5},
        {"balanced": 0.2, "rb_heavy": 0.8},
    )
    assert posterior == pytest.approx({"balanced": 0.2, "rb_heavy": 0.8})
