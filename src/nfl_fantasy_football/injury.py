from __future__ import annotations

import numpy as np
import pandas as pd


POSITIONS = ("QB", "RB", "WR", "TE", "K")
FALLBACK_HAZARD = {
    "QB": 0.0199,
    "RB": 0.0296,
    "WR": 0.0273,
    "TE": 0.0257,
    "K": 0.0175,
}
FALLBACK_DURATION = {
    "QB": 1.93,
    "RB": 2.02,
    "WR": 1.97,
    "TE": 1.89,
    "K": 1.67,
}


def _position(values: pd.Series) -> pd.Series:
    return values.replace({"FB": "RB"})


def _size_group(values: pd.Series, low: float, high: float) -> pd.Series:
    return pd.Series(
        np.select([values.le(low), values.ge(high)], ["low", "high"], default="mid"),
        index=values.index,
    ).where(values.notna(), "unknown")


def estimate_injury_risk_profiles(
    history: pd.DataFrame,
    current_players: pd.DataFrame,
    *,
    player_prior_games: float = 34.0,
    duration_prior_episodes: float = 2.0,
    size_prior_games: float = 300.0,
) -> pd.DataFrame:
    """Estimate empirical-Bayes injury onset and duration for current players.

    An injury absence requires zero snaps plus a contemporaneous injury report.
    Position supplies the baseline, a 34-game prior shrinks player recurrence,
    episode length represents prior severity, and BMI terciles supply an
    empirically estimated within-position size multiplier.
    """
    required = {
        "player_id",
        "position",
        "season",
        "week",
        "played",
        "report_primary_injury",
        "practice_primary_injury",
        "report_status",
    }
    missing = required.difference(history.columns)
    if missing:
        raise ValueError(f"history missing columns: {sorted(missing)}")
    if not {"player_id", "position"}.issubset(current_players.columns):
        raise ValueError("current_players must contain player_id and position")

    frame = history.copy()
    frame["position"] = _position(frame["position"])
    frame = frame[frame["position"].isin(POSITIONS)].copy()
    reported = frame["report_primary_injury"].notna() | frame[
        "practice_primary_injury"
    ].notna()
    severe_status = frame["report_status"].astype("string").str.lower().isin(
        ("out", "doubtful")
    )
    frame["injury_absent"] = frame["played"].lt(0.5) & (reported | severe_status)
    frame = frame.sort_values(["player_id", "season", "week"])
    previous_absent = frame.groupby(["player_id", "season"], observed=True)[
        "injury_absent"
    ].shift(fill_value=False)
    frame["injury_start"] = frame["injury_absent"] & ~previous_absent

    if "height" not in frame:
        frame["height"] = np.nan
    if "weight" not in frame:
        frame["weight"] = np.nan
    frame["bmi"] = 703.0 * pd.to_numeric(
        frame["weight"], errors="coerce"
    ) / pd.to_numeric(frame["height"], errors="coerce").pow(2)

    position_stats = frame.groupby("position", observed=True).agg(
        exposure=("injury_start", "size"),
        starts=("injury_start", "sum"),
        missed=("injury_absent", "sum"),
    )
    position_stats["hazard"] = position_stats["starts"] / position_stats["exposure"]
    position_stats["duration"] = position_stats["missed"] / position_stats[
        "starts"
    ].replace(0, np.nan)

    size_thresholds: dict[str, tuple[float, float]] = {}
    size_factors: dict[tuple[str, str], float] = {}
    for position in POSITIONS:
        rows = frame[frame["position"].eq(position)].copy()
        valid_bmi = rows["bmi"].dropna()
        if valid_bmi.empty:
            size_thresholds[position] = (float("nan"), float("nan"))
            continue
        low, high = valid_bmi.quantile([1 / 3, 2 / 3]).tolist()
        size_thresholds[position] = (float(low), float(high))
        rows["size_group"] = _size_group(rows["bmi"], low, high)
        baseline = float(position_stats.loc[position, "hazard"])
        grouped = rows.groupby("size_group", observed=True).agg(
            exposure=("injury_start", "size"), starts=("injury_start", "sum")
        )
        for group, values in grouped.iterrows():
            rate = (float(values["starts"]) + size_prior_games * baseline) / (
                float(values["exposure"]) + size_prior_games
            )
            size_factors[(position, str(group))] = rate / baseline if baseline else 1.0

    player_stats = frame.groupby("player_id", observed=True).agg(
        exposure=("injury_start", "size"),
        history_episodes=("injury_start", "sum"),
        history_missed_games=("injury_absent", "sum"),
    )
    latest_size = (
        frame.sort_values(["season", "week"])
        .groupby("player_id", observed=True)[["height", "weight", "bmi"]]
        .last()
    )
    current = current_players.copy()
    current["position"] = _position(current["position"])
    current = current[current["position"].isin(POSITIONS)].drop_duplicates(
        "player_id", keep="last"
    )
    current = current.set_index("player_id").join(
        player_stats, how="left", rsuffix="_history"
    )
    current = current.join(latest_size, how="left", rsuffix="_history")
    for measurement in ("height", "weight", "bmi"):
        history_column = f"{measurement}_history"
        if history_column in current:
            if measurement not in current:
                current[measurement] = current[history_column]
            else:
                current[measurement] = current[measurement].fillna(
                    current[history_column]
                )
            current = current.drop(columns=history_column)
    computed_bmi = 703.0 * pd.to_numeric(
        current["weight"], errors="coerce"
    ) / pd.to_numeric(current["height"], errors="coerce").pow(2)
    if "bmi" not in current:
        current["bmi"] = computed_bmi
    else:
        current["bmi"] = current["bmi"].fillna(computed_bmi)
    current[["exposure", "history_episodes", "history_missed_games"]] = current[
        ["exposure", "history_episodes", "history_missed_games"]
    ].fillna(0.0)

    records = []
    for player_id, row in current.iterrows():
        position = str(row["position"])
        baseline_hazard = float(
            position_stats["hazard"].get(position, FALLBACK_HAZARD[position])
        )
        baseline_duration = float(
            position_stats["duration"].get(position, FALLBACK_DURATION[position])
        )
        if not np.isfinite(baseline_hazard) or baseline_hazard <= 0:
            baseline_hazard = FALLBACK_HAZARD[position]
        if not np.isfinite(baseline_duration) or baseline_duration < 1:
            baseline_duration = FALLBACK_DURATION[position]
        low, high = size_thresholds.get(position, (float("nan"), float("nan")))
        bmi = float(row["bmi"]) if pd.notna(row.get("bmi")) else float("nan")
        size_group = str(_size_group(pd.Series([bmi]), low, high).iloc[0])
        size_multiplier = float(size_factors.get((position, size_group), 1.0))
        history_hazard = (
            float(row["history_episodes"]) + player_prior_games * baseline_hazard
        ) / (float(row["exposure"]) + player_prior_games)
        # Inactive/IR weeks can be absent from the active-roster exposure table.
        # Do not interpret a zero recorded episode count as evidence below the
        # position baseline until full roster-week exposure is available.
        recurrence_hazard = max(baseline_hazard, history_hazard)
        weekly_hazard = float(
            np.clip(
                max(0.85 * baseline_hazard, recurrence_hazard * size_multiplier),
                0.005,
                0.08,
            )
        )
        mean_duration = (
            float(row["history_missed_games"])
            + duration_prior_episodes * baseline_duration
        ) / (float(row["history_episodes"]) + duration_prior_episodes)
        mean_duration = float(np.clip(mean_duration, 1.0, 6.0))
        unavailable_share = weekly_hazard * mean_duration / (
            1.0 + weekly_hazard * (mean_duration - 1.0)
        )
        records.append(
            {
                "player_id": player_id,
                "injury_weekly_hazard": weekly_hazard,
                "injury_mean_duration": mean_duration,
                "injury_expected_missed_games": 17.0 * unavailable_share,
                "injury_baseline_hazard": baseline_hazard,
                "injury_history_episodes": int(row["history_episodes"]),
                "injury_history_missed_games": int(row["history_missed_games"]),
                "injury_size_multiplier": size_multiplier,
                "height": (
                    float(row["height"]) if pd.notna(row.get("height")) else np.nan
                ),
                "weight": (
                    float(row["weight"]) if pd.notna(row.get("weight")) else np.nan
                ),
                "bmi": bmi,
            }
        )
    return pd.DataFrame.from_records(records)
