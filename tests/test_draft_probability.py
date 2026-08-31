import pytest

from nfl_fantasy_football.draft_probability import (
    LeagueConfig,
    bench_option_value,
    conditional_survival,
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


def test_league_config_rejects_invalid_draft_slot() -> None:
    with pytest.raises(ValueError):
        LeagueConfig(teams=10, draft_slot=11)
