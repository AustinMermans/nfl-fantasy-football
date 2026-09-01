from __future__ import annotations

import numpy as np


REGULAR_SEASON_GAMES = 17
POSITION_UPDATE_PRIOR_GAMES = {
    "QB": 5.0,
    "RB": 8.0,
    "WR": 8.0,
    "TE": 10.0,
    "K": 10.0,
}
CURRENT_INJURY_PROBABILITY = {
    "out": 1.0,
    "doubtful": 0.95,
    "questionable": 0.25,
}


def inseason_component_weight(
    position: str,
    games_played: float,
    *,
    rookie: bool = False,
) -> float:
    """Increase current-form weight as within-season evidence accumulates."""
    prior_games = POSITION_UPDATE_PRIOR_GAMES.get(position, 8.0)
    evidence = max(float(games_played), 0.0)
    reliability = evidence / (evidence + prior_games)
    return float(reliability)


def blend_remaining_projection(
    preseason_full_season: float,
    weekly_model_remaining: float,
    *,
    remaining_games: int,
    games_played: float,
    position: str,
    rookie: bool = False,
) -> tuple[float, float]:
    """Blend a frozen Week-0 prior with the current future-game forecast."""
    if remaining_games <= 0:
        return 0.0, inseason_component_weight(position, games_played, rookie=rookie)
    prior_remaining = (
        max(float(preseason_full_season), 0.0)
        * float(remaining_games)
        / REGULAR_SEASON_GAMES
    )
    weight = inseason_component_weight(position, games_played, rookie=rookie)
    blended = (1.0 - weight) * prior_remaining + weight * max(
        float(weekly_model_remaining), 0.0
    )
    return float(blended), weight


def unavailable_share(weekly_hazard: float, mean_duration: float) -> float:
    hazard = float(np.clip(weekly_hazard, 0.0, 1.0))
    duration = max(float(mean_duration), 1.0)
    return float(hazard * duration / (1.0 + hazard * (duration - 1.0)))


def availability_adjusted_projection(
    conditional_points: float,
    *,
    remaining_games: int,
    weekly_hazard: float,
    mean_duration: float,
    current_status: str | None = None,
) -> tuple[float, float, float]:
    """Convert a conditional ROS mean into an expected-availability mean."""
    if remaining_games <= 0:
        return 0.0, 0.0, 0.0
    baseline_share = unavailable_share(weekly_hazard, mean_duration)
    baseline_missed = remaining_games * baseline_share
    current_probability = CURRENT_INJURY_PROBABILITY.get(
        str(current_status or "").strip().lower(), 0.0
    )
    current_episode = current_probability * min(1.0, float(remaining_games))
    expected_missed = min(
        float(remaining_games),
        baseline_missed + (1.0 - baseline_share) * current_episode,
    )
    expected_games = float(remaining_games) - expected_missed
    expected_points = max(float(conditional_points), 0.0) * (
        expected_games / float(remaining_games)
    )
    return float(expected_points), expected_games, expected_missed


def unconditional_projection_with_availability(
    projected_points: float,
    *,
    remaining_games: int,
    weekly_hazard: float,
    mean_duration: float,
    current_status: str | None = None,
) -> tuple[float, float, float]:
    """Keep an unconditional point mean while reporting availability diagnostics."""
    _, expected_games, expected_missed = availability_adjusted_projection(
        projected_points,
        remaining_games=remaining_games,
        weekly_hazard=weekly_hazard,
        mean_duration=mean_duration,
        current_status=current_status,
    )
    return max(float(projected_points), 0.0), expected_games, expected_missed
