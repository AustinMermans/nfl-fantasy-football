import pandas as pd

from nfl_fantasy_football.draft_board import build_player_rankings


def test_player_rankings_aggregate_games_and_rank_positions():
    fantasy = pd.DataFrame(
        {
            "season": [2024, 2024, 2024],
            "week": [1, 2, 1],
            "game_id": ["a", "b", "c"],
            "player_id": ["p1", "p1", "p2"],
            "player_name": ["Alpha", "Alpha", "Beta"],
            "position": ["RB", "RB", "WR"],
            "team": ["A", "B", "C"],
            "opponent_team": ["C", "D", "A"],
            "predicted_fantasy_points": [10.0, 12.0, 18.0],
            "baseline_fantasy_points": [8.0, 8.0, 17.0],
            "fantasy_relevant": [True, True, True],
            "actual_fantasy_points": [11.0, 14.0, 17.0],
        }
    )
    components = pd.DataFrame(
        {
            "season": [2024, 2024, 2024],
            "game_id": ["a", "b", "c"],
            "player_id": ["p1", "p1", "p2"],
            "target": ["passing_yards", "passing_yards", "passing_yards"],
            "feature_set": ["context", "context", "context"],
            "model": ["hist", "hist", "hist"],
            "predicted": [0.0, 0.0, 250.0],
        }
    )

    rankings = build_player_rankings(fantasy, components, season=2024)

    assert [row["name"] for row in rankings] == ["Alpha", "Beta"]
    assert rankings[0]["projectedPoints"] == 22.0
    assert rankings[0]["pointsPerGame"] == 11.0
    assert rankings[0]["actualPoints"] == 25.0
    assert rankings[0]["actualPointsPerGame"] == 12.5
    assert rankings[0]["team"] == "B"
    assert rankings[0]["rank"] == 1
    assert rankings[1]["positionRank"] == 1
    assert rankings[1]["stats"]["passing_yards"] == 250.0
    assert rankings[0]["games"] == [
        {
            "week": 1,
            "gameId": "a",
            "team": "A",
            "opponent": "C",
            "venue": "at",
            "projectedPoints": 10.0,
            "actualPoints": 11.0,
            "baselinePoints": 8.0,
            "stats": {
                "rushing_yards": 0.0,
                "rushing_tds": 0.0,
                "receiving_yards": 0.0,
                "receiving_tds": 0.0,
                "fumbles_lost_total": 0.0,
            },
        },
        {
            "week": 2,
            "gameId": "b",
            "team": "B",
            "opponent": "D",
            "venue": "at",
            "projectedPoints": 12.0,
            "actualPoints": 14.0,
            "baselinePoints": 8.0,
            "stats": {
                "rushing_yards": 0.0,
                "rushing_tds": 0.0,
                "receiving_yards": 0.0,
                "receiving_tds": 0.0,
                "fumbles_lost_total": 0.0,
            },
        },
    ]
    assert rankings[0]["draftRank"] in {1, 2}
    assert rankings[0]["actualDraftRank"] == 1
    assert rankings[0]["actualRank"] == 1
    assert rankings[0]["actualPositionRank"] == 1
    assert rankings[0]["draftValue"] == 0.0
    assert rankings[0]["valueOverReplacement"] == 0.0
    assert rankings[0]["actualValueOverReplacement"] == 0.0
