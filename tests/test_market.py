import pandas as pd

from nfl_fantasy_football.market import (
    kalshi_historical_candlesticks,
    point_in_time_market_features,
)


def test_market_feature_uses_last_quote_before_kickoff() -> None:
    rows = pd.DataFrame(
        {
            "source": ["kalshi"] * 3,
            "market_id": ["m"] * 3,
            "game_id": ["g"] * 3,
            "player_id": ["p"] * 3,
            "stat_type": ["passing_yards"] * 3,
            "line": [250.5] * 3,
            "over_probability": [0.45, 0.55, 0.99],
            "observed_at": [
                "2025-09-01T10:00:00Z",
                "2025-09-01T11:00:00Z",
                "2025-09-01T13:00:00Z",
            ],
            "kickoff": ["2025-09-01T12:00:00Z"] * 3,
        }
    )
    selected = point_in_time_market_features(rows)
    assert len(selected) == 1
    assert selected.iloc[0]["over_probability"] == 0.55


def test_kalshi_rejects_unsupported_candle_interval() -> None:
    try:
        kalshi_historical_candlesticks("ticker", start_ts=1, end_ts=2, interval_minutes=15)
    except ValueError as error:
        assert "interval" in str(error)
    else:
        raise AssertionError("invalid interval should fail before a network call")
