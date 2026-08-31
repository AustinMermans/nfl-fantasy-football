import pandas as pd

from nfl_fantasy_football.rookies import (
    historical_rookie_seasons,
    rookie_prior_table,
    weighted_quantile,
)


def test_weighted_quantile_moves_toward_high_weight_observation() -> None:
    result = weighted_quantile(
        pd.Series([10.0, 20.0, 100.0]),
        pd.Series([1.0, 1.0, 8.0]),
        (0.5,),
    )
    assert result[0] > 50.0


def test_rookie_history_only_uses_first_season() -> None:
    history = pd.DataFrame(
        {
            "season": [2024, 2024, 2025],
            "player_id": ["r", "v", "r"],
            "player_name": ["Rookie", "Veteran", "Rookie"],
            "position": ["RB", "RB", "RB"],
            "draft_year": [2024, 2020, 2024],
            "years_exp": [0, 4, 1],
            "draft_pick": [10, 20, 10],
            "game_id": ["a", "b", "c"],
            "rushing_yards": [100.0, 100.0, 100.0],
        }
    )
    outcomes = historical_rookie_seasons(history)
    assert outcomes[["season", "player_id"]].to_dict("records") == [
        {"season": 2024, "player_id": "r"}
    ]
    assert outcomes.iloc[0]["actual_points"] == 10.0


def test_rookie_prior_preserves_an_upside_range() -> None:
    history_rows = []
    for season, points, pick in ((2022, 20.0, 10), (2023, 100.0, 20), (2024, 220.0, 30)):
        history_rows.append(
            {
                "season": season,
                "player_id": f"r{season}",
                "player_name": f"Rookie {season}",
                "position": "RB",
                "draft_year": season,
                "years_exp": 0,
                "draft_pick": pick,
                "game_id": f"g{season}",
                "rushing_yards": points * 10,
            }
        )
    history = pd.DataFrame(history_rows)
    totals = pd.DataFrame(
        {
            "player_id": ["rookie", "vet"],
            "player_name": ["New Rookie", "Veteran"],
            "position": ["RB", "RB"],
            "team": ["A", "B"],
            "predicted_fantasy_points": [5.0, 140.0],
        }
    )
    roles = pd.DataFrame(
        {
            "player_id": ["rookie", "vet"],
            "depth_rank": [1, 1],
            "player_games_prior": [0, 40],
            "draft_pick": [20, 50],
        }
    )
    prior = rookie_prior_table(history, totals, roles).iloc[0]
    assert prior["rookie_p10"] < prior["rookie_p50"] < prior["rookie_p90"]
    assert prior["rookie_prior_mean"] > 5.0
