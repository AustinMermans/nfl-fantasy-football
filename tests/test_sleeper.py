from nfl_fantasy_football.sleeper import parse_sleeper_market


def test_parse_sleeper_market_filters_non_redraft_players() -> None:
    payload = [
        {
            "player_id": "1",
            "player": {"first_name": "Test", "last_name": "Runner", "position": "RB", "team": "SEA"},
            "stats": {"adp_half_ppr": 12.4},
        },
        {
            "player_id": "2",
            "player": {"first_name": "Old", "last_name": "Linebacker", "position": "LB"},
            "stats": {"adp_half_ppr": 43},
        },
        {
            "player_id": "3",
            "player": {"first_name": "Deep", "last_name": "Reserve", "position": "WR"},
            "stats": {"adp_half_ppr": 999},
        },
    ]

    assert parse_sleeper_market(payload) == [
        {"sleeperId": "1", "name": "Test Runner", "position": "RB", "team": "SEA", "adp": 12.4}
    ]
