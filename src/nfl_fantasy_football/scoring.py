from __future__ import annotations

from pathlib import Path
import tomllib

import numpy as np
import pandas as pd

from .config import PROJECT_ROOT


def load_scoring(path: Path | None = None) -> dict[str, float]:
    source = path or PROJECT_ROOT / "config" / "scoring.toml"
    with source.open("rb") as handle:
        raw = tomllib.load(handle)
    return {field: float(weight) for field, weight in raw["scoring"].items()}


def score_components(
    frame: pd.DataFrame,
    scoring: dict[str, float] | None = None,
) -> pd.Series:
    weights = scoring or load_scoring()
    points = np.zeros(len(frame), dtype=float)
    for field, weight in weights.items():
        if field not in frame:
            values = np.zeros(len(frame), dtype=float)
        else:
            values = pd.to_numeric(frame[field], errors="coerce").fillna(0).to_numpy()
        points += weight * values
    return pd.Series(points, index=frame.index, name="fantasy_points_standard")


def scoring_fields(scoring: dict[str, float] | None = None) -> tuple[str, ...]:
    return tuple((scoring or load_scoring()).keys())
