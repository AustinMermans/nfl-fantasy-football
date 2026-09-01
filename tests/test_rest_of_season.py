import pandas as pd
import pytest

from nfl_fantasy_football.production import observed_completed_games
from nfl_fantasy_football.rest_of_season import (
    availability_adjusted_projection,
    blend_remaining_projection,
    inseason_component_weight,
    unconditional_projection_with_availability,
)


def test_preseason_blend_preserves_existing_position_weights() -> None:
    points, weight = blend_remaining_projection(
        200.0,
        240.0,
        remaining_games=17,
        games_played=0,
        position="RB",
    )
    assert weight == pytest.approx(0.25)
    assert points == pytest.approx(210.0)


def test_current_evidence_gains_weight_without_replacing_prior_immediately() -> None:
    early = inseason_component_weight("WR", 1)
    late = inseason_component_weight("WR", 12)
    assert 0.25 < early < late < 1.0


def test_remaining_prior_is_scaled_to_games_left() -> None:
    points, _ = blend_remaining_projection(
        170.0,
        80.0,
        remaining_games=8,
        games_played=9,
        position="QB",
    )
    assert 0 < points < 100


def test_availability_adjustment_includes_current_injury_status() -> None:
    healthy = availability_adjusted_projection(
        100.0,
        remaining_games=10,
        weekly_hazard=0.02,
        mean_duration=2.0,
    )
    out = availability_adjusted_projection(
        100.0,
        remaining_games=10,
        weekly_hazard=0.02,
        mean_duration=2.0,
        current_status="Out",
    )
    assert out[0] < healthy[0]
    assert out[1] < healthy[1]
    assert out[2] > healthy[2]


def test_unconditional_projection_is_not_discounted_again_for_availability() -> None:
    points, expected_games, expected_missed = unconditional_projection_with_availability(
        200.0,
        remaining_games=17,
        weekly_hazard=0.08,
        mean_duration=3.0,
        current_status="Questionable",
    )

    assert points == 200.0
    assert expected_games < 17
    assert expected_missed > 0


def test_completed_game_waits_for_player_stats_before_leaving_schedule() -> None:
    score_complete = pd.DataFrame(
        {
            "game_id": ["game-1", "game-2"],
            "week": [1, 1],
            "gameday": ["2026-09-10", "2026-09-11"],
        }
    )
    current_history = pd.DataFrame({"game_id": ["game-1"], "player_id": ["p1"]})

    observed = observed_completed_games(score_complete, current_history)

    assert observed["game_id"].tolist() == ["game-1"]
