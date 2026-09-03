from __future__ import annotations

from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from hashlib import sha256
import json
from pathlib import Path
import time
from threading import Lock
from typing import Iterable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

import pandas as pd

from .config import PROJECT_ROOT


SLEEPER_API_ROOT = "https://api.sleeper.app/v1"
SEQUENCE_POSITIONS = {"QB", "RB", "WR", "TE", "K", "DEF", "DST"}


def _anonymous_id(kind: str, value: object) -> str:
    return sha256(f"{kind}:{value or ''}".encode()).hexdigest()


@dataclass
class SleeperAPIClient:
    """Small rate-limited client for Sleeper's documented read-only API."""

    base_url: str = SLEEPER_API_ROOT
    timeout: int = 60
    minimum_interval: float = 0.1
    maximum_attempts: int = 4
    _last_request: float = field(default=0.0, init=False, repr=False)
    _rate_lock: Lock = field(default_factory=Lock, init=False, repr=False)

    def get(self, path: str) -> object:
        request = Request(
            f"{self.base_url.rstrip('/')}/{path.lstrip('/')}",
            headers={"User-Agent": "nfl-fantasy-football/0.1"},
        )
        attempts = max(1, self.maximum_attempts)
        failure: Exception = RuntimeError("Sleeper request failed")
        for attempt in range(attempts):
            with self._rate_lock:
                wait = self.minimum_interval - (time.monotonic() - self._last_request)
                if wait > 0:
                    time.sleep(wait)
                self._last_request = time.monotonic()
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    payload = json.load(response)
                return payload
            except HTTPError as error:
                if error.code != 429 and error.code < 500:
                    raise
                failure = error
            except (TimeoutError, URLError) as error:
                failure = error
            if attempt + 1 < attempts:
                time.sleep(max(1.0, self.minimum_interval * 10) * (2**attempt))
        raise failure


def draft_format(draft: Mapping[str, object]) -> dict[str, object]:
    settings = draft.get("settings") or {}
    metadata = draft.get("metadata") or {}
    return {
        "draft_id": _anonymous_id("draft", draft.get("draft_id")),
        "league_id": _anonymous_id("league", draft.get("league_id")),
        "season": int(draft.get("season") or 0),
        "start_time": int(draft.get("start_time") or 0),
        "teams": int(settings.get("teams") or 0),
        "rounds": int(settings.get("rounds") or 0),
        "scoring_type": str(metadata.get("scoring_type") or "unknown").lower(),
        "slots_qb": int(settings.get("slots_qb") or 0),
        "slots_rb": int(settings.get("slots_rb") or 0),
        "slots_wr": int(settings.get("slots_wr") or 0),
        "slots_te": int(settings.get("slots_te") or 0),
        "slots_flex": int(settings.get("slots_flex") or 0),
        "slots_k": int(settings.get("slots_k") or 0),
        "slots_def": int(settings.get("slots_def") or 0),
        "slots_bn": int(settings.get("slots_bn") or 0),
    }


def eligible_redraft_snake(
    draft: Mapping[str, object],
    *,
    seasons: set[int],
    team_sizes: set[int],
    minimum_rounds: int = 12,
) -> bool:
    fields = draft_format(draft)
    metadata = draft.get("metadata") or {}
    settings = draft.get("settings") or {}
    name = str(metadata.get("name") or "").lower()
    description = str(metadata.get("description") or "").lower()
    scoring_type = str(metadata.get("scoring_type") or "").lower()
    idp_slots = sum(
        int(settings.get(key) or 0)
        for key in (
            "slots_idp_flex",
            "slots_dl",
            "slots_lb",
            "slots_db",
            "slots_cb",
            "slots_s",
            "slots_de",
            "slots_dt",
        )
    )
    return bool(
        draft.get("sport") == "nfl"
        and draft.get("type") == "snake"
        and draft.get("status") == "complete"
        and draft.get("league_id")
        and str(draft.get("season_type") or "regular") == "regular"
        and fields["season"] in seasons
        and fields["teams"] in team_sizes
        and int(fields["rounds"]) >= minimum_rounds
        and int(fields["slots_qb"]) == 1
        and int(settings.get("player_type") or 0) == 0
        and int(settings.get("slots_super_flex") or 0) == 0
        and idp_slots == 0
        and "2qb" not in scoring_type
        and "dynasty" not in scoring_type
        and "dynasty" not in name
        and "dynasty" not in description
        and "rookie" not in name
    )


def normalize_sleeper_draft(
    draft: Mapping[str, object], picks: Sequence[Mapping[str, object]]
) -> pd.DataFrame:
    """Normalize picks without retaining usernames or Sleeper user IDs."""
    fields = draft_format(draft)
    rows: list[dict[str, object]] = []
    for pick in sorted(picks, key=lambda row: int(row.get("pick_no") or 0)):
        metadata = pick.get("metadata") or {}
        position = str(metadata.get("position") or "").upper()
        if position not in SEQUENCE_POSITIONS:
            continue
        player_id = str(pick.get("player_id") or metadata.get("player_id") or "")
        if not player_id:
            continue
        rows.append(
            {
                **fields,
                "pick_no": int(pick.get("pick_no") or 0),
                "round": int(pick.get("round") or 0),
                "draft_slot": int(pick.get("draft_slot") or 0),
                "roster_id": int(pick.get("roster_id") or 0),
                "player_id": player_id,
                "position": position,
                "nfl_team": str(metadata.get("team") or ""),
                "is_keeper": bool(pick.get("is_keeper")),
            }
        )
    return pd.DataFrame(rows)


def _sanitized_snapshot(
    draft: Mapping[str, object], picks: Sequence[Mapping[str, object]]
) -> dict[str, object]:
    normalized = normalize_sleeper_draft(draft, picks)
    return {
        "draft": draft_format(draft),
        "picks": normalized.to_dict("records"),
    }


def _write_content_addressed_snapshot(payload: object, raw_dir: Path) -> str:
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    digest = sha256(serialized.encode("utf-8")).hexdigest()
    raw_dir.mkdir(parents=True, exist_ok=True)
    destination = raw_dir / f"{digest}.json"
    if not destination.exists():
        destination.write_text(serialized + "\n", encoding="utf-8")
    return digest


def collect_sleeper_draft_corpus(
    *,
    seasons: Iterable[int],
    user_ids: Iterable[str] = (),
    league_ids: Iterable[str] = (),
    draft_ids: Iterable[str] = (),
    team_sizes: Iterable[int] = (8, 10, 12, 14),
    minimum_rounds: int = 12,
    maximum_drafts: int = 500,
    participant_crawl_depth: int = 0,
    maximum_users: int = 250,
    maximum_workers: int = 8,
    destination: Path | None = None,
    raw_dir: Path | None = None,
    client: SleeperAPIClient | None = None,
) -> tuple[Path, Path]:
    """Collect completed public Sleeper drafts reachable from explicit seeds."""
    season_set = {int(season) for season in seasons}
    team_set = {int(teams) for teams in team_sizes}
    api = client or SleeperAPIClient()
    candidates: dict[str, Mapping[str, object]] = {}
    pick_cache: dict[str, list[Mapping[str, object]]] = {}
    unresolved_seeds = 0

    def fetch_picks(draft_id: str) -> list[Mapping[str, object]]:
        if draft_id not in pick_cache:
            payload = api.get(f"draft/{quote(draft_id, safe='')}/picks")
            pick_cache[draft_id] = (
                [item for item in payload if isinstance(item, Mapping)]
                if isinstance(payload, list)
                else []
            )
        return pick_cache[draft_id]

    def add_drafts(payload: object) -> None:
        if not isinstance(payload, list):
            return
        for item in payload:
            if not isinstance(item, Mapping):
                continue
            draft_id = str(item.get("draft_id") or "")
            if draft_id:
                candidates[draft_id] = item

    for user_id in dict.fromkeys(str(value) for value in user_ids if str(value)):
        encoded = quote(user_id, safe="")
        for season in sorted(season_set):
            try:
                add_drafts(api.get(f"user/{encoded}/drafts/nfl/{season}"))
            except HTTPError as error:
                if error.code != 404:
                    raise
                unresolved_seeds += 1
    for league_id in dict.fromkeys(str(value) for value in league_ids if str(value)):
        try:
            add_drafts(api.get(f"league/{quote(league_id, safe='')}/drafts"))
        except HTTPError as error:
            if error.code != 404:
                raise
            unresolved_seeds += 1
    for draft_id in dict.fromkeys(str(value) for value in draft_ids if str(value)):
        try:
            payload = api.get(f"draft/{quote(draft_id, safe='')}")
        except HTTPError as error:
            if error.code != 404:
                raise
            unresolved_seeds += 1
            continue
        if isinstance(payload, Mapping):
            candidates[draft_id] = payload

    # User IDs are used transiently to discover related public drafts and are
    # never written to either the normalized data or the manifest.
    visited_users = {
        str(value) for value in user_ids if str(value)
    }
    frontier = {
        str(user_id)
        for draft in candidates.values()
        for user_id in (draft.get("draft_order") or {})
        if str(user_id)
    }.difference(visited_users)
    for depth in range(max(0, participant_crawl_depth)):
        current = sorted(frontier)[: max(0, maximum_users - len(visited_users))]
        if not current:
            break
        frontier = set()
        before = set(candidates)
        requests = [
            f"user/{quote(user_id, safe='')}/drafts/nfl/{season}"
            for user_id in current
            for season in sorted(season_set)
        ]
        with ThreadPoolExecutor(max_workers=max(1, maximum_workers)) as executor:
            for payload in executor.map(api.get, requests):
                add_drafts(payload)
        visited_users.update(current)
        if depth + 1 >= participant_crawl_depth:
            continue
        for draft_id in set(candidates).difference(before):
            draft = candidates[draft_id]
            if not eligible_redraft_snake(
                draft,
                seasons=season_set,
                team_sizes=team_set,
                minimum_rounds=minimum_rounds,
            ):
                continue
            frontier.update(
                str(pick.get("picked_by") or "")
                for pick in fetch_picks(draft_id)
                if str(pick.get("picked_by") or "")
                and str(pick.get("picked_by") or "") not in visited_users
            )

    output = destination or PROJECT_ROOT / "data" / "processed" / "sleeper_draft_picks.parquet"
    snapshots = raw_dir or PROJECT_ROOT / "data" / "raw" / "sleeper_drafts"
    eligible = [
        (draft_id, draft)
        for draft_id, draft in candidates.items()
        if eligible_redraft_snake(
            draft,
            seasons=season_set,
            team_sizes=team_set,
            minimum_rounds=minimum_rounds,
        )
    ]
    by_season: dict[int, list[tuple[str, Mapping[str, object]]]] = {}
    for draft_id, draft in eligible:
        by_season.setdefault(int(draft_format(draft)["season"]), []).append(
            (draft_id, draft)
        )
    for season_drafts in by_season.values():
        season_drafts.sort(key=lambda item: int(item[1].get("start_time") or 0))
    selected: list[tuple[str, Mapping[str, object]]] = []
    while any(by_season.values()):
        for season in sorted(by_season):
            if by_season[season]:
                selected.append(by_season[season].pop(0))

    frames: list[pd.DataFrame] = []
    manifest_rows: list[dict[str, object]] = []
    for draft_id, draft in selected:
        if len(frames) >= maximum_drafts:
            break
        picks = fetch_picks(draft_id)
        if any(bool(pick.get("is_keeper")) for pick in picks):
            continue
        fields = draft_format(draft)
        expected = int(fields["teams"]) * int(fields["rounds"])
        if len(picks) < expected * 0.9:
            continue
        frame = normalize_sleeper_draft(draft, picks)
        if frame.empty:
            continue
        digest = _write_content_addressed_snapshot(
            _sanitized_snapshot(draft, picks), snapshots
        )
        frames.append(frame)
        manifest_rows.append(
            {
                **fields,
                "picks": len(frame),
                "snapshot_sha256": digest,
            }
        )

    if not frames:
        raise ValueError("no eligible completed redraft snake drafts found")
    combined = pd.concat(frames, ignore_index=True).sort_values(
        ["season", "start_time", "draft_id", "pick_no"]
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(output, index=False)
    manifest = output.with_suffix(".manifest.json")
    manifest.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(UTC).isoformat(),
                "source": "Sleeper documented read-only API",
                "privacy": "user IDs, usernames, and league names are not retained",
                "discovery": {
                    "candidate_drafts": len(candidates),
                    "eligible_drafts": len(eligible),
                    "participant_crawl_depth": participant_crawl_depth,
                    "users_queried": len(visited_users),
                    "unresolved_seed_requests": unresolved_seeds,
                },
                "drafts": manifest_rows,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return output, manifest
