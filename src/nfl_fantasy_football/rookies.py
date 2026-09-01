from __future__ import annotations

import numpy as np
import pandas as pd

from .scoring import score_components


UNDRAFTED_PICK = 300.0
PICK_BANDWIDTH = 0.85
ROOKIE_PRIOR_COLUMNS = (
    "player_id",
    "rookie_prior_mean",
    "rookie_p10",
    "rookie_p50",
    "rookie_p90",
    "rookie_cohort_effective_n",
    "rookie_draft_pick",
    "rookie_role_center",
)


def rookie_role_weights(depth_rank: float) -> tuple[float, float]:
    """Return cohort and current-role weights for a rookie forecast.

    Draft capital remains useful for starters, while a reserve designation is
    direct evidence that the player does not currently own a full-season role.
    """
    if pd.notna(depth_rank) and float(depth_rank) <= 1:
        return 0.5, 0.5
    return 0.25, 0.75


def weighted_quantile(
    values: pd.Series, weights: pd.Series, quantiles: tuple[float, ...]
) -> np.ndarray:
    """Return deterministic weighted quantiles for nonnegative cohort outcomes."""
    clean = pd.DataFrame({"value": values, "weight": weights}).dropna()
    clean = clean[clean["weight"].gt(0)].sort_values("value")
    if clean.empty:
        return np.full(len(quantiles), np.nan)
    cumulative = clean["weight"].cumsum()
    cumulative = (cumulative - 0.5 * clean["weight"]) / clean["weight"].sum()
    return np.interp(quantiles, cumulative, clean["value"])


def historical_rookie_seasons(history: pd.DataFrame) -> pd.DataFrame:
    """Aggregate actual rookie fantasy seasons without using future-season data."""
    frame = history.copy()
    frame["actual_points"] = score_components(frame)
    rookie = frame[frame["draft_year"].eq(frame["season"]) | frame["years_exp"].eq(0)]
    return rookie.groupby(
        ["season", "player_id", "player_name", "position"], as_index=False
    ).agg(
        actual_points=("actual_points", "sum"),
        games=("game_id", "nunique"),
        draft_pick=("draft_pick", "first"),
    )


def rookie_prior_table(
    history: pd.DataFrame,
    current_totals: pd.DataFrame,
    current_roles: pd.DataFrame,
) -> pd.DataFrame:
    """Estimate rookie predictive ranges from draft capital and current depth role.

    Draft capital selects a smooth historical rookie cohort. Current depth rank is
    incorporated as a second noisy signal using experienced players on today's
    depth chart. The returned range is predictive, not a confidence interval.
    """
    outcomes = historical_rookie_seasons(history)
    roles = current_roles.drop_duplicates("player_id").copy()
    totals = current_totals.merge(roles, on="player_id", validate="one_to_one")
    experienced = totals[totals["player_games_prior"].gt(0)]
    role_summary = experienced.groupby(["position", "depth_rank"])[
        "predicted_fantasy_points"
    ].median()
    position_summary = experienced.groupby("position")[
        "predicted_fantasy_points"
    ].median()

    rows: list[dict[str, object]] = []
    rookie_mask = totals.get("is_rookie", totals["player_games_prior"].eq(0)).astype(bool)
    for player in totals[rookie_mask].itertuples(index=False):
        cohort = outcomes[outcomes["position"].eq(player.position)].copy()
        if cohort.empty:
            continue
        target_pick = float(
            player.draft_pick if pd.notna(player.draft_pick) else UNDRAFTED_PICK
        )
        cohort_pick = cohort["draft_pick"].fillna(UNDRAFTED_PICK).clip(lower=1.0)
        distance = np.abs(np.log1p(cohort_pick) - np.log1p(target_pick))
        weights = np.exp(-distance / PICK_BANDWIDTH)
        q10, q50, q90 = weighted_quantile(
            cohort["actual_points"], weights, (0.10, 0.50, 0.90)
        )
        cohort_mean = float(np.average(cohort["actual_points"], weights=weights))
        effective_n = float(weights.sum() ** 2 / np.square(weights).sum())

        role_key = (player.position, player.depth_rank)
        if role_key in role_summary.index:
            role_center = float(role_summary.loc[role_key])
        else:
            role_center = float(position_summary.loc[player.position])
        cohort_weight, role_weight = rookie_role_weights(player.depth_rank)
        center = cohort_mean * cohort_weight + role_center * role_weight
        shift = center - q50
        rows.append(
            {
                "player_id": player.player_id,
                "rookie_prior_mean": max(0.0, center),
                "rookie_p10": max(0.0, q10 + shift),
                "rookie_p50": max(0.0, center),
                "rookie_p90": max(center, q90 + shift),
                "rookie_cohort_effective_n": effective_n,
                "rookie_draft_pick": target_pick,
                "rookie_role_center": role_center,
            }
        )
    return pd.DataFrame(rows, columns=ROOKIE_PRIOR_COLUMNS)
