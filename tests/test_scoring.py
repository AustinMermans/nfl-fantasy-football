import pandas as pd

from nfl_fantasy_football.scoring import score_components


def test_traditional_non_ppr_scoring() -> None:
    row = pd.DataFrame(
        [{
            "passing_yards": 250,
            "passing_tds": 2,
            "passing_interceptions": 1,
            "rushing_yards": 20,
            "rushing_tds": 1,
            "fumbles_lost_total": 1,
        }]
    )
    assert score_components(row).iloc[0] == 22.0


def test_tiered_kicker_scoring() -> None:
    row = pd.DataFrame(
        [{
            "fg_made_20_29": 1,
            "fg_made_40_49": 1,
            "fg_made_50_59": 1,
            "pat_made": 2,
        }]
    )
    assert score_components(row).iloc[0] == 14.0
