import pandas as pd

from nfl_fantasy_football.draft_backtest import (
    PolicyConfig,
    add_market_implied_points,
    display_name_from_mfl,
    normalized_player_name,
    simulate_historical_draft,
)


def test_mfl_names_join_after_suffix_and_punctuation_normalization() -> None:
    assert display_name_from_mfl("McCaffrey, Christian") == "Christian McCaffrey"
    assert normalized_player_name("Robinson Jr., Brian") == normalized_player_name(
        "Brian Robinson"
    )


def test_market_point_curve_is_monotone_with_adp() -> None:
    history = pd.DataFrame(
        {
            "position": ["RB"] * 12,
            "adp": list(range(1, 13)),
            "actual_points": list(range(240, 120, -10)),
        }
    )
    current = pd.DataFrame({"position": ["RB"] * 3, "adp": [2.0, 6.0, 10.0]})

    scored = add_market_implied_points(current, history)

    assert scored["market_points"].is_monotonic_decreasing


def test_historical_draft_completes_legal_roster_and_scores_h2h() -> None:
    rows = []
    adp = 1
    for position, count, points in (
        ("QB", 8, 20.0),
        ("RB", 16, 16.0),
        ("WR", 16, 15.0),
        ("TE", 8, 11.0),
        ("K", 8, 8.0),
    ):
        for index in range(count):
            rows.append(
                {
                    "mfl_id": f"{position}{index}",
                    "name": f"{position} {index}",
                    "position": position,
                    "adp": float(adp),
                    "market_points": points - index * 0.1,
                    "season_ensemble": points - index * 0.08,
                    "actual_weekly": {week: points - index * 0.1 for week in range(1, 18)},
                }
            )
            adp += 1
    pool = pd.DataFrame(rows)

    result = simulate_historical_draft(
        pool,
        teams=2,
        draft_slot=1,
        rounds=10,
        strategy="hybrid",
        policy=PolicyConfig(model_weight=0.25, bench_weight=0.15, lookahead=True),
    )

    assert 0.0 <= result["h2h_win_rate"] <= 1.0
    assert result["managed_points_week_1_17"] > 0
    assert result["n_qb"] >= 1
    assert result["n_rb"] >= 2
    assert result["n_wr"] >= 2
    assert result["n_te"] >= 1
    assert result["n_k"] >= 1
