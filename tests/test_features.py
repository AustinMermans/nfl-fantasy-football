import pandas as pd

from nfl_fantasy_football.features import build_features


def _row(game: int, yards: float, opponent: str = "B") -> dict[str, object]:
    row: dict[str, object] = {
        "game_id": str(game),
        "gameday": pd.Timestamp("2024-09-01") + pd.Timedelta(days=7 * game),
        "season": 2024,
        "week": game + 1,
        "player_id": "p1",
        "player_name": "Player One",
        "position": "WR",
        "team": "A",
        "opponent_team": opponent,
        "offense_snaps": 40.0,
        "offense_pct": 0.7,
        "home": 1.0,
        "rest_days": 7.0,
        "age": 25.0,
        "years_since_draft": 3.0,
        "roof": "outdoors",
        "surface": "grass",
        "temp": 70.0,
        "wind": 5.0,
        "spread_line": -2.5,
        "total_line": 45.0,
    }
    for column in (
        "attempts", "passing_yards", "passing_tds", "passing_interceptions",
        "carries", "rushing_yards", "rushing_tds", "targets", "receptions",
        "receiving_yards", "receiving_tds", "receiving_air_yards",
        "target_share", "air_yards_share",
    ):
        row[column] = yards if column == "receiving_yards" else 0.0
    return row


def test_player_history_is_strictly_lagged() -> None:
    frame = pd.DataFrame([_row(0, 10.0), _row(1, 20.0), _row(2, 999.0)])
    features = build_features(frame)
    assert pd.isna(features.loc[0, "receiving_yards_lag1"])
    assert features.loc[1, "receiving_yards_lag1"] == 10.0
    assert features.loc[2, "receiving_yards_ewm12"] < 20.0


def test_current_target_change_does_not_change_same_row_features() -> None:
    original = pd.DataFrame([_row(0, 10.0), _row(1, 20.0)])
    changed = original.copy()
    changed.loc[1, "receiving_yards"] = 500.0
    before = build_features(original).loc[1, "receiving_yards_ewm4"]
    after = build_features(changed).loc[1, "receiving_yards_ewm4"]
    assert before == after == 10.0

