from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import logsumexp


POSITIONS = ("QB", "RB", "WR", "TE", "K")
FEATURE_NAMES = (
    "market_rank",
    "starter_need",
    "roster_count",
    "recent_position_run",
    "next_turn_demand",
    "starter_need_late",
    "QB",
    "RB",
    "WR",
    "TE",
    "K",
)
FORMAT_COLUMNS = (
    "season",
    "teams",
    "rounds",
    "scoring_type",
    "slots_qb",
    "slots_rb",
    "slots_wr",
    "slots_te",
    "slots_flex",
    "slots_k",
    "slots_def",
    "slots_bn",
)


@dataclass(frozen=True)
class ChoiceObservation:
    features: np.ndarray
    chosen_index: int
    draft_id: str
    pick_no: int


@dataclass(frozen=True)
class PlackettLuceModel:
    coefficients: np.ndarray
    feature_names: tuple[str, ...]

    def probabilities(self, features: np.ndarray) -> np.ndarray:
        utility = np.asarray(features, dtype=float) @ self.coefficients
        utility -= float(np.max(utility))
        weights = np.exp(utility)
        return weights / weights.sum()


def _slots(row: Mapping[str, object]) -> dict[str, int]:
    return {
        position: int(row.get(f"slots_{position.lower()}", 0) or 0)
        for position in POSITIONS
    }


def _starter_need(
    position: str,
    roster_counts: Mapping[str, int],
    slots: Mapping[str, int],
    flex_slots: int,
) -> float:
    if roster_counts.get(position, 0) < slots.get(position, 0):
        return 1.0
    if position not in {"RB", "WR", "TE"}:
        return 0.0
    flex_eligible = sum(roster_counts.get(item, 0) for item in ("RB", "WR", "TE"))
    base_filled = sum(
        min(roster_counts.get(item, 0), slots.get(item, 0))
        for item in ("RB", "WR", "TE")
    )
    return float(flex_eligible - base_filled < flex_slots)


def _next_manager_ids(
    sequence: pd.DataFrame, index: int, current_roster_id: int
) -> list[int]:
    remaining = [int(value) for value in sequence.iloc[index + 1 :]["roster_id"]]
    try:
        next_turn = remaining.index(current_roster_id)
    except ValueError:
        return []
    return remaining[:next_turn]


def choice_features(
    *,
    position: str,
    market_rank: float,
    pick_no: int,
    teams: int,
    rounds: int,
    roster_counts: Mapping[str, int],
    all_roster_counts: Mapping[int, Mapping[str, int]],
    next_manager_ids: Sequence[int],
    recent_positions: Sequence[str],
    slots: Mapping[str, int],
    flex_slots: int,
) -> np.ndarray:
    need = _starter_need(position, roster_counts, slots, flex_slots)
    next_needs = [
        _starter_need(
            position,
            all_roster_counts.get(manager, {}),
            slots,
            flex_slots,
        )
        for manager in next_manager_ids
    ]
    demand = float(np.mean(next_needs)) if next_needs else 0.0
    round_fraction = min(1.0, max(0.0, pick_no / max(1, rounds * teams)))
    return np.asarray(
        [
            -float(market_rank) / 100.0,
            need,
            -float(roster_counts.get(position, 0)) / max(1, rounds),
            sum(item == position for item in recent_positions[-6:]) / 6.0,
            demand,
            need * round_fraction,
            *(float(position == item) for item in POSITIONS),
        ],
        dtype=float,
    )


def market_ranks_from_drafts(picks: pd.DataFrame) -> dict[str, float]:
    ranks = (
        picks.groupby("player_id")["pick_no"]
        .mean()
        .sort_values()
        .to_dict()
    )
    return {str(player_id): float(rank) for player_id, rank in ranks.items()}


def player_positions_from_drafts(picks: pd.DataFrame) -> dict[str, str]:
    modes = picks.groupby("player_id")["position"].agg(
        lambda values: values.mode().iloc[0]
    )
    return {str(player_id): str(position) for player_id, position in modes.items()}


def build_choice_observations(
    picks: pd.DataFrame,
    *,
    market_ranks: Mapping[str, float],
    player_positions: Mapping[str, str],
    choice_set_size: int = 50,
) -> list[ChoiceObservation]:
    required = {
        "draft_id",
        "pick_no",
        "roster_id",
        "player_id",
        "position",
        "teams",
        "rounds",
        "slots_flex",
        *(f"slots_{position.lower()}" for position in POSITIONS),
    }
    missing = required.difference(picks.columns)
    if missing:
        raise ValueError(f"draft picks missing columns: {sorted(missing)}")
    ranked_pool = sorted(
        (
            player
            for player in market_ranks
            if player_positions.get(player) in POSITIONS
        ),
        key=lambda player: (market_ranks[player], str(player)),
    )
    observations: list[ChoiceObservation] = []
    for draft_id, sequence in picks.groupby("draft_id", sort=False):
        sequence = sequence.sort_values("pick_no").reset_index(drop=True)
        available = set(ranked_pool)
        roster_counts: dict[int, dict[str, int]] = {}
        recent_positions: list[str] = []
        for index, row in sequence.iterrows():
            chosen = str(row["player_id"])
            position = str(row["position"])
            manager = int(row["roster_id"])
            manager_counts = roster_counts.setdefault(manager, {})
            if chosen in available and position in POSITIONS:
                candidates = sorted(
                    available,
                    key=lambda player: (market_ranks[player], str(player)),
                )[:choice_set_size]
                if chosen not in candidates:
                    candidates.append(chosen)
                next_managers = _next_manager_ids(sequence, index, manager)
                slots = _slots(row)
                features = np.vstack(
                    [
                        choice_features(
                            position=player_positions[player],
                            market_rank=float(market_ranks[player]),
                            pick_no=int(row["pick_no"]),
                            teams=int(row["teams"]),
                            rounds=int(row["rounds"]),
                            roster_counts=manager_counts,
                            all_roster_counts=roster_counts,
                            next_manager_ids=next_managers,
                            recent_positions=recent_positions,
                            slots=slots,
                            flex_slots=int(row["slots_flex"]),
                        )
                        for player in candidates
                    ]
                )
                observations.append(
                    ChoiceObservation(
                        features=features,
                        chosen_index=candidates.index(chosen),
                        draft_id=str(draft_id),
                        pick_no=int(row["pick_no"]),
                    )
                )
            available.discard(chosen)
            manager_counts[position] = manager_counts.get(position, 0) + 1
            recent_positions.append(position)
    return observations


def fit_plackett_luce(
    observations: Sequence[ChoiceObservation],
    *,
    feature_indices: Sequence[int] | None = None,
    l2: float = 1.0,
) -> PlackettLuceModel:
    if not observations:
        raise ValueError("cannot fit a choice model without observations")
    indices = tuple(feature_indices or range(len(FEATURE_NAMES)))

    def objective(coefficients: np.ndarray) -> tuple[float, np.ndarray]:
        loss = 0.5 * l2 * float(coefficients @ coefficients)
        gradient = l2 * coefficients
        for observation in observations:
            features = observation.features[:, indices]
            utility = features @ coefficients
            probabilities = np.exp(utility - logsumexp(utility))
            loss += float(logsumexp(utility) - utility[observation.chosen_index])
            gradient += probabilities @ features - features[observation.chosen_index]
        return loss, gradient

    fitted = minimize(
        objective,
        np.zeros(len(indices), dtype=float),
        method="L-BFGS-B",
        jac=True,
    )
    if not fitted.success:
        raise RuntimeError(f"Plackett-Luce fit failed: {fitted.message}")
    return PlackettLuceModel(
        coefficients=np.asarray(fitted.x, dtype=float),
        feature_names=tuple(FEATURE_NAMES[index] for index in indices),
    )


def score_choice_model(
    model: PlackettLuceModel,
    observations: Sequence[ChoiceObservation],
    *,
    feature_indices: Sequence[int] | None = None,
) -> dict[str, float]:
    if not observations:
        return {
            "n": 0.0,
            "log_loss": float("nan"),
            "multiclass_brier": float("nan"),
            "top1_accuracy": float("nan"),
            "top5_accuracy": float("nan"),
            "ici": float("nan"),
            "e50": float("nan"),
            "e90": float("nan"),
            "emax": float("nan"),
            "calibration_intercept": float("nan"),
            "calibration_slope": float("nan"),
        }
    indices = tuple(feature_indices or range(len(FEATURE_NAMES)))
    losses: list[float] = []
    briers: list[float] = []
    top1: list[float] = []
    top5: list[float] = []
    calibration_probability: list[float] = []
    calibration_outcome: list[float] = []
    for observation in observations:
        probabilities = model.probabilities(observation.features[:, indices])
        chosen = observation.chosen_index
        losses.append(-float(np.log(max(probabilities[chosen], 1e-12))))
        target = np.zeros(len(probabilities))
        target[chosen] = 1.0
        briers.append(float(np.sum((probabilities - target) ** 2)))
        order = np.argsort(probabilities)[::-1]
        top1.append(float(order[0] == chosen))
        top5.append(float(chosen in order[:5]))
        calibration_probability.extend(probabilities.tolist())
        calibration_outcome.extend(target.tolist())
    probabilities = np.asarray(calibration_probability)
    outcomes = np.asarray(calibration_outcome)
    bins = np.linspace(0.0, 1.0, 11)
    weighted_errors: list[tuple[float, int]] = []
    for lower, upper in zip(bins[:-1], bins[1:]):
        mask = (probabilities >= lower) & (
            probabilities <= upper if upper == 1.0 else probabilities < upper
        )
        if mask.any():
            weighted_errors.append(
                (
                    abs(float(probabilities[mask].mean() - outcomes[mask].mean())),
                    int(mask.sum()),
                )
            )
    expanded_errors = np.concatenate(
        [np.repeat(error, count) for error, count in weighted_errors]
    )
    ici = float(np.mean(expanded_errors))
    logits = np.log(
        np.clip(probabilities, 1e-8, 1 - 1e-8)
        / np.clip(1 - probabilities, 1e-8, 1 - 1e-8)
    )

    def calibration_objective(parameters: np.ndarray) -> tuple[float, np.ndarray]:
        linear = parameters[0] + parameters[1] * logits
        fitted = 1.0 / (1.0 + np.exp(-np.clip(linear, -35, 35)))
        loss = -float(
            np.sum(
                outcomes * np.log(np.clip(fitted, 1e-12, 1.0))
                + (1 - outcomes) * np.log(np.clip(1 - fitted, 1e-12, 1.0))
            )
        )
        residual = fitted - outcomes
        return loss, np.asarray([residual.sum(), residual @ logits])

    calibration = minimize(
        calibration_objective,
        np.asarray([0.0, 1.0]),
        method="L-BFGS-B",
        jac=True,
    )
    return {
        "n": float(len(observations)),
        "log_loss": float(np.mean(losses)),
        "multiclass_brier": float(np.mean(briers)),
        "top1_accuracy": float(np.mean(top1)),
        "top5_accuracy": float(np.mean(top5)),
        "ici": ici,
        "e50": float(np.quantile(expanded_errors, 0.50)),
        "e90": float(np.quantile(expanded_errors, 0.90)),
        "emax": float(np.max(expanded_errors)),
        "calibration_intercept": float(calibration.x[0]),
        "calibration_slope": float(calibration.x[1]),
    }


def chronological_choice_backtest(
    picks: pd.DataFrame,
    *,
    minimum_train_drafts: int = 20,
    test_drafts_per_fold: int = 10,
    choice_set_size: int = 50,
    l2: float = 1.0,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Expanding-time comparison of opponent-aware choice and ADP-only models."""
    rows: list[dict[str, object]] = []
    coefficient_rows: list[dict[str, object]] = []
    for format_key, group in picks.groupby(list(FORMAT_COLUMNS), dropna=False):
        drafts = (
            group.groupby("draft_id")["start_time"].min().sort_values().index.tolist()
        )
        if len(drafts) < minimum_train_drafts + test_drafts_per_fold:
            continue
        for train_end in range(
            minimum_train_drafts,
            len(drafts),
            test_drafts_per_fold,
        ):
            test_ids = drafts[train_end : train_end + test_drafts_per_fold]
            if not test_ids:
                break
            train = group[group["draft_id"].isin(drafts[:train_end])]
            test = group[group["draft_id"].isin(test_ids)]
            ranks = market_ranks_from_drafts(train)
            positions = player_positions_from_drafts(train)
            train_observations = build_choice_observations(
                train,
                market_ranks=ranks,
                player_positions=positions,
                choice_set_size=choice_set_size,
            )
            test_observations = build_choice_observations(
                test,
                market_ranks=ranks,
                player_positions=positions,
                choice_set_size=choice_set_size,
            )
            if not train_observations or not test_observations:
                continue
            models = {
                "adp_only": (
                    fit_plackett_luce(
                        train_observations, feature_indices=[0], l2=l2
                    ),
                    (0,),
                ),
                "opponent_aware": (
                    fit_plackett_luce(train_observations, l2=l2),
                    tuple(range(len(FEATURE_NAMES))),
                ),
            }
            for strategy, (model, indices) in models.items():
                metrics = score_choice_model(
                    model, test_observations, feature_indices=indices
                )
                rows.append(
                    {
                        **dict(zip(FORMAT_COLUMNS, format_key)),
                        "fold": len(drafts[:train_end]),
                        "train_drafts": train_end,
                        "test_drafts": len(test_ids),
                        "known_pick_coverage": len(test_observations)
                        / max(1, int(test["position"].isin(POSITIONS).sum())),
                        "strategy": strategy,
                        **metrics,
                    }
                )
                coefficient_rows.extend(
                    {
                        **dict(zip(FORMAT_COLUMNS, format_key)),
                        "fold": len(drafts[:train_end]),
                        "strategy": strategy,
                        "feature": name,
                        "coefficient": float(value),
                    }
                    for name, value in zip(model.feature_names, model.coefficients)
                )
    return pd.DataFrame(rows), pd.DataFrame(coefficient_rows)
