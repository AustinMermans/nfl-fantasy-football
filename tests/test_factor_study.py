import pandas as pd

from nfl_fantasy_football.factor_study import _holm_adjust


def test_holm_adjustment_is_at_least_raw_p_value() -> None:
    raw = pd.Series([0.01, 0.04, 0.2])
    adjusted = _holm_adjust(raw)
    assert (adjusted >= raw).all()
    assert (adjusted <= 1).all()
