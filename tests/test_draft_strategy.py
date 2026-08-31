import pandas as pd

from nfl_fantasy_football.draft_strategy import (
    format_draft_metrics,
    next_pick_for_team,
    picks_until_next_turn,
    snake_team,
    starter_counts,
)


def _player_pool() -> pd.DataFrame:
    rows = []
    for position, points in {
        "QB": [300, 290, 280],
        "RB": [250, 240, 230, 220, 210, 200],
        "WR": [245, 235, 225, 215, 205, 195],
        "TE": [180, 170, 160],
        "K": [130, 120, 110],
    }.items():
        rows.extend(
            {
                "player_id": f"{position}{index}",
                "player_name": f"{position} {index}",
                "position": position,
                "points": value,
            }
            for index, value in enumerate(points, start=1)
        )
    return pd.DataFrame(rows)


def test_starter_counts_allocate_flex_to_best_remaining_players():
    counts = starter_counts(_player_pool(), "points", teams=2)

    assert counts == {"QB": 2, "RB": 5, "WR": 5, "TE": 2, "K": 2}


def test_format_rank_has_no_hand_set_position_multiplier():
    frame = _player_pool()
    replacement, value, rank = format_draft_metrics(frame, "points", teams=2)
    metrics = frame.assign(replacement=replacement, value=value, rank=rank).set_index(
        "player_id"
    )

    assert metrics.loc["QB1", "replacement"] == 290
    assert metrics.loc["QB1", "value"] == 10
    assert metrics.loc["RB1", "replacement"] == 210
    assert metrics.loc["RB1", "value"] == 40
    assert metrics.loc["RB1", "rank"] < metrics.loc["QB1", "rank"]


def test_snake_turn_math_handles_end_turns():
    assert [snake_team(pick, 4) for pick in range(1, 9)] == [1, 2, 3, 4, 4, 3, 2, 1]
    assert next_pick_for_team(1, 12, 1) == 24
    assert picks_until_next_turn(1, 12, 1) == 22
    assert next_pick_for_team(12, 12, 12) == 13
    assert picks_until_next_turn(12, 12, 12) == 0
