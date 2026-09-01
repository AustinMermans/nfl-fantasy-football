import pandas as pd

from nfl_fantasy_football.draft_backtest import (
    PolicyConfig,
    _opponent_pick,
    _timing_eligible,
    _weekly_lineup_score,
    add_market_implied_points,
    display_name_from_mfl,
    normalized_player_name,
    policy_grid,
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
                    "actual_weekly": {
                        week: points - index * 0.1 for week in range(1, 18)
                    },
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


def test_noisy_opponent_choice_is_reproducible_and_does_not_change_fixed_adp() -> None:
    available = [
        {
            "mfl_id": str(index),
            "name": f"RB {index}",
            "position": "RB",
            "adp": 10.0 + index,
        }
        for index in range(8)
    ]
    kwargs = {
        "rounds": 17,
        "roster_slots": {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 2, "K": 1},
        "roster_maximums": {"QB": 4, "RB": 8, "WR": 8, "TE": 3, "K": 3},
        "overall_pick": 20,
    }

    fixed = _opponent_pick(available, [], room_noise=0.0, noise_seed=11, **kwargs)
    noisy_first = _opponent_pick(available, [], room_noise=1.0, noise_seed=11, **kwargs)
    noisy_second = _opponent_pick(
        available, [], room_noise=1.0, noise_seed=11, **kwargs
    )

    assert fixed["mfl_id"] == "0"
    assert noisy_first == noisy_second


def test_policy_grid_builds_distinct_market_guardrails() -> None:
    policies = policy_grid(
        model_weights=[0.0],
        bench_weights=[0.15],
        adp_reaches=[2.0, 8.0],
    )

    assert len(policies) == 4
    assert {policy.max_adp_reach for policy in policies} == {2.0, 8.0}
    assert len({policy.name for policy in policies}) == 4


def test_managed_lineup_does_not_use_realized_points_to_choose_starter() -> None:
    roster = [
        {
            "mfl_id": "starter",
            "name": "Starter",
            "position": "QB",
            "adp": 10.0,
            "market_points": 300.0,
            "actual_weekly": {1: 5.0},
        },
        {
            "mfl_id": "backup",
            "name": "Backup",
            "position": "QB",
            "adp": 100.0,
            "market_points": 200.0,
            "actual_weekly": {1: 30.0},
        },
    ]
    slots = {"QB": 1, "RB": 0, "WR": 0, "TE": 0, "FLEX": 0, "K": 0}

    managed = _weekly_lineup_score(
        roster,
        1,
        selection_key="market_points",
        roster_slots=slots,
        lineup_mode="managed",
    )
    best_ball = _weekly_lineup_score(
        roster,
        1,
        selection_key="market_points",
        roster_slots=slots,
        lineup_mode="best_ball",
    )

    assert managed == 5.0
    assert best_ball == 30.0


def test_policy_grid_builds_roster_construction_profiles() -> None:
    policies = policy_grid(
        model_weights=[0.0],
        bench_weights=[0.0],
        adp_reaches=[2.0],
        roster_profiles=["one_qb_one_te", "two_qb_two_te"],
    )

    assert len(policies) == 4
    assert {policy.roster_profile for policy in policies} == {
        "one_qb_one_te",
        "two_qb_two_te",
    }


def test_policy_grid_builds_distinct_decision_rules() -> None:
    policies = policy_grid(
        model_weights=[0.0],
        bench_weights=[0.0],
        adp_reaches=[0.0],
        roster_profiles=["two_qb_two_te"],
        lookahead_values=[False],
        decision_rules=["adp", "utility"],
    )

    assert len(policies) == 2
    assert {policy.decision_rule for policy in policies} == {"adp", "utility"}
    assert len({policy.name for policy in policies}) == 2


def test_capped_adp_policy_enforces_two_qb_two_te_one_k_maximums() -> None:
    rows = []
    adp = 1
    for position, count in (("QB", 8), ("TE", 6), ("K", 4), ("RB", 16), ("WR", 16)):
        for index in range(count):
            points = 200.0 - adp
            rows.append(
                {
                    "mfl_id": f"{position}{index}",
                    "name": f"{position} {index}",
                    "position": position,
                    "adp": float(adp),
                    "market_points": points,
                    "season_ensemble": points,
                    "actual_weekly": {week: points for week in range(1, 18)},
                }
            )
            adp += 1

    result = simulate_historical_draft(
        pd.DataFrame(rows),
        teams=2,
        draft_slot=1,
        rounds=10,
        strategy="hybrid",
        policy=PolicyConfig(
            model_weight=0.0,
            bench_weight=0.0,
            lookahead=False,
            roster_profile="two_qb_two_te",
            decision_rule="adp",
        ),
    )

    assert result["n_qb"] == 2
    assert result["n_te"] == 2
    assert result["n_k"] == 1


def test_late_reserve_timing_delays_kicker_and_backup_qb() -> None:
    eligible = [
        {"mfl_id": "qb", "position": "QB"},
        {"mfl_id": "rb", "position": "RB"},
        {"mfl_id": "k", "position": "K"},
    ]
    roster = [{"mfl_id": "starter-qb", "position": "QB"}]

    middle = _timing_eligible(
        eligible,
        roster,
        overall_pick=51,
        teams=10,
        rounds=17,
        profile="late_reserves",
    )
    final = _timing_eligible(
        eligible,
        roster,
        overall_pick=161,
        teams=10,
        rounds=17,
        profile="late_reserves",
    )

    assert [player["mfl_id"] for player in middle] == ["rb"]
    assert {player["mfl_id"] for player in final} == {"qb", "rb", "k"}
