import pandas as pd

from nfl_fantasy_football.preseason import (
    COMPONENT_WEIGHT_BY_POSITION,
    current_preseason_rows,
    season_player_panel,
    walk_forward_preseason_backtest,
)


def _game(season: int, player_id: str, points_yards: float) -> dict[str, object]:
    return {
        "season": season,
        "player_id": player_id,
        "player_name": "Player",
        "position": "RB",
        "team": "AAA",
        "age": 25.0,
        "years_exp": 2.0,
        "draft_pick": 50.0,
        "game_id": f"{season}_{player_id}",
        "offense_snaps": 30.0,
        "offense_pct": 0.5,
        "st_snaps": 0.0,
        "rushing_yards": points_yards,
    }


def test_season_panel_uses_exact_prior_seasons() -> None:
    history = pd.DataFrame(
        [_game(2022, "continuous", 100), _game(2023, "continuous", 80), _game(2024, "continuous", 60), _game(2022, "gap", 100), _game(2024, "gap", 60)]
    )
    panel = season_player_panel(history)
    continuous = panel[(panel["season"].eq(2024)) & panel["player_id"].eq("continuous")].iloc[0]
    gap = panel[(panel["season"].eq(2024)) & panel["player_id"].eq("gap")].iloc[0]

    assert continuous["prior_points"] == 8.0
    assert continuous["prior2_points"] == 10.0
    assert pd.isna(gap["prior_points"])
    assert gap["prior2_points"] == 10.0


def test_current_rows_do_not_treat_a_gap_as_last_season() -> None:
    history = pd.DataFrame([_game(2022, "gap", 100), _game(2024, "active", 60)])
    panel = season_player_panel(history)
    roles = pd.DataFrame(
        [
            {"player_id": "gap", "player_name": "Gap", "position": "RB", "team": "AAA", "age": 28, "years_exp": 5, "draft_pick": 50, "week": 1},
            {"player_id": "active", "player_name": "Active", "position": "RB", "team": "AAA", "age": 25, "years_exp": 2, "draft_pick": 50, "week": 1},
        ]
    )
    current = current_preseason_rows(panel, roles, season=2025).set_index("player_id")

    assert pd.isna(current.loc["gap", "prior_points"])
    assert current.loc["active", "prior_points"] == 6.0


def test_qb_total_does_not_use_frozen_weekly_component_blend() -> None:
    assert COMPONENT_WEIGHT_BY_POSITION["QB"] == 0.0
    assert COMPONENT_WEIGHT_BY_POSITION["RB"] > 0.0


def test_walk_forward_prediction_is_unchanged_by_future_season() -> None:
    rows = []
    for player_index in range(12):
        for season in range(2014, 2019):
            game = _game(season, f"p{player_index}", 300 + 5 * player_index + season % 3)
            if season == 2018:
                game["rushing_yards"] = 5000 + 100 * player_index
            rows.append(game)
    history = pd.DataFrame(rows)
    through_2017 = history[history["season"].le(2017)]

    early, _, _ = walk_forward_preseason_backtest(
        through_2017, first_test_season=2017, last_test_season=2017
    )
    with_future, _, _ = walk_forward_preseason_backtest(
        history, first_test_season=2017, last_test_season=2017
    )

    pd.testing.assert_series_equal(
        early.sort_values("player_id")["season_ensemble"].reset_index(drop=True),
        with_future.sort_values("player_id")["season_ensemble"].reset_index(drop=True),
    )
