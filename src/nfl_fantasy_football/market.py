from __future__ import annotations

import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd


REQUIRED_MARKET_COLUMNS = {
    "source",
    "market_id",
    "game_id",
    "player_id",
    "stat_type",
    "line",
    "over_probability",
    "observed_at",
    "kickoff",
}

KALSHI_BASE = "https://external-api.kalshi.com/trade-api/v2"
POLYMARKET_GAMMA = "https://gamma-api.polymarket.com"
POLYMARKET_CLOB = "https://clob.polymarket.com"


def _get_json(base: str, path: str, parameters: dict[str, object] | None = None):
    query = urlencode(
        {key: value for key, value in (parameters or {}).items() if value is not None}
    )
    url = f"{base}{path}" + (f"?{query}" if query else "")
    request = Request(url, headers={"User-Agent": "nfl-fantasy-football/0.1"})
    with urlopen(request, timeout=60) as response:
        return json.load(response)


def kalshi_historical_markets(
    *,
    series_ticker: str,
    max_pages: int = 25,
) -> list[dict[str, object]]:
    """Load settled Kalshi markets for one verified recurring series."""
    markets: list[dict[str, object]] = []
    cursor: str | None = None
    for _ in range(max_pages):
        payload = _get_json(
            KALSHI_BASE,
            "/historical/markets",
            {"series_ticker": series_ticker, "limit": 1000, "cursor": cursor},
        )
        markets.extend(payload.get("markets", []))
        cursor = payload.get("cursor") or None
        if not cursor:
            break
    return markets


def kalshi_historical_candlesticks(
    ticker: str,
    *,
    start_ts: int,
    end_ts: int,
    interval_minutes: int = 60,
) -> list[dict[str, object]]:
    if interval_minutes not in {1, 60, 1440}:
        raise ValueError("Kalshi interval must be 1, 60, or 1440 minutes")
    payload = _get_json(
        KALSHI_BASE,
        f"/historical/markets/{ticker}/candlesticks",
        {
            "start_ts": start_ts,
            "end_ts": end_ts,
            "period_interval": interval_minutes,
        },
    )
    return payload.get("candlesticks", [])


def polymarket_markets(**filters: object) -> list[dict[str, object]]:
    payload = _get_json(POLYMARKET_GAMMA, "/markets", filters)
    if not isinstance(payload, list):
        raise ValueError("unexpected Polymarket markets response")
    return payload


def polymarket_price_history(
    token_id: str,
    *,
    start_ts: int | None = None,
    end_ts: int | None = None,
    interval: str | None = None,
    fidelity_minutes: int = 60,
) -> list[dict[str, float]]:
    payload = _get_json(
        POLYMARKET_CLOB,
        "/prices-history",
        {
            "market": token_id,
            "startTs": start_ts,
            "endTs": end_ts,
            "interval": interval,
            "fidelity": fidelity_minutes,
        },
    )
    return payload.get("history", [])


def point_in_time_market_features(markets: pd.DataFrame) -> pd.DataFrame:
    """Keep the final liquid quote known before kickoff for each player prop."""
    missing = REQUIRED_MARKET_COLUMNS.difference(markets.columns)
    if missing:
        raise ValueError(f"market data missing columns: {sorted(missing)}")
    frame = markets.copy()
    frame["observed_at"] = pd.to_datetime(frame["observed_at"], utc=True)
    frame["kickoff"] = pd.to_datetime(frame["kickoff"], utc=True)
    frame = frame[
        frame["observed_at"].lt(frame["kickoff"])
        & frame["over_probability"].between(0.0, 1.0)
    ]
    return (
        frame.sort_values("observed_at")
        .groupby(["source", "game_id", "player_id", "stat_type"], as_index=False)
        .tail(1)
        .reset_index(drop=True)
    )
