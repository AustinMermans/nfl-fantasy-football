import pandas as pd

from nfl_fantasy_football.scoring import score_components


def test_league_half_ppr_scoring() -> None:
    row = pd.DataFrame(
        [{
            "passing_yards": 250,
            "passing_tds": 2,
            "passing_interceptions": 1,
            "rushing_yards": 20,
            "rushing_tds": 1,
            "fumbles_lost_total": 1,
            "receptions": 4,
        }]
    )
    assert score_components(row).iloc[0] == 24.0


def test_tiered_kicker_scoring() -> None:
    row = pd.DataFrame(
        [{
            "fg_made_20_29": 1,
            "fg_made_40_49": 1,
            "fg_made_50_59": 1,
            "fg_made_60_": 1,
            "fg_missed_total": 1,
            "pat_made": 2,
        }]
    )
    assert score_components(row).iloc[0] == 19.0
