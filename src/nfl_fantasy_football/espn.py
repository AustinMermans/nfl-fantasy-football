from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import Request, urlopen

from .config import PROJECT_ROOT


ESPN_POSITION = {1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K"}
ESPN_RECEPTIONS_STAT = "53"


def parse_espn_market(payload: dict[str, object], *, season: int) -> list[dict[str, object]]:
    """Extract current ESPN ranks, ADP, and half-PPR expert projections."""
    rows: list[dict[str, object]] = []
    for entry in payload.get("players", []):
        player = entry.get("player", {})
        position = ESPN_POSITION.get(player.get("defaultPositionId"))
        name = player.get("fullName")
        if not position or not name:
            continue
        ranks = player.get("draftRanksByRankType", {})
        ppr_rank = ranks.get("PPR", {}).get("rank")
        standard_rank = ranks.get("STANDARD", {}).get("rank")
        ownership = player.get("ownership", {})
        adp = ownership.get("averageDraftPosition")
        projection = next(
            (
                item
                for item in player.get("stats", [])
                if item.get("seasonId") == season
                and item.get("scoringPeriodId") == 0
                and item.get("statSourceId") == 1
                and item.get("statSplitTypeId") == 0
            ),
            None,
        )
        ppr_points = projection.get("appliedTotal") if projection else None
        receptions = (projection.get("stats", {}) or {}).get(ESPN_RECEPTIONS_STAT, 0.0) if projection else None
        half_ppr_points = (
            float(ppr_points) + 0.5 * float(receptions or 0.0)
            if ppr_points is not None
            else None
        )
        ranks_present = [float(value) for value in (standard_rank, ppr_rank) if value]
        half_ppr_rank = sum(ranks_present) / len(ranks_present) if ranks_present else None
        market_inputs = [
            (0.7, float(adp)) if adp else None,
            (0.3, float(half_ppr_rank)) if half_ppr_rank else None,
        ]
        market_inputs = [item for item in market_inputs if item]
        market_center = (
            sum(weight * value for weight, value in market_inputs)
            / sum(weight for weight, _ in market_inputs)
            if market_inputs
            else None
        )
        rows.append(
            {
                "espnId": int(player["id"]),
                "name": str(name),
                "position": position,
                "adp": round(float(adp), 2) if adp else None,
                "standardRank": int(standard_rank) if standard_rank else None,
                "pprRank": int(ppr_rank) if ppr_rank else None,
                "halfPprRank": round(float(half_ppr_rank), 2) if half_ppr_rank else None,
                "marketCenter": round(float(market_center), 2) if market_center else None,
                "espnHalfPprPoints": round(half_ppr_points, 1) if half_ppr_points is not None else None,
                "injuryStatus": player.get("injuryStatus"),
            }
        )
    return rows


def fetch_espn_market(season: int) -> dict[str, object]:
    endpoint = (
        "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/"
        f"seasons/{season}/segments/0/leaguedefaults/1?view=kona_player_info"
    )
    fantasy_filter = {
        "players": {
            "limit": 2000,
            "sortDraftRanks": {"sortPriority": 100, "sortAsc": True, "value": "PPR"},
        }
    }
    request = Request(
        endpoint,
        headers={
            "User-Agent": "nfl-fantasy-football/0.1",
            "x-fantasy-filter": json.dumps(fantasy_filter, separators=(",", ":")),
        },
    )
    with urlopen(request, timeout=60) as response:
        raw = json.load(response)
    return {
        "generatedAt": datetime.now(UTC).isoformat(),
        "season": season,
        "source": "ESPN Fantasy public player pool",
        "marketModel": "70% ESPN ADP + 30% midpoint of Standard/PPR rank",
        "players": parse_espn_market(raw, season=season),
    }


def write_espn_market(
    season: int,
    *,
    destination: Path | None = None,
) -> Path:
    payload = fetch_espn_market(season)
    output = destination or PROJECT_ROOT / "web" / "market.js"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "window.NFL_MARKET_DATA = "
        + json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
        + ";\n",
        encoding="utf-8",
    )
    return output
