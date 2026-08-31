from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import PoissonRegressor, Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler


@dataclass
class RecentMeanRegressor:
    column: str
    fallback: float = 0.0

    def fit(self, frame: pd.DataFrame, target: pd.Series) -> "RecentMeanRegressor":
        self.fallback = float(target.mean())
        return self

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        return frame[self.column].fillna(self.fallback).clip(lower=0).to_numpy()


def build_estimator(name: str, *, seed: int, nonnegative_target: bool):
    if name == "linear" and nonnegative_target:
        return make_pipeline(
            SimpleImputer(strategy="median", add_indicator=True),
            StandardScaler(),
            PoissonRegressor(alpha=0.25, max_iter=1000),
        )
    if name == "linear":
        return make_pipeline(
            SimpleImputer(strategy="median", add_indicator=True),
            StandardScaler(),
            Ridge(alpha=20.0),
        )
    if name == "hist":
        return make_pipeline(
            SimpleImputer(strategy="median", add_indicator=True),
            HistGradientBoostingRegressor(
                loss="poisson" if nonnegative_target else "squared_error",
                learning_rate=0.06,
                max_iter=180,
                max_leaf_nodes=15,
                l2_regularization=2.0,
                random_state=seed,
            ),
        )
    raise ValueError(f"unknown estimator: {name}")
