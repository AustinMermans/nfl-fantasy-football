from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import Request, urlopen

from .config import PROJECT_ROOT


POSITIONS = {"QB", "RB", "WR", "TE", "K"}


def parse_sleeper_market(payload: list[dict[str, object]]) -> list[dict[str, object]]:
    """Extract redraft ADP from Sleeper's current season projection feed."""
    rows: list[dict[str, object]] = []
    for entry in payload:
        player = entry.get("player") or {}
        stats = entry.get("stats") or {}
        position = str(player.get("position") or "").upper()
        first = str(player.get("first_name") or "").strip()
        last = str(player.get("last_name") or "").strip()
        name = f"{first} {last}".strip()
        adp = stats.get("adp_half_ppr")
        try:
            numeric_adp = float(adp)
        except (TypeError, ValueError):
            continue
        if position not in POSITIONS or not name or not 0 < numeric_adp < 999:
            continue
        rows.append(
            {
                "sleeperId": str(entry.get("player_id") or ""),
                "name": name,
                "position": position,
                "team": player.get("team") or player.get("team_abbr"),
                "adp": round(numeric_adp, 2),
            }
        )
    return sorted(rows, key=lambda row: (float(row["adp"]), str(row["name"])))


def fetch_sleeper_market(season: int) -> dict[str, object]:
    endpoint = f"https://api.sleeper.com/projections/nfl/{season}?season_type=regular"
    request = Request(endpoint, headers={"User-Agent": "nfl-fantasy-football/0.1"})
    with urlopen(request, timeout=60) as response:
        raw = json.load(response)
    return {
        "generatedAt": datetime.now(UTC).isoformat(),
        "season": season,
        "source": "Sleeper current season projection feed",
        "field": "adp_half_ppr",
        "scope": "Current cross-check only; not a historical backtest series",
        "players": parse_sleeper_market(raw),
    }


def write_sleeper_market(season: int, *, destination: Path | None = None) -> Path:
    payload = fetch_sleeper_market(season)
    output = destination or PROJECT_ROOT / "web" / "sleeper.js"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "window.NFL_SLEEPER_MARKET = "
        + json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
        + ";\n",
        encoding="utf-8",
    )
    return output
