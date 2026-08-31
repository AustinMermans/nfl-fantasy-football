from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import ttest_1samp
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_squared_error
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .evaluation import TARGET_POSITIONS
from .features import feature_sets


def _estimator():
    return make_pipeline(
        SimpleImputer(strategy="median", add_indicator=True),
        StandardScaler(),
        Ridge(alpha=20.0),
    )


def _rmse(actual, predicted) -> float:
    return float(mean_squared_error(actual, np.clip(predicted, 0, None)) ** 0.5)


def _holm_adjust(p_values: pd.Series) -> pd.Series:
    order = np.argsort(p_values.to_numpy())
    sorted_p = p_values.to_numpy()[order]
    adjusted = np.maximum.accumulate(
        np.array([(len(sorted_p) - index) * value for index, value in enumerate(sorted_p)])
    )
    output = np.empty(len(sorted_p))
    output[order] = np.clip(adjusted, 0, 1)
    return pd.Series(output, index=p_values.index)


def screen_context_factors(
    frame: pd.DataFrame,
    target: str,
    *,
    first_test_season: int,
    last_test_season: int,
    min_player_games: int,
    random_repetitions: int,
    seed: int,
) -> pd.DataFrame:
    sets = feature_sets(target)
    baseline = sets["workload"]
    candidates = list(dict.fromkeys(
        [column for column in sets["market_context"] if column not in baseline]
    ))
    data = frame[
        frame["position"].isin(TARGET_POSITIONS[target])
        & frame["player_games_prior"].ge(min_player_games)
    ].copy()
    fold_delta: dict[str, list[float]] = {candidate: [] for candidate in candidates}
    selection_delta: dict[str, float] = {}

    for season in range(first_test_season, last_test_season + 1):
        train = data[data["season"] < season]
        test = data[data["season"] == season]
        base_model = _estimator().fit(train[baseline], train[target])
        base_rmse = _rmse(test[target], base_model.predict(test[baseline]))
        for candidate in candidates:
            columns = [*baseline, candidate]
            model = _estimator().fit(train[columns], train[target])
            delta = base_rmse - _rmse(test[target], model.predict(test[columns]))
            fold_delta[candidate].append(delta)
            if season == last_test_season:
                selection_delta[candidate] = delta

    selection_train = data[data["season"] < last_test_season].copy()
    selection_test = data[data["season"] == last_test_season].copy()
    baseline_model = _estimator().fit(selection_train[baseline], selection_train[target])
    baseline_rmse = _rmse(
        selection_test[target], baseline_model.predict(selection_test[baseline])
    )
    random_deltas = []
    rng = np.random.default_rng(seed)
    for _ in range(random_repetitions):
        train = selection_train[baseline].copy()
        test = selection_test[baseline].copy()
        train["random_control"] = rng.normal(size=len(train))
        test["random_control"] = rng.normal(size=len(test))
        model = _estimator().fit(train, selection_train[target])
        random_deltas.append(
            baseline_rmse - _rmse(selection_test[target], model.predict(test))
        )
    random_p95 = float(np.quantile(random_deltas, 0.95))

    rows = []
    for candidate, deltas in fold_delta.items():
        test = ttest_1samp(deltas, popmean=0.0, alternative="greater")
        rows.append(
            {
                "target": target,
                "candidate": candidate,
                "folds": len(deltas),
                "mean_rmse_gain": float(np.mean(deltas)),
                "selection_rmse_gain": selection_delta[candidate],
                "random_gain_mean": float(np.mean(random_deltas)),
                "random_gain_p95": random_p95,
                "p_value": float(test.pvalue),
            }
        )
    output = pd.DataFrame(rows)
    output["holm_p"] = _holm_adjust(output["p_value"])
    output["beats_random"] = output["selection_rmse_gain"] > output["random_gain_p95"]
    output["accepted"] = (
        output["mean_rmse_gain"].gt(0)
        & output["beats_random"]
        & output["holm_p"].lt(0.05)
    )
    return output.sort_values(
        ["accepted", "mean_rmse_gain"], ascending=[False, False]
    ).reset_index(drop=True)

