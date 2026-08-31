from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pandas as pd


DEFAULT_ROSTER_SLOTS = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "K": 1}
FLEX_POSITIONS = ("RB", "WR", "TE")


def starter_counts(
    frame: pd.DataFrame,
    points_column: str,
    *,
    teams: int = 12,
    roster_slots: Mapping[str, int] | None = None,
) -> dict[str, int]:
    """Derive league-wide starter demand, including flex, from the projections."""
    slots = dict(roster_slots or DEFAULT_ROSTER_SLOTS)
    counts = {
        position: teams * int(slots.get(position, 0))
        for position in ("QB", "RB", "WR", "TE", "K")
    }
    flex_pool: list[tuple[float, str]] = []
    for position in FLEX_POSITIONS:
        ordered = frame.loc[frame["position"].eq(position), points_column].sort_values(
            ascending=False
        )
        base_count = min(counts[position], len(ordered))
        flex_pool.extend((float(points), position) for points in ordered.iloc[base_count:])
    flex_pool.sort(reverse=True)
    for _, position in flex_pool[: teams * int(slots.get("FLEX", 0))]:
        counts[position] += 1
    return counts


def format_draft_metrics(
    frame: pd.DataFrame,
    points_column: str,
    *,
    teams: int = 12,
    roster_slots: Mapping[str, int] | None = None,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Rank players by format-derived value over the last projected starter."""
    counts = starter_counts(
        frame, points_column, teams=teams, roster_slots=roster_slots
    )
    replacement_by_position: dict[str, float] = {}
    for position, position_frame in frame.groupby("position"):
        ordered = position_frame.sort_values(points_column, ascending=False)
        replacement_rank = min(max(counts.get(position, 1), 1), len(ordered))
        replacement_by_position[position] = float(
            ordered.iloc[replacement_rank - 1][points_column]
        )

    replacement = frame["position"].map(replacement_by_position)
    value = frame[points_column] - replacement
    ranked = frame.assign(_draft_value=value).sort_values(
        ["_draft_value", points_column, "player_name"],
        ascending=[False, False, True],
    )
    rank_by_player = {
        player_id: rank
        for rank, player_id in enumerate(ranked["player_id"], start=1)
    }
    return replacement, value, frame["player_id"].map(rank_by_player).astype(int)


def snake_team(overall_pick: int, teams: int) -> int:
    """Return the one-indexed team on the clock for a one-indexed overall pick."""
    if overall_pick < 1 or teams < 2:
        raise ValueError("overall_pick must be positive and teams must be at least two")
    round_number = (overall_pick - 1) // teams + 1
    position_in_round = (overall_pick - 1) % teams + 1
    return position_in_round if round_number % 2 else teams - position_in_round + 1


def next_pick_for_team(after_pick: int, teams: int, draft_slot: int) -> int:
    """Find a team's next snake pick strictly after ``after_pick``."""
    if not 1 <= draft_slot <= teams:
        raise ValueError("draft_slot must be within the league")
    candidate = after_pick + 1
    while snake_team(candidate, teams) != draft_slot:
        candidate += 1
    return candidate


def picks_until_next_turn(current_pick: int, teams: int, draft_slot: int) -> int:
    """Count opponent selections after the current selection and before the next turn."""
    return next_pick_for_team(current_pick, teams, draft_slot) - current_pick - 1


def lineup_value(
    players: list[Mapping[str, Any]],
    points_key: str,
    *,
    roster_slots: Mapping[str, int] | None = None,
    replacements: Mapping[str, float] | None = None,
) -> float:
    """Score the best legal starting lineup, optionally padding empty slots."""
    slots = dict(roster_slots or DEFAULT_ROSTER_SLOTS)
    pools: dict[str, list[float]] = {}
    for position in ("QB", "RB", "WR", "TE", "K"):
        pools[position] = sorted(
            [float(player[points_key]) for player in players if player["position"] == position],
            reverse=True,
        )
        if replacements is not None:
            padding = slots[position] + (slots["FLEX"] if position in FLEX_POSITIONS else 0)
            pools[position].extend([float(replacements[position])] * padding)
            pools[position].sort(reverse=True)

    total = 0.0
    flex_pool: list[float] = []
    for position, values in pools.items():
        count = slots[position]
        total += sum(values[:count])
        if position in FLEX_POSITIONS:
            flex_pool.extend(values[count:])
    total += sum(sorted(flex_pool, reverse=True)[: slots["FLEX"]])
    return total


def simulate_draft_policy(
    players: list[dict[str, Any]],
    *,
    teams: int = 12,
    draft_slot: int = 1,
    rounds: int = 12,
    strategy: str = "dynamic",
    scenario: str = "balanced",
    roster_slots: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    """Run a deterministic preseason draft and score its realized starting lineup."""
    if strategy not in {"dynamic", "greedy", "format", "raw_points"}:
        raise ValueError(f"unknown strategy: {strategy}")
    slots = dict(roster_slots or DEFAULT_ROSTER_SLOTS)
    frame = pd.DataFrame(
        {
            "player_id": [player["id"] for player in players],
            "player_name": [player["name"] for player in players],
            "position": [player["position"] for player in players],
            "projected": [player["projectedPoints"] for player in players],
        }
    )
    replacement, value, rank = format_draft_metrics(
        frame, "projected", teams=teams, roster_slots=slots
    )
    metrics = {
        player_id: {
            "replacement": float(replacement.iloc[index]),
            "value": float(value.iloc[index]),
            "rank": int(rank.iloc[index]),
        }
        for index, player_id in enumerate(frame["player_id"])
    }
    replacements = {
        player["position"]: metrics[player["id"]]["replacement"] for player in players
    }
    available = list(players)
    roster: list[dict[str, Any]] = []

    def opponent_order(pool: list[dict[str, Any]], overall_pick: int) -> list[dict[str, Any]]:
        forced = "RB" if scenario == "rb_rush" else "WR" if scenario == "wr_rush" else None
        eligible = (
            [player for player in pool if player["position"] == forced]
            if forced and overall_pick <= teams * 2
            else pool
        )
        return sorted(eligible or pool, key=lambda player: metrics[player["id"]]["rank"])

    def dynamic_choice(overall_pick: int) -> dict[str, Any]:
        next_turn = next_pick_for_team(overall_pick, teams, draft_slot)
        intervening = next_turn - overall_pick - 1
        baseline_removed = {
            player["id"]
            for player in opponent_order(available, overall_pick + 1)[:intervening]
        }
        candidates = []
        position_leaders = [
            max(
                (player for player in available if player["position"] == position),
                key=lambda player: player["projectedPoints"],
                default=None,
            )
            for position in ("QB", "RB", "WR", "TE", "K")
        ]
        roster_counts = {
            position: sum(player["position"] == position for player in roster)
            for position in ("QB", "RB", "WR", "TE", "K")
        }
        missing_base = {
            position: max(0, slots[position] - roster_counts[position])
            for position in roster_counts
        }
        flex_eligible = sum(roster_counts[position] for position in FLEX_POSITIONS)
        base_flex_used = sum(
            min(roster_counts[position], slots[position]) for position in FLEX_POSITIONS
        )
        missing_flex = max(0, slots["FLEX"] - max(0, flex_eligible - base_flex_used))
        remaining_picks = rounds - len(roster)
        must_fill = remaining_picks <= sum(missing_base.values()) + missing_flex
        if must_fill:
            position_leaders = [
                player
                for player in position_leaders
                if player is not None
                and (
                    missing_base[player["position"]] > 0
                    or (missing_flex > 0 and player["position"] in FLEX_POSITIONS)
                )
            ]
        for candidate in (player for player in position_leaders if player is not None):
            future_pool = [player for player in available if player["id"] != candidate["id"]]
            for step in range(intervening):
                if not future_pool:
                    break
                chosen = opponent_order(future_pool, overall_pick + step + 1)[0]
                future_pool.remove(chosen)
            next_options = []
            for position in ("QB", "RB", "WR", "TE", "K"):
                position_pool = [player for player in future_pool if player["position"] == position]
                if position_pool:
                    next_options.append(
                        max(position_pool, key=lambda player: player["projectedPoints"])
                    )
            two_pick_value = max(
                (
                    lineup_value(
                        roster + [candidate, next_player],
                        "projectedPoints",
                        roster_slots=slots,
                        replacements=replacements,
                    )
                    for next_player in next_options
                ),
                default=lineup_value(
                    roster + [candidate],
                    "projectedPoints",
                    roster_slots=slots,
                    replacements=replacements,
                ),
            )
            same_position = [
                player for player in future_pool if player["position"] == candidate["position"]
            ]
            next_points = max(
                (float(player["projectedPoints"]) for player in same_position), default=0.0
            )
            candidates.append(
                (
                    two_pick_value,
                    candidate["id"] in baseline_removed,
                    float(candidate["projectedPoints"]) - next_points,
                    metrics[candidate["id"]]["value"],
                    float(candidate["projectedPoints"]),
                    candidate,
                )
            )
        return max(candidates, key=lambda item: item[:-1])[-1]

    def greedy_choice() -> dict[str, Any]:
        leaders = [
            max(
                (player for player in available if player["position"] == position),
                key=lambda player: player["projectedPoints"],
                default=None,
            )
            for position in ("QB", "RB", "WR", "TE", "K")
        ]
        roster_counts = {
            position: sum(player["position"] == position for player in roster)
            for position in ("QB", "RB", "WR", "TE", "K")
        }
        missing_base = {
            position: max(0, slots[position] - roster_counts[position])
            for position in roster_counts
        }
        flex_eligible = sum(roster_counts[position] for position in FLEX_POSITIONS)
        base_flex_used = sum(
            min(roster_counts[position], slots[position]) for position in FLEX_POSITIONS
        )
        missing_flex = max(0, slots["FLEX"] - max(0, flex_eligible - base_flex_used))
        if rounds - len(roster) <= sum(missing_base.values()) + missing_flex:
            leaders = [
                player
                for player in leaders
                if player is not None
                and (
                    missing_base[player["position"]] > 0
                    or (missing_flex > 0 and player["position"] in FLEX_POSITIONS)
                )
            ]
        return max(
            (player for player in leaders if player is not None),
            key=lambda player: (
                lineup_value(
                    roster + [player],
                    "projectedPoints",
                    roster_slots=slots,
                    replacements=replacements,
                ),
                metrics[player["id"]]["value"],
            ),
        )

    for overall_pick in range(1, teams * rounds + 1):
        if not available:
            break
        if snake_team(overall_pick, teams) == draft_slot:
            if strategy == "dynamic":
                selected = dynamic_choice(overall_pick)
            elif strategy == "greedy":
                selected = greedy_choice()
            elif strategy == "format":
                selected = min(available, key=lambda player: metrics[player["id"]]["rank"])
            else:
                selected = max(available, key=lambda player: player["projectedPoints"])
            roster.append(selected)
        else:
            selected = opponent_order(available, overall_pick)[0]
        available.remove(selected)

    position_counts = {
        position: sum(player["position"] == position for player in roster)
        for position in ("QB", "RB", "WR", "TE", "K")
    }
    return {
        "strategy": strategy,
        "scenario": scenario,
        "draft_slot": draft_slot,
        "projected_starter_points": round(
            lineup_value(roster, "projectedPoints", roster_slots=slots), 2
        ),
        "actual_starter_points": round(
            lineup_value(roster, "actualPoints", roster_slots=slots), 2
        ),
        **{f"n_{position.lower()}": count for position, count in position_counts.items()},
    }
