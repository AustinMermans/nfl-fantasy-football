from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Iterable
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import numpy as np
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

# Both hosts are documented production hosts. The elections host currently has
# broader unauthenticated availability; external-api remains the fallback.
KALSHI_BASES = (
    "https://api.elections.kalshi.com/trade-api/v2",
    "https://external-api.kalshi.com/trade-api/v2",
)
KALSHI_BASE = KALSHI_BASES[0]
POLYMARKET_GAMMA = "https://gamma-api.polymarket.com"
POLYMARKET_CLOB = "https://clob.polymarket.com"
POLYMARKET_NFL_TAG_ID = 450

KALSHI_PLAYER_SERIES = {
    "KXNFLPASSYDS": "passing_yards",
    "KXNFLPASSTDS": "passing_tds",
    "KXNFLPASSINT": "passing_interceptions",
    "KXNFLPASSATT": "attempts",
    "KXNFLPASSCOMP": "completions",
    "KXNFLRSHYDS": "rushing_yards",
    "KXNFLRSHATT": "carries",
    "KXNFLRECYDS": "receiving_yards",
    "KXNFLREC": "receptions",
    "KXNFLANYTD": "anytime_touchdown",
    "KXNFL2TD": "multiple_touchdowns",
    "KXNFLWEEKCOMPETE": "participation",
    "KXNFLFFPTS": "fantasy_points",
}

STAT_ALIASES = {
    "passing yard": "passing_yards",
    "passing yards": "passing_yards",
    "passing touchdown": "passing_tds",
    "passing touchdowns": "passing_tds",
    "passing td": "passing_tds",
    "passing tds": "passing_tds",
    "passing interception": "passing_interceptions",
    "passing interceptions": "passing_interceptions",
    "passing attempt": "attempts",
    "passing attempts": "attempts",
    "passing completion": "completions",
    "passing completions": "completions",
    "rushing yard": "rushing_yards",
    "rushing yards": "rushing_yards",
    "rushing attempt": "carries",
    "rushing attempts": "carries",
    "carry": "carries",
    "carries": "carries",
    "receiving yard": "receiving_yards",
    "receiving yards": "receiving_yards",
    "reception": "receptions",
    "receptions": "receptions",
    "fantasy point": "fantasy_points",
    "fantasy points": "fantasy_points",
}

_MILESTONE_PATTERN = re.compile(
    r"^(?P<player>.+?)(?::|\s+records)\s*(?P<line>\d+(?:\.\d+)?)\+\s*"
    r"(?P<stat>passing yards?|passing touchdowns?|passing tds?|"
    r"passing interceptions?|passing attempts?|passing completions?|"
    r"rushing yards?|rushing attempts?|carries|receiving yards?|receptions?|"
    r"fantasy points?)$",
    re.IGNORECASE,
)
_OVER_PATTERN = re.compile(
    r"^Will\s+(?P<player>.+?)\s+(?:throw|rush|record|have|finish with)"
    r"(?:\s+for)?\s+over\s+(?P<line>\d+(?:\.\d+)?)\s+"
    r"(?P<stat>passing yards?|rushing yards?|receiving yards?|receptions?|"
    r"passing touchdowns?|passing tds?|fantasy points?)\??$",
    re.IGNORECASE,
)
_ANYTIME_TD_PATTERN = re.compile(
    r"^(?:Will\s+)?(?P<player>.+?)(?:\s+score)?\s+Anytime Touchdown\??$",
    re.IGNORECASE,
)
_THROW_YARDS_PATTERN = re.compile(
    r"^Will\s+(?P<player>.+?)\s+throw\s+for\s+over\s+"
    r"(?P<line>\d+(?:\.\d+)?)\s+yards\??$",
    re.IGNORECASE,
)
_FIRST_TD_PATTERN = re.compile(
    r"^Will\s+(?P<player>.+?)\s+score\s+the\s+first\s+TD\??$",
    re.IGNORECASE,
)
_RUSH_TD_PATTERN = re.compile(
    r"^Will\s+(?P<player>.+?)\s+run\s+for\s+a\s+TD\??$",
    re.IGNORECASE,
)


def _get_json(
    base: str | Iterable[str],
    path: str,
    parameters: dict[str, object] | None = None,
):
    query = urlencode(
        {key: value for key, value in (parameters or {}).items() if value is not None}
    )
    bases = (base,) if isinstance(base, str) else tuple(base)
    last_error: Exception | None = None
    for candidate in bases:
        url = f"{candidate}{path}" + (f"?{query}" if query else "")
        request = Request(url, headers={"User-Agent": "nfl-fantasy-football/0.1"})
        try:
            with urlopen(request, timeout=60) as response:
                return json.load(response)
        except HTTPError as error:
            last_error = error
            if error.code not in {403, 404, 429}:
                raise
    if last_error is not None:
        raise last_error
    raise RuntimeError("no API base URL configured")


def _paginated(
    base: str | Iterable[str],
    path: str,
    *,
    item_key: str,
    parameters: dict[str, object] | None = None,
    max_pages: int = 25,
    limit: int = 1000,
) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    cursor: str | None = None
    for _ in range(max_pages):
        payload = _get_json(
            base,
            path,
            {**(parameters or {}), "limit": limit, "cursor": cursor},
        )
        items.extend(payload.get(item_key, []))
        cursor = payload.get("cursor") or None
        if not cursor:
            break
    return items


def kalshi_series(*, category: str = "Sports") -> list[dict[str, object]]:
    payload = _get_json(
        KALSHI_BASES,
        "/series",
        {
            "category": category,
            "include_product_metadata": "true",
            "include_volume": "true",
        },
    )
    return payload.get("series", [])


def kalshi_historical_markets(
    *,
    series_ticker: str,
    max_pages: int = 25,
) -> list[dict[str, object]]:
    """Load settled Kalshi markets for one verified recurring series."""
    return _paginated(
        KALSHI_BASES,
        "/historical/markets",
        item_key="markets",
        parameters={"series_ticker": series_ticker},
        max_pages=max_pages,
    )


def kalshi_live_markets(
    *,
    series_ticker: str,
    max_pages: int = 25,
) -> list[dict[str, object]]:
    return _paginated(
        KALSHI_BASES,
        "/markets",
        item_key="markets",
        parameters={"series_ticker": series_ticker},
        max_pages=max_pages,
    )


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
        KALSHI_BASES,
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


def polymarket_events(
    *,
    tag_id: int = POLYMARKET_NFL_TAG_ID,
    closed: bool | None = None,
    max_pages: int = 25,
    page_size: int = 100,
) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for page in range(max_pages):
        payload = _get_json(
            POLYMARKET_GAMMA,
            "/events",
            {
                "tag_id": tag_id,
                "related_tags": "true",
                "closed": str(closed).lower() if closed is not None else None,
                "limit": page_size,
                "offset": page * page_size,
            },
        )
        if not isinstance(payload, list):
            raise ValueError("unexpected Polymarket events response")
        events.extend(payload)
        if len(payload) < page_size:
            break
    return events


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


def parse_player_prop_label(label: str) -> dict[str, str | float] | None:
    """Parse only explicit player-game prop labels; reject team and futures text."""
    clean = " ".join(str(label).strip().split())
    match = _THROW_YARDS_PATTERN.fullmatch(clean)
    if match:
        return {
            "player_name": match.group("player").strip(),
            "stat_type": "passing_yards",
            "line": float(match.group("line")),
        }
    for pattern in (_MILESTONE_PATTERN, _OVER_PATTERN):
        match = pattern.fullmatch(clean)
        if match:
            stat = STAT_ALIASES[match.group("stat").lower()]
            return {
                "player_name": match.group("player").strip(),
                "stat_type": stat,
                "line": float(match.group("line")),
            }
    match = _ANYTIME_TD_PATTERN.fullmatch(clean)
    if match:
        return {
            "player_name": match.group("player").strip(),
            "stat_type": "anytime_touchdown",
            "line": 0.5,
        }
    for pattern, stat_type in (
        (_FIRST_TD_PATTERN, "first_touchdown"),
        (_RUSH_TD_PATTERN, "rushing_touchdown"),
    ):
        match = pattern.fullmatch(clean)
        if match:
            player_name = match.group("player").strip()
            if player_name.lower() == "another player" or "d/st" in player_name.lower():
                return None
            return {
                "player_name": player_name,
                "stat_type": stat_type,
                "line": 0.5,
            }
    return None


def kalshi_player_market_catalog(
    markets: Iterable[dict[str, object]],
    *,
    series_ticker: str,
) -> pd.DataFrame:
    rows = []
    expected_stat = KALSHI_PLAYER_SERIES.get(series_ticker)
    for market in markets:
        parsed = parse_player_prop_label(str(market.get("title", "")))
        if parsed is None:
            continue
        if expected_stat and parsed["stat_type"] != expected_stat:
            continue
        rows.append(
            {
                "source": "kalshi",
                "series_ticker": series_ticker,
                "market_id": market.get("ticker"),
                "event_id": market.get("event_ticker"),
                **parsed,
                "open_time": market.get("open_time"),
                "close_time": market.get("close_time"),
                "volume": pd.to_numeric(market.get("volume_fp"), errors="coerce"),
                "open_interest": pd.to_numeric(
                    market.get("open_interest_fp"), errors="coerce"
                ),
            }
        )
    output = pd.DataFrame(rows)
    for column in ("open_time", "close_time"):
        if column in output:
            output[column] = pd.to_datetime(output[column], utc=True, errors="coerce")
    return output


def polymarket_player_market_catalog(
    events: Iterable[dict[str, object]],
) -> pd.DataFrame:
    rows = []
    for event in events:
        for market in event.get("markets", []) or []:
            parsed = parse_player_prop_label(str(market.get("question", "")))
            if parsed is None:
                continue
            rows.append(
                {
                    "source": "polymarket",
                    "market_id": market.get("id"),
                    "event_id": event.get("id"),
                    **parsed,
                    "open_time": market.get("startDate"),
                    "close_time": market.get("closedTime") or market.get("endDate"),
                    "game_start_time": market.get("gameStartTime")
                    or event.get("startDate"),
                    "volume": pd.to_numeric(market.get("volumeNum"), errors="coerce"),
                    "liquidity": pd.to_numeric(
                        market.get("liquidityNum"), errors="coerce"
                    ),
                    "sports_market_type": market.get("sportsMarketType"),
                    "token_ids": market.get("clobTokenIds"),
                }
            )
    output = pd.DataFrame(rows)
    for column in ("open_time", "close_time", "game_start_time"):
        if column in output:
            output[column] = pd.to_datetime(output[column], utc=True, errors="coerce")
    return output


def _candle_value(candle: dict[str, object], field: str) -> float:
    values = candle.get(field) or {}
    if not isinstance(values, dict):
        return float("nan")
    return float(values.get("close_dollars", values.get("close", float("nan"))))


def kalshi_candlesticks_to_quotes(
    market: dict[str, object],
    candlesticks: Iterable[dict[str, object]],
    *,
    game_id: str,
    player_id: str,
    kickoff: str | pd.Timestamp,
) -> pd.DataFrame:
    parsed = parse_player_prop_label(str(market.get("title", "")))
    if parsed is None:
        raise ValueError("Kalshi market is not a recognized player prop")
    rows = []
    for candle in candlesticks:
        bid = _candle_value(candle, "yes_bid")
        ask = _candle_value(candle, "yes_ask")
        trade = _candle_value(candle, "price")
        probability = (
            (bid + ask) / 2.0
            if np.isfinite(bid) and np.isfinite(ask)
            else trade
        )
        rows.append(
            {
                "source": "kalshi",
                "market_id": market.get("ticker"),
                "game_id": game_id,
                "player_id": player_id,
                "player_name": parsed["player_name"],
                "stat_type": parsed["stat_type"],
                "line": parsed["line"],
                "over_probability": probability,
                "bid_probability": bid,
                "ask_probability": ask,
                "observed_at": pd.to_datetime(
                    candle.get("end_period_ts"), unit="s", utc=True
                ),
                "kickoff": kickoff,
                "volume": pd.to_numeric(
                    candle.get("volume_fp", candle.get("volume")), errors="coerce"
                ),
                "open_interest": pd.to_numeric(
                    candle.get("open_interest_fp", candle.get("open_interest")),
                    errors="coerce",
                ),
            }
        )
    return pd.DataFrame(rows)


def polymarket_history_to_quotes(
    market: dict[str, object],
    history: Iterable[dict[str, object]],
    *,
    game_id: str,
    player_id: str,
    kickoff: str | pd.Timestamp,
) -> pd.DataFrame:
    parsed = parse_player_prop_label(str(market.get("question", "")))
    if parsed is None:
        raise ValueError("Polymarket market is not a recognized player prop")
    rows = []
    for point in history:
        rows.append(
            {
                "source": "polymarket",
                "market_id": market.get("id"),
                "game_id": game_id,
                "player_id": player_id,
                "player_name": parsed["player_name"],
                "stat_type": parsed["stat_type"],
                "line": parsed["line"],
                "over_probability": pd.to_numeric(point.get("p"), errors="coerce"),
                "observed_at": pd.to_datetime(point.get("t"), unit="s", utc=True),
                "kickoff": kickoff,
                "volume": pd.to_numeric(market.get("volumeNum"), errors="coerce"),
            }
        )
    return pd.DataFrame(rows)


def _normalized_name(value: object) -> str:
    ascii_name = unicodedata.normalize("NFKD", str(value)).encode(
        "ascii", "ignore"
    ).decode("ascii")
    return re.sub(r"[^a-z0-9]", "", ascii_name.lower())


def _catalog_event_date(frame: pd.DataFrame) -> pd.Series:
    dates = pd.Series(pd.NaT, index=frame.index, dtype="datetime64[ns, UTC]")
    if "game_start_time" in frame:
        dates = pd.to_datetime(frame["game_start_time"], utc=True, errors="coerce")
    if "event_id" in frame:
        encoded = frame["event_id"].astype(str).str.extract(
            r"-(\d{2}[A-Z]{3}\d{2})", expand=False
        )
        parsed = pd.to_datetime(encoded, format="%y%b%d", utc=True, errors="coerce")
        dates = dates.fillna(parsed)
    return dates


def resolve_player_market_catalog(
    catalog: pd.DataFrame,
    player_games: pd.DataFrame,
) -> pd.DataFrame:
    """Resolve source labels to GSIS player-games with auditable exact matching."""
    required = {"player_name"}
    if missing := required.difference(catalog.columns):
        raise ValueError(f"market catalog missing columns: {sorted(missing)}")
    games_required = {"game_id", "gameday", "player_id", "player_name"}
    if missing := games_required.difference(player_games.columns):
        raise ValueError(f"player games missing columns: {sorted(missing)}")

    left = catalog.copy()
    left["_name_key"] = left["player_name"].map(_normalized_name)
    left["_event_date"] = _catalog_event_date(left).dt.date
    right = player_games[["game_id", "gameday", "player_id", "player_name"]].copy()
    right["_name_key"] = right["player_name"].map(_normalized_name)
    right["_event_date"] = pd.to_datetime(
        right["gameday"], utc=True, errors="coerce"
    ).dt.date
    right = right.drop_duplicates(["game_id", "player_id"])
    candidate_counts = right.groupby(["_name_key", "_event_date"]).size()
    unique_keys = candidate_counts[candidate_counts.eq(1)].index
    right = right.set_index(["_name_key", "_event_date"]).loc[unique_keys].reset_index()
    resolved = left.merge(
        right[["_name_key", "_event_date", "game_id", "player_id"]],
        on=["_name_key", "_event_date"],
        how="left",
        validate="many_to_one",
    )
    resolved["match_status"] = np.where(
        resolved["game_id"].notna(), "exact_name_date", "unmatched"
    )
    return resolved.drop(columns=["_name_key", "_event_date"])


def point_in_time_market_features(markets: pd.DataFrame) -> pd.DataFrame:
    """Keep each market's final valid quote known strictly before kickoff."""
    missing = REQUIRED_MARKET_COLUMNS.difference(markets.columns)
    if missing:
        raise ValueError(f"market data missing columns: {sorted(missing)}")
    frame = markets.copy()
    frame["observed_at"] = pd.to_datetime(frame["observed_at"], utc=True)
    frame["kickoff"] = pd.to_datetime(frame["kickoff"], utc=True)
    frame["line"] = pd.to_numeric(frame["line"], errors="coerce")
    frame["over_probability"] = pd.to_numeric(
        frame["over_probability"], errors="coerce"
    )
    valid = (
        frame["observed_at"].lt(frame["kickoff"])
        & frame["line"].notna()
        & frame["over_probability"].between(0.0, 1.0)
    )
    if {"bid_probability", "ask_probability"}.issubset(frame.columns):
        frame["market_spread"] = (
            pd.to_numeric(frame["ask_probability"], errors="coerce")
            - pd.to_numeric(frame["bid_probability"], errors="coerce")
        )
        valid &= frame["market_spread"].ge(0.0) | frame["market_spread"].isna()
    frame = frame[valid].copy()
    frame["quote_age_hours"] = (
        frame["kickoff"] - frame["observed_at"]
    ).dt.total_seconds() / 3600.0
    return (
        frame.sort_values("observed_at")
        .groupby(
            [
                "source",
                "market_id",
                "game_id",
                "player_id",
                "stat_type",
                "line",
            ],
            as_index=False,
            dropna=False,
        )
        .tail(1)
        .reset_index(drop=True)
    )


def _ladder_median(group: pd.DataFrame) -> float:
    ladder = (
        group.groupby("line", as_index=False)["over_probability"]
        .median()
        .sort_values("line")
    )
    lines = ladder["line"].to_numpy(dtype=float)
    probabilities = np.minimum.accumulate(
        ladder["over_probability"].to_numpy(dtype=float)
    )
    if len(lines) == 1:
        return float(lines[0])
    if probabilities[0] <= 0.5:
        return float(lines[0])
    if probabilities[-1] >= 0.5:
        return float(lines[-1])
    return float(np.interp(0.5, probabilities[::-1], lines[::-1]))


def market_consensus_features(markets: pd.DataFrame) -> pd.DataFrame:
    """Convert pre-kickoff quote ladders into source-robust player-stat features."""
    frame = point_in_time_market_features(markets)
    if frame.empty:
        return pd.DataFrame(
            columns=[
                "game_id",
                "player_id",
                "stat_type",
                "market_prop_median",
                "market_prop_sources",
                "market_prop_quotes",
                "market_prop_volume",
                "market_prop_quote_age_hours",
                "market_prop_max_spread",
            ]
        )
    if "volume" not in frame:
        frame["volume"] = np.nan
    if "market_spread" not in frame:
        frame["market_spread"] = np.nan
    source_rows = []
    keys = ["source", "game_id", "player_id", "stat_type"]
    for key, group in frame.groupby(keys, dropna=False):
        source_rows.append(
            {
                **dict(zip(keys, key, strict=True)),
                "source_median": _ladder_median(group),
                "source_quotes": int(len(group)),
                "source_volume": float(group["volume"].fillna(0).sum()),
                "source_quote_age_hours": float(group["quote_age_hours"].min()),
                "source_max_spread": float(group["market_spread"].max()),
            }
        )
    source_frame = pd.DataFrame(source_rows)
    return (
        source_frame.groupby(["game_id", "player_id", "stat_type"], as_index=False)
        .agg(
            market_prop_median=("source_median", "median"),
            market_prop_sources=("source", "nunique"),
            market_prop_quotes=("source_quotes", "sum"),
            market_prop_volume=("source_volume", "sum"),
            market_prop_quote_age_hours=("source_quote_age_hours", "median"),
            market_prop_max_spread=("source_max_spread", "max"),
        )
    )


def attach_market_features(
    player_games: pd.DataFrame,
    market_features: pd.DataFrame,
) -> pd.DataFrame:
    """Attach long-form player-stat market features to canonical player games."""
    output = player_games.copy()
    value_columns = [
        column
        for column in market_features.columns
        if column.startswith("market_prop_")
    ]
    for stat_type, group in market_features.groupby("stat_type", sort=False):
        renamed = {
            column: column.replace("market_prop_", f"market_{stat_type}_", 1)
            for column in value_columns
        }
        output = output.merge(
            group[["game_id", "player_id", *value_columns]].rename(columns=renamed),
            on=["game_id", "player_id"],
            how="left",
            validate="many_to_one",
        )
    return output


def market_feature_columns(target: str) -> list[str]:
    prefix = f"market_{target}_"
    return [
        f"{prefix}median",
        f"{prefix}sources",
        f"{prefix}quotes",
        f"{prefix}volume",
        f"{prefix}quote_age_hours",
        f"{prefix}max_spread",
    ]


def market_admission_audit(
    market_features: pd.DataFrame,
    player_games: pd.DataFrame,
    *,
    development_end_season: int,
    minimum_seasons: int = 3,
    minimum_rows_per_season: int = 100,
) -> pd.DataFrame:
    """Gate market features before any predictive comparison is attempted."""
    joined = market_features.merge(
        player_games[["game_id", "player_id", "season"]].drop_duplicates(),
        on=["game_id", "player_id"],
        how="inner",
        validate="many_to_one",
    )
    joined = joined[joined["season"].le(development_end_season)].copy()
    rows = []
    for stat_type, group in joined.groupby("stat_type"):
        counts = group.groupby("season").size()
        eligible_seasons = counts[counts.ge(minimum_rows_per_season)]
        rows.append(
            {
                "stat_type": stat_type,
                "common_support_rows": int(len(group)),
                "first_season": int(group["season"].min()),
                "last_season": int(group["season"].max()),
                "eligible_seasons": int(len(eligible_seasons)),
                "coverage_gate_passed": bool(len(eligible_seasons) >= minimum_seasons),
            }
        )
    return pd.DataFrame(rows)
