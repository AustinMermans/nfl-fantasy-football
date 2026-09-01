from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import unicodedata
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression

from .draft_strategy import FLEX_POSITIONS, lineup_value, next_pick_for_team, snake_team
from .scoring import score_components


POSITIONS = ("QB", "RB", "WR", "TE", "K")
DEFAULT_ROSTER_SLOTS = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 2, "K": 1}
DEFAULT_ROSTER_MAXIMUMS = {"QB": 4, "RB": 8, "WR": 8, "TE": 3, "K": 3}
MFL_BASE = "https://api.myfantasyleague.com/{season}/export"


@dataclass(frozen=True)
class PolicyConfig:
    model_weight: float
    bench_weight: float
    lookahead: bool = True
    max_adp_reach: float | None = None

    @property
    def name(self) -> str:
        reach = "" if self.max_adp_reach is None else f"_r{self.max_adp_reach:.1f}"
        return (
            f"hybrid_w{self.model_weight:.2f}_b{self.bench_weight:.2f}{reach}_"
            f"{'lookahead' if self.lookahead else 'greedy'}"
        )


def display_name_from_mfl(value: object) -> str:
    name = str(value or "").strip()
    if "," not in name:
        return name
    last, first = (part.strip() for part in name.split(",", 1))
    return f"{first} {last}".strip()


def normalized_player_name(value: object) -> str:
    name = display_name_from_mfl(value).lower()
    name = unicodedata.normalize("NFD", name)
    name = "".join(char for char in name if not unicodedata.combining(char))
    name = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", name)
    return re.sub(r"[^a-z0-9]", "", name)


def normalized_position(value: object) -> str:
    position = str(value or "").upper()
    return "RB" if position == "FB" else "K" if position in {"PK", "PN"} else position


def _read_json(url: str, destination: Path, *, refresh: bool) -> dict[str, object]:
    if destination.exists() and not refresh:
        return json.loads(destination.read_text(encoding="utf-8"))
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = Request(url, headers={"User-Agent": "nfl-fantasy-football/0.1 research"})
    with urlopen(request, timeout=30) as response:
        payload = json.loads(response.read())
    destination.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return payload


def fetch_mfl_adp_snapshot(
    season: int,
    teams: int,
    *,
    cache_dir: Path,
    period: str = "AUG15",
    reception_points: float = 0.5,
    cutoff: int = 1,
    refresh: bool = False,
) -> pd.DataFrame:
    """Fetch a late-preseason MFL market snapshot and interpolate half PPR."""
    if teams not in {8, 10, 12, 14, 16}:
        raise ValueError("MFL ADP supports 8, 10, 12, 14, or 16 teams")
    if not 0.0 <= reception_points <= 1.0:
        raise ValueError("reception_points must be between standard and full PPR")

    root = cache_dir / str(season)
    players_url = (
        f"{MFL_BASE.format(season=season)}?{urlencode({'TYPE': 'players', 'JSON': 1})}"
    )
    players_payload = _read_json(players_url, root / "players.json", refresh=refresh)
    player_rows = players_payload.get("players", {}).get("player", [])  # type: ignore[union-attr]
    players = {
        str(row.get("id")): {
            "name": display_name_from_mfl(row.get("name")),
            "position": normalized_position(row.get("position")),
            "team": str(row.get("team") or "FA"),
        }
        for row in player_rows
    }

    frames: list[pd.DataFrame] = []
    for is_ppr, label in ((0, "standard"), (1, "ppr")):
        params = {
            "TYPE": "adp",
            "PERIOD": period,
            "FCOUNT": teams,
            "IS_PPR": is_ppr,
            "IS_KEEPER": "N",
            "IS_MOCK": 0,
            "CUTOFF": cutoff,
            "DETAILS": "",
            "JSON": 1,
        }
        url = f"{MFL_BASE.format(season=season)}?{urlencode(params)}"
        payload = _read_json(
            url, root / f"adp-{teams}-{label}-{period.lower()}.json", refresh=refresh
        )
        rows = payload.get("adp", {}).get("player", [])  # type: ignore[union-attr]
        frame = pd.DataFrame(rows)
        if frame.empty:
            continue
        frame = frame.rename(columns={"id": "mfl_id", "averagePick": f"adp_{label}"})
        frame[f"adp_{label}"] = pd.to_numeric(frame[f"adp_{label}"], errors="coerce")
        frames.append(frame[["mfl_id", f"adp_{label}"]])
    if not frames:
        return pd.DataFrame()

    combined = frames[0]
    for frame in frames[1:]:
        combined = combined.merge(frame, on="mfl_id", how="outer")
    standard = combined.get("adp_standard", pd.Series(np.nan, index=combined.index))
    ppr = combined.get("adp_ppr", pd.Series(np.nan, index=combined.index))
    combined["adp"] = (1.0 - reception_points) * standard.fillna(
        ppr
    ) + reception_points * ppr.fillna(standard)
    combined["name"] = combined["mfl_id"].map(
        lambda value: players.get(str(value), {}).get("name")
    )
    combined["position"] = combined["mfl_id"].map(
        lambda value: players.get(str(value), {}).get("position")
    )
    combined["team"] = combined["mfl_id"].map(
        lambda value: players.get(str(value), {}).get("team")
    )
    combined["name_key"] = combined["name"].map(normalized_player_name)
    combined["season"] = int(season)
    combined["teams"] = int(teams)
    combined["source"] = f"MFL {period} interpolated half PPR"
    return (
        combined[combined["position"].isin(POSITIONS) & combined["adp"].notna()]
        .sort_values(["adp", "name"])
        .reset_index(drop=True)
    )


def build_historical_player_pool(
    history: pd.DataFrame,
    preseason_predictions: pd.DataFrame,
    adp: pd.DataFrame,
    *,
    season: int,
) -> pd.DataFrame:
    """Join point-in-time market ranks and model forecasts to realized weekly scores."""
    games = history[history["season"].eq(season)].copy()
    games["position"] = games["position"].map(normalized_position)
    games = games[games["position"].isin(POSITIONS)]
    games["name_key"] = games["player_name"].map(normalized_player_name)
    games["actual_points"] = score_components(games)
    weekly = games.groupby(["name_key", "position", "week"], as_index=False).agg(
        actual_points=("actual_points", "sum")
    )
    totals = weekly.groupby(["name_key", "position"], as_index=False).agg(
        actual_points=("actual_points", "sum")
    )
    weekly_maps = weekly.groupby(["name_key", "position"]).apply(
        lambda frame: {
            int(row.week): float(row.actual_points) for row in frame.itertuples()
        },
        include_groups=False,
    )
    totals["actual_weekly"] = [
        weekly_maps.get((row.name_key, row.position), {}) for row in totals.itertuples()
    ]

    model = preseason_predictions[preseason_predictions["season"].eq(season)].copy()
    model["position"] = model["position"].map(normalized_position)
    model["name_key"] = model["player_name"].map(normalized_player_name)
    model = model.sort_values("season_ensemble", ascending=False).drop_duplicates(
        ["name_key", "position"]
    )
    pool = adp.merge(totals, on=["name_key", "position"], how="left").merge(
        model[["name_key", "position", "season_ensemble"]],
        on=["name_key", "position"],
        how="left",
    )
    pool["actual_points"] = pool["actual_points"].fillna(0.0)
    pool["actual_weekly"] = pool["actual_weekly"].map(
        lambda value: value if isinstance(value, dict) else {}
    )
    return pool.reset_index(drop=True)


def add_market_implied_points(
    current: pd.DataFrame, history: pd.DataFrame
) -> pd.DataFrame:
    """Map ADP to expected season points using only earlier player-seasons."""
    output = current.copy()
    output["market_points"] = 0.0
    for position in POSITIONS:
        train = history[
            history["position"].eq(position)
            & history["adp"].notna()
            & history["actual_points"].notna()
        ]
        test_mask = output["position"].eq(position)
        if not test_mask.any():
            continue
        if len(train) < 12:
            output.loc[test_mask, "market_points"] = np.maximum(
                0.0, 220.0 - 1.1 * output.loc[test_mask, "adp"].astype(float)
            )
            continue
        model = IsotonicRegression(increasing=False, out_of_bounds="clip")
        model.fit(
            np.log1p(train["adp"].astype(float)), train["actual_points"].astype(float)
        )
        output.loc[test_mask, "market_points"] = model.predict(
            np.log1p(output.loc[test_mask, "adp"].astype(float))
        )
    return output


def _starter_deficit(
    roster: Sequence[Mapping[str, object]], roster_slots: Mapping[str, int]
) -> int:
    counts = {
        position: sum(player["position"] == position for player in roster)
        for position in POSITIONS
    }
    base_missing = sum(
        max(0, int(roster_slots[position]) - counts[position]) for position in POSITIONS
    )
    flex_used = max(
        0,
        sum(counts[position] for position in FLEX_POSITIONS)
        - sum(
            min(counts[position], int(roster_slots[position]))
            for position in FLEX_POSITIONS
        ),
    )
    return base_missing + max(0, int(roster_slots["FLEX"]) - flex_used)


def _eligible_players(
    available: Sequence[dict[str, object]],
    roster: Sequence[Mapping[str, object]],
    *,
    rounds: int,
    roster_slots: Mapping[str, int],
    roster_maximums: Mapping[str, int],
) -> list[dict[str, object]]:
    remaining_after_pick = rounds - len(roster) - 1
    eligible = []
    for player in available:
        position = str(player["position"])
        if sum(item["position"] == position for item in roster) >= int(
            roster_maximums[position]
        ):
            continue
        if _starter_deficit([*roster, player], roster_slots) <= remaining_after_pick:
            eligible.append(player)
    return eligible or list(available)


def _replacement_points(
    players: Sequence[Mapping[str, object]], teams: int, points_key: str
) -> dict[str, float]:
    ranks = {"QB": teams, "RB": teams * 3, "WR": teams * 3, "TE": teams, "K": teams}
    replacements = {}
    for position in POSITIONS:
        values = sorted(
            (
                float(player[points_key])
                for player in players
                if player["position"] == position
            ),
            reverse=True,
        )
        replacements[position] = (
            values[min(max(ranks[position], 1), len(values)) - 1] if values else 0.0
        )
    return replacements


def _roster_utility(
    roster: Sequence[dict[str, object]],
    *,
    points_key: str,
    bench_weight: float,
    roster_slots: Mapping[str, int],
    replacements: Mapping[str, float],
) -> float:
    starter_value = lineup_value(list(roster), points_key, roster_slots=roster_slots)
    bench_option = sum(
        max(
            0.0,
            float(player[points_key]) - float(replacements[str(player["position"])]),
        )
        for player in roster
    )
    return starter_value + bench_weight * bench_option


def _opponent_pick(
    available: Sequence[dict[str, object]],
    roster: Sequence[dict[str, object]],
    *,
    rounds: int,
    roster_slots: Mapping[str, int],
    roster_maximums: Mapping[str, int],
    room_noise: float = 0.0,
    noise_seed: int = 0,
    overall_pick: int = 1,
) -> dict[str, object]:
    eligible = _eligible_players(
        available,
        roster,
        rounds=rounds,
        roster_slots=roster_slots,
        roster_maximums=roster_maximums,
    )

    def noisy_rank(player: Mapping[str, object]) -> tuple[float, str]:
        if room_noise <= 0:
            return float(player["adp"]), str(player["name"])
        key = f"{noise_seed}|{overall_pick}|{player['mfl_id']}".encode()
        digest = hashlib.blake2b(key, digest_size=16).digest()
        first = max((int.from_bytes(digest[:8], "big") + 0.5) / 2**64, 1e-12)
        second = (int.from_bytes(digest[8:], "big") + 0.5) / 2**64
        shock = np.sqrt(-2.0 * np.log(first)) * np.cos(2.0 * np.pi * second)
        deviation = min(20.0, 3.0 + 0.10 * overall_pick)
        return float(player["adp"]) + room_noise * deviation * float(shock), str(
            player["name"]
        )

    return min(eligible, key=noisy_rank)


def simulate_historical_draft(
    pool: pd.DataFrame,
    *,
    teams: int,
    draft_slot: int,
    rounds: int,
    strategy: str,
    policy: PolicyConfig | None = None,
    roster_slots: Mapping[str, int] | None = None,
    roster_maximums: Mapping[str, int] | None = None,
    room_noise: float = 0.0,
    noise_seed: int = 0,
    lookahead_samples: int = 2,
) -> dict[str, object]:
    """Draft against fixed roster-aware ADP opponents and score realized lineups."""
    if strategy not in {"adp", "hybrid"}:
        raise ValueError("strategy must be adp or hybrid")
    if not 1 <= draft_slot <= teams:
        raise ValueError("draft_slot must be within the league")
    config = policy or PolicyConfig(model_weight=0.0, bench_weight=0.0, lookahead=False)
    slots = dict(roster_slots or DEFAULT_ROSTER_SLOTS)
    maximums = dict(roster_maximums or DEFAULT_ROSTER_MAXIMUMS)
    players = pool.copy()
    players["hybrid_points"] = (
        players["market_points"]
        + config.model_weight
        * (
            players["season_ensemble"].fillna(players["market_points"])
            - players["market_points"]
        )
    ).clip(lower=0.0)
    available = players.to_dict("records")
    rosters: dict[int, list[dict[str, object]]] = {
        team: [] for team in range(1, teams + 1)
    }
    replacements = _replacement_points(available, teams, "hybrid_points")

    def choose_hybrid(overall_pick: int) -> dict[str, object]:
        roster = rosters[draft_slot]
        eligible = _eligible_players(
            available,
            roster,
            rounds=rounds,
            roster_slots=slots,
            roster_maximums=maximums,
        )
        ordered_by_adp = sorted(eligible, key=lambda player: float(player["adp"]))
        if config.max_adp_reach is not None:
            best_adp = float(ordered_by_adp[0]["adp"])
            shortlist = [
                player
                for player in ordered_by_adp
                if float(player["adp"]) <= best_adp + config.max_adp_reach
            ]
        else:
            shortlist = ordered_by_adp[:12]
            for position in POSITIONS:
                leaders = sorted(
                    (player for player in eligible if player["position"] == position),
                    key=lambda player: float(player["hybrid_points"]),
                    reverse=True,
                )[:2]
                shortlist.extend(leaders)
        shortlist = list(
            {str(player["mfl_id"]): player for player in shortlist}.values()
        )

        def candidate_value(candidate: dict[str, object]) -> tuple[float, float, float]:
            immediate = _roster_utility(
                [*roster, candidate],
                points_key="hybrid_points",
                bench_weight=config.bench_weight,
                roster_slots=slots,
                replacements=replacements,
            )
            if not config.lookahead or len(roster) + 4 >= rounds:
                return immediate, immediate, -float(candidate["adp"])
            scenario_values = []
            scenario_count = max(1, lookahead_samples if room_noise > 0 else 1)
            for scenario in range(scenario_count):
                future_available = [
                    player
                    for player in available
                    if player["mfl_id"] != candidate["mfl_id"]
                ]
                future_rosters = {team: list(items) for team, items in rosters.items()}
                future_rosters[draft_slot].append(candidate)
                next_turn = next_pick_for_team(overall_pick, teams, draft_slot)
                decision_seed = noise_seed + 1_000_003 + scenario * 104_729
                for future_pick in range(overall_pick + 1, next_turn):
                    manager = snake_team(future_pick, teams)
                    selected = _opponent_pick(
                        future_available,
                        future_rosters[manager],
                        rounds=rounds,
                        roster_slots=slots,
                        roster_maximums=maximums,
                        room_noise=room_noise,
                        noise_seed=decision_seed,
                        overall_pick=future_pick,
                    )
                    future_rosters[manager].append(selected)
                    future_available.remove(selected)
                partners = _eligible_players(
                    future_available,
                    future_rosters[draft_slot],
                    rounds=rounds,
                    roster_slots=slots,
                    roster_maximums=maximums,
                )
                partner_shortlist = sorted(
                    partners, key=lambda player: float(player["adp"])
                )[:6]
                scenario_values.append(
                    max(
                        (
                            _roster_utility(
                                [*future_rosters[draft_slot], partner],
                                points_key="hybrid_points",
                                bench_weight=config.bench_weight,
                                roster_slots=slots,
                                replacements=replacements,
                            )
                            for partner in partner_shortlist
                        ),
                        default=immediate,
                    )
                )
            return float(np.mean(scenario_values)), immediate, -float(candidate["adp"])

        return max(shortlist, key=candidate_value)

    for overall_pick in range(1, teams * rounds + 1):
        if not available:
            break
        manager = snake_team(overall_pick, teams)
        if manager == draft_slot:
            selected = (
                choose_hybrid(overall_pick)
                if strategy == "hybrid"
                else _opponent_pick(
                    available,
                    rosters[manager],
                    rounds=rounds,
                    roster_slots=slots,
                    roster_maximums=maximums,
                )
            )
        else:
            selected = _opponent_pick(
                available,
                rosters[manager],
                rounds=rounds,
                roster_slots=slots,
                roster_maximums=maximums,
                room_noise=room_noise,
                noise_seed=noise_seed,
                overall_pick=overall_pick,
            )
        rosters[manager].append(selected)
        available.remove(selected)

    weekly_scores: dict[int, dict[int, float]] = {team: {} for team in rosters}
    for team, roster in rosters.items():
        for week in range(1, 18):
            weekly_roster = [
                {**player, "week_points": float(player["actual_weekly"].get(week, 0.0))}
                for player in roster
            ]
            weekly_scores[team][week] = lineup_value(
                weekly_roster, "week_points", roster_slots=slots
            )
    comparisons = []
    for week in range(1, 15):
        mine = weekly_scores[draft_slot][week]
        comparisons.extend(
            1.0
            if mine > weekly_scores[team][week]
            else 0.5
            if mine == weekly_scores[team][week]
            else 0.0
            for team in rosters
            if team != draft_slot
        )
    my_roster = rosters[draft_slot]
    return {
        "strategy": strategy,
        "teams": teams,
        "draft_slot": draft_slot,
        "rounds": rounds,
        "room_noise": room_noise,
        "noise_seed": noise_seed,
        "policy": config.name if strategy == "hybrid" else "naive_adp",
        "h2h_win_rate": float(np.mean(comparisons)) if comparisons else float("nan"),
        "managed_points_week_1_17": float(sum(weekly_scores[draft_slot].values())),
        "roster": [str(player["name"]) for player in my_roster],
        **{
            f"n_{position.lower()}": sum(
                player["position"] == position for player in my_roster
            )
            for position in POSITIONS
        },
    }


def summarize_policy_results(results: pd.DataFrame) -> pd.DataFrame:
    return results.groupby(
        ["split", "teams", "strategy", "policy"], as_index=False
    ).agg(
        drafts=("draft_slot", "count"),
        mean_h2h_win_rate=("h2h_win_rate", "mean"),
        mean_managed_points=("managed_points_week_1_17", "mean"),
    )


def policy_grid(
    model_weights: Iterable[float] = (0.0, 0.25, 0.5, 0.75),
    bench_weights: Iterable[float] = (0.15,),
    adp_reaches: Iterable[float | None] = (None,),
) -> tuple[PolicyConfig, ...]:
    return tuple(
        PolicyConfig(
            model_weight=float(model),
            bench_weight=float(bench),
            lookahead=lookahead,
            max_adp_reach=None if reach is None else float(reach),
        )
        for model in model_weights
        for bench in bench_weights
        for reach in adp_reaches
        for lookahead in (False, True)
    )
