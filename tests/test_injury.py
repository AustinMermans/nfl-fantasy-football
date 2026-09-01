import pandas as pd

from nfl_fantasy_football.injury import estimate_injury_risk_profiles


def test_recurrent_long_absences_raise_hazard_and_duration() -> None:
    rows = []
    for player_id, missed_weeks in (
        ("healthy", set()),
        ("brief", {6}),
        ("recurrent", {2, 3, 8, 9, 10}),
    ):
        for week in range(1, 18):
            missed = week in missed_weeks
            rows.append(
                {
                    "player_id": player_id,
                    "position": "RB",
                    "season": 2025,
                    "week": week,
                    "played": 0.0 if missed else 1.0,
                    "report_primary_injury": "Knee" if missed else None,
                    "practice_primary_injury": None,
                    "report_status": "Out" if missed else None,
                    "height": 71.0,
                    "weight": 215.0,
                }
            )
    history = pd.DataFrame(rows)
    current = pd.DataFrame(
        {
            "player_id": ["healthy", "recurrent", "rookie"],
            "position": ["RB", "RB", "RB"],
            "height": [71.0, 71.0, 71.0],
            "weight": [215.0, 215.0, 215.0],
        }
    )

    profiles = estimate_injury_risk_profiles(history, current).set_index("player_id")

    assert profiles.loc["recurrent", "injury_weekly_hazard"] > profiles.loc[
        "healthy", "injury_weekly_hazard"
    ]
    assert profiles.loc["recurrent", "injury_mean_duration"] > profiles.loc[
        "healthy", "injury_mean_duration"
    ]
    assert profiles.loc["rookie", "injury_history_episodes"] == 0
    assert profiles.loc["rookie", "injury_weekly_hazard"] > 0


def test_size_multiplier_is_learned_within_position() -> None:
    rows = []
    for player_index, weight in enumerate((180.0, 180.0, 220.0, 220.0, 260.0, 260.0)):
        for week in range(1, 11):
            injured = weight == 260.0 and week == 5
            rows.append(
                {
                    "player_id": f"rb-{player_index}",
                    "position": "RB",
                    "season": 2025,
                    "week": week,
                    "played": 0.0 if injured else 1.0,
                    "report_primary_injury": "Knee" if injured else None,
                    "practice_primary_injury": None,
                    "report_status": "Out" if injured else None,
                    "height": 71.0,
                    "weight": weight,
                }
            )
    current = pd.DataFrame(
        {
            "player_id": ["new-light", "new-heavy"],
            "position": ["RB", "RB"],
            "height": [71.0, 71.0],
            "weight": [180.0, 260.0],
        }
    )

    profiles = estimate_injury_risk_profiles(pd.DataFrame(rows), current).set_index(
        "player_id"
    )

    assert profiles.loc["new-heavy", "injury_size_multiplier"] > profiles.loc[
        "new-light", "injury_size_multiplier"
    ]


def test_position_fallback_handles_history_with_no_observed_injuries() -> None:
    history = pd.DataFrame(
        {
            "player_id": ["qb"] * 4,
            "position": ["QB"] * 4,
            "season": [2025] * 4,
            "week": [1, 2, 3, 4],
            "played": [1.0] * 4,
            "report_primary_injury": [None] * 4,
            "practice_primary_injury": [None] * 4,
            "report_status": [None] * 4,
            "height": [75.0] * 4,
            "weight": [220.0] * 4,
        }
    )
    current = history[["player_id", "position", "height", "weight"]].head(1)

    profile = estimate_injury_risk_profiles(history, current).iloc[0]

    assert profile["injury_weekly_hazard"] > 0
    assert profile["injury_mean_duration"] >= 1
    assert profile["injury_baseline_duration"] >= 1
    assert profile["injury_weekly_hazard"] >= 0.85 * profile["injury_baseline_hazard"]
