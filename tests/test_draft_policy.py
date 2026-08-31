from nfl_fantasy_football.draft_strategy import lineup_value, simulate_draft_policy


def test_lineup_value_uses_best_flex_and_replacement_for_empty_slots():
    players = [
        {"position": "RB", "points": 20.0},
        {"position": "RB", "points": 15.0},
        {"position": "WR", "points": 18.0},
        {"position": "WR", "points": 14.0},
        {"position": "TE", "points": 16.0},
    ]
    replacements = {"QB": 10.0, "RB": 5.0, "WR": 5.0, "TE": 5.0, "K": 3.0}

    assert lineup_value(players, "points", replacements=replacements) == 101.0


def test_dynamic_policy_completes_a_legal_starting_lineup():
    players = []
    for position, base in {"QB": 30, "RB": 25, "WR": 24, "TE": 18, "K": 10}.items():
        for index in range(8):
            players.append(
                {
                    "id": f"{position}{index}",
                    "name": f"{position} {index}",
                    "position": position,
                    "projectedPoints": float(base - index),
                    "actualPoints": float(base - index),
                }
            )

    result = simulate_draft_policy(
        players, teams=2, draft_slot=1, rounds=8, strategy="dynamic"
    )

    assert result["projected_starter_points"] > 0
    assert result["n_qb"] >= 1
    assert result["n_rb"] >= 2
    assert result["n_wr"] >= 2
    assert result["n_te"] >= 1
    assert result["n_k"] >= 1
