import pandas as pd
import pytest

from nfl_fantasy_football.market import (
    attach_market_features,
    kalshi_candlesticks_to_quotes,
    kalshi_historical_candlesticks,
    kalshi_player_market_catalog,
    market_admission_audit,
    market_consensus_features,
    parse_player_prop_label,
    point_in_time_market_features,
    polymarket_player_market_catalog,
    polymarket_history_to_quotes,
    resolve_player_market_catalog,
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


def test_prop_parser_accepts_explicit_player_stats_and_rejects_futures() -> None:
    assert parse_player_prop_label("Sam Darnold: 250+ passing yards") == {
        "player_name": "Sam Darnold",
        "stat_type": "passing_yards",
        "line": 250.0,
    }
    assert parse_player_prop_label("Jaxson Dart records 275+ passing yards") == {
        "player_name": "Jaxson Dart",
        "stat_type": "passing_yards",
        "line": 275.0,
    }
    assert parse_player_prop_label(
        "Will Patrick Mahomes throw for over 275 Yards?"
    ) == {
        "player_name": "Patrick Mahomes",
        "stat_type": "passing_yards",
        "line": 275.0,
    }
    assert parse_player_prop_label("Will Travis Kelce score the first TD?") == {
        "player_name": "Travis Kelce",
        "stat_type": "first_touchdown",
        "line": 0.5,
    }
    assert parse_player_prop_label("Saquon Barkley Anytime Touchdown?") == {
        "player_name": "Saquon Barkley",
        "stat_type": "anytime_touchdown",
        "line": 0.5,
    }
    assert (
        parse_player_prop_label(
            "Will Joe Burrow finish the regular season with the most passing yards?"
        )
        is None
    )


def test_point_in_time_selection_preserves_alternate_lines() -> None:
    rows = pd.DataFrame(
        {
            "source": ["kalshi"] * 4,
            "market_id": ["m200", "m200", "m250", "m250"],
            "game_id": ["g"] * 4,
            "player_id": ["p"] * 4,
            "stat_type": ["passing_yards"] * 4,
            "line": [200.0, 200.0, 250.0, 250.0],
            "over_probability": [0.7, 0.8, 0.4, 0.3],
            "observed_at": [
                "2025-09-01T10:00:00Z",
                "2025-09-01T11:00:00Z",
                "2025-09-01T10:00:00Z",
                "2025-09-01T11:00:00Z",
            ],
            "kickoff": ["2025-09-01T12:00:00Z"] * 4,
        }
    )
    selected = point_in_time_market_features(rows)
    assert selected["line"].tolist() == [200.0, 250.0]
    assert selected["over_probability"].tolist() == [0.8, 0.3]


def test_market_consensus_interpolates_probability_ladder() -> None:
    rows = pd.DataFrame(
        {
            "source": ["kalshi"] * 3,
            "market_id": ["m200", "m225", "m250"],
            "game_id": ["g"] * 3,
            "player_id": ["p"] * 3,
            "stat_type": ["passing_yards"] * 3,
            "line": [200.0, 225.0, 250.0],
            "over_probability": [0.8, 0.6, 0.3],
            "observed_at": ["2025-09-01T11:00:00Z"] * 3,
            "kickoff": ["2025-09-01T12:00:00Z"] * 3,
            "volume": [100.0, 200.0, 300.0],
        }
    )
    consensus = market_consensus_features(rows)
    assert consensus.iloc[0]["market_prop_median"] == pytest.approx(233.3333333333)
    assert consensus.iloc[0]["market_prop_quotes"] == 3
    assert consensus.iloc[0]["market_prop_volume"] == 600.0


def test_catalog_parsers_normalize_source_records() -> None:
    kalshi = kalshi_player_market_catalog(
        [
            {
                "ticker": "m",
                "event_ticker": "e",
                "title": "Sam Darnold: 250+ passing yards",
                "volume_fp": "12.00",
            }
        ],
        series_ticker="KXNFLPASSYDS",
    )
    assert kalshi.iloc[0]["stat_type"] == "passing_yards"

    polymarket = polymarket_player_market_catalog(
        [
            {
                "id": "e",
                "markets": [
                    {
                        "id": "m",
                        "question": "Saquon Barkley Anytime Touchdown?",
                        "volumeNum": 10,
                    }
                ],
            }
        ]
    )
    assert polymarket.iloc[0]["stat_type"] == "anytime_touchdown"


def test_source_histories_convert_to_canonical_quotes() -> None:
    kalshi = kalshi_candlesticks_to_quotes(
        {"ticker": "m", "title": "Sam Darnold: 250+ passing yards"},
        [
            {
                "end_period_ts": 1_756_720_000,
                "yes_bid": {"close_dollars": "0.4800"},
                "yes_ask": {"close_dollars": "0.5200"},
                "price": {"close_dollars": "0.5100"},
                "volume_fp": "12.00",
            }
        ],
        game_id="g",
        player_id="p",
        kickoff="2025-09-01T12:00:00Z",
    )
    assert kalshi.iloc[0]["over_probability"] == 0.5
    assert kalshi.iloc[0]["volume"] == 12.0

    polymarket = polymarket_history_to_quotes(
        {"id": "m", "question": "Saquon Barkley Anytime Touchdown?"},
        [{"t": 1_756_720_000, "p": 0.61}],
        game_id="g",
        player_id="p",
        kickoff="2025-09-01T12:00:00Z",
    )
    assert polymarket.iloc[0]["over_probability"] == 0.61


def test_attach_and_admission_audit_use_common_support_only() -> None:
    games = pd.DataFrame(
        {
            "game_id": ["g1", "g2", "g3"],
            "player_id": ["p", "p", "p"],
            "season": [2022, 2023, 2025],
        }
    )
    features = pd.DataFrame(
        {
            "game_id": ["g1", "g2", "g3"],
            "player_id": ["p", "p", "p"],
            "stat_type": ["passing_yards"] * 3,
            "market_prop_median": [200.0, 210.0, 220.0],
            "market_prop_sources": [1, 1, 1],
        }
    )
    attached = attach_market_features(games, features)
    assert attached["market_passing_yards_median"].tolist() == [200.0, 210.0, 220.0]
    audit = market_admission_audit(
        features,
        games,
        development_end_season=2024,
        minimum_seasons=2,
        minimum_rows_per_season=1,
    )
    assert audit.iloc[0]["common_support_rows"] == 2
    assert bool(audit.iloc[0]["coverage_gate_passed"])


def test_catalog_resolution_matches_exact_name_and_event_date() -> None:
    catalog = pd.DataFrame(
        {
            "event_id": ["KXNFLPASSYDS-24SEP08NECIN", "bad"],
            "player_name": ["Joe Burrow", "Unknown Player"],
        }
    )
    games = pd.DataFrame(
        {
            "game_id": ["2024_01_NE_CIN"],
            "gameday": ["2024-09-08"],
            "player_id": ["p"],
            "player_name": ["Joe Burrow"],
        }
    )
    resolved = resolve_player_market_catalog(catalog, games)
    assert resolved.loc[0, "game_id"] == "2024_01_NE_CIN"
    assert resolved.loc[0, "match_status"] == "exact_name_date"
    assert resolved.loc[1, "match_status"] == "unmatched"
