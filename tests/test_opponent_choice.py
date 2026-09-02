import numpy as np
import pandas as pd

from nfl_fantasy_football.opponent_choice import (
    ChoiceObservation,
    _next_manager_ids,
    chronological_choice_backtest,
    fit_plackett_luce,
    score_choice_model,
)


def test_plackett_luce_recovers_roster_need_signal_beyond_equal_adp() -> None:
    observations = []
    for index in range(40):
        features = np.zeros((2, 11), dtype=float)
        features[0, 1] = 1.0
        observations.append(
            ChoiceObservation(
                features=features,
                chosen_index=0,
                draft_id=f"draft-{index}",
                pick_no=10,
            )
        )

    adp = fit_plackett_luce(observations, feature_indices=[0])
    aware = fit_plackett_luce(observations)
    adp_score = score_choice_model(adp, observations, feature_indices=[0])
    aware_score = score_choice_model(aware, observations)

    assert aware.coefficients[1] > 0
    assert aware_score["log_loss"] < adp_score["log_loss"]
    assert aware_score["top1_accuracy"] > adp_score["top1_accuracy"]
    assert np.isfinite(aware_score["calibration_slope"])
    assert aware_score["emax"] >= aware_score["e90"] >= aware_score["e50"]


def test_next_manager_ids_returns_empty_when_manager_has_no_next_turn() -> None:
    sequence = pd.DataFrame({"roster_id": [1, 2, 2, 1]})

    assert _next_manager_ids(sequence, 0, 1) == [2, 2]
    assert _next_manager_ids(sequence, 3, 1) == []


def _synthetic_draft_corpus(drafts: int = 8) -> pd.DataFrame:
    rows = []
    players = [
        ("rb1", "RB"),
        ("rb2", "RB"),
        ("qb1", "QB"),
        ("qb2", "QB"),
        ("wr1", "WR"),
        ("wr2", "WR"),
        ("te1", "TE"),
        ("te2", "TE"),
    ]
    for draft in range(drafts):
        for pick_no, (player_id, position) in enumerate(players, start=1):
            draft_slot = 1 if pick_no in {1, 4, 5, 8} else 2
            rows.append(
                {
                    "draft_id": f"draft-{draft}",
                    "start_time": 1_000 + draft,
                    "season": 2025,
                    "teams": 2,
                    "rounds": 4,
                    "scoring_type": "half_ppr",
                    "slots_qb": 1,
                    "slots_rb": 1,
                    "slots_wr": 1,
                    "slots_te": 1,
                    "slots_flex": 0,
                    "slots_k": 0,
                    "slots_def": 0,
                    "slots_bn": 0,
                    "pick_no": pick_no,
                    "roster_id": draft_slot,
                    "draft_slot": draft_slot,
                    "player_id": player_id,
                    "position": position,
                }
            )
    return pd.DataFrame(rows)


def test_chronological_backtest_uses_expanding_earlier_drafts() -> None:
    results, coefficients = chronological_choice_backtest(
        _synthetic_draft_corpus(),
        minimum_train_drafts=4,
        test_drafts_per_fold=2,
        choice_set_size=8,
    )

    assert set(results["strategy"]) == {"adp_only", "opponent_aware"}
    assert sorted(results["train_drafts"].unique().tolist()) == [4, 6]
    assert results["known_pick_coverage"].eq(1.0).all()
    assert set(coefficients["strategy"]) == {"adp_only", "opponent_aware"}


def test_later_drafts_do_not_change_an_earlier_fold() -> None:
    shorter, _ = chronological_choice_backtest(
        _synthetic_draft_corpus(6),
        minimum_train_drafts=4,
        test_drafts_per_fold=2,
        choice_set_size=8,
    )
    longer, _ = chronological_choice_backtest(
        _synthetic_draft_corpus(10),
        minimum_train_drafts=4,
        test_drafts_per_fold=2,
        choice_set_size=8,
    )

    columns = ["strategy", "log_loss", "multiclass_brier", "top1_accuracy"]
    pd.testing.assert_frame_equal(
        shorter[columns].reset_index(drop=True),
        longer.loc[longer["fold"].eq(4), columns].reset_index(drop=True),
    )
