from __future__ import annotations

import numpy as np
import pandas as pd

from .data import STAT_COLUMNS
from .market import market_feature_columns


HISTORY_COLUMNS = (
    *STAT_COLUMNS,
    "offense_snaps",
    "offense_pct",
    "st_snaps",
    "played",
)


def _shifted_ewm(series: pd.Series, span: int) -> pd.Series:
    return series.shift().ewm(span=span, adjust=False, min_periods=1).mean()


def build_features(player_games: pd.DataFrame) -> pd.DataFrame:
    """Create point-in-time features using only games before the row's kickoff."""
    frame = player_games.sort_values(["gameday", "game_id", "player_id"]).copy()
    for column in (*STAT_COLUMNS, "st_snaps"):
        if column not in frame:
            frame[column] = 0.0
    if "played" not in frame:
        frame["played"] = (
            frame["offense_snaps"].fillna(0).gt(0)
            | frame["st_snaps"].fillna(0).gt(0)
        ).astype(float)
    for column in (
        "report_primary_injury",
        "practice_primary_injury",
        "report_status",
        "practice_status",
    ):
        if column not in frame:
            frame[column] = None
    players = frame.groupby("player_id", sort=False)
    frame["player_games_prior"] = players.cumcount().astype(float)

    history_features: dict[str, pd.Series] = {}
    for column in HISTORY_COLUMNS:
        grouped = players[column]
        history_features[f"{column}_lag1"] = grouped.shift()
        history_features[f"{column}_ewm4"] = grouped.transform(
            lambda values: _shifted_ewm(values, 4)
        )
        history_features[f"{column}_ewm12"] = grouped.transform(
            lambda values: _shifted_ewm(values, 12)
        )
    frame = pd.concat([frame, pd.DataFrame(history_features, index=frame.index)], axis=1)

    team_game = (
        frame.groupby(
            [
                "game_id",
                "gameday",
                "season",
                "week",
                "team",
                "opponent_team",
                "position",
            ],
            as_index=False,
        )[list(STAT_COLUMNS)]
        .sum()
        .sort_values(["gameday", "game_id"])
    )
    opponent_game = team_game.rename(
        columns={
            "opponent_team": "defense_team",
            **{column: f"allowed_{column}" for column in STAT_COLUMNS},
        }
    )

    for column in STAT_COLUMNS:
        team_game[f"team_{column}_ewm8"] = team_game.groupby(
            ["team", "position"], sort=False
        )[column].transform(lambda values: _shifted_ewm(values, 8))
        allowed = f"allowed_{column}"
        opponent_game[f"opponent_{column}_ewm8"] = opponent_game.groupby(
            ["defense_team", "position"], sort=False
        )[allowed].transform(lambda values: _shifted_ewm(values, 8))

    team_features = ["game_id", "team", "position"] + [
        f"team_{column}_ewm8" for column in STAT_COLUMNS
    ]
    opponent_features = ["game_id", "defense_team", "position"] + [
        f"opponent_{column}_ewm8" for column in STAT_COLUMNS
    ]
    frame = frame.merge(
        team_game[team_features],
        on=["game_id", "team", "position"],
        how="left",
        validate="many_to_one",
    ).merge(
        opponent_game[opponent_features].rename(columns={"defense_team": "opponent_team"}),
        on=["game_id", "opponent_team", "position"],
        how="left",
        validate="many_to_one",
    )

    frame["position_code"] = frame["position"].map(
        {"QB": 0.0, "RB": 1.0, "FB": 2.0, "WR": 3.0, "TE": 4.0, "K": 5.0}
    )
    frame["roof_indoor"] = frame["roof"].isin(["closed", "dome"]).astype(float)
    frame["surface_grass"] = frame["surface"].astype(str).str.contains(
        "grass", case=False, na=False
    ).astype(float)
    team_spread = frame["spread_line"].where(
        frame["home"].eq(1.0), -frame["spread_line"]
    )
    frame["team_implied_points"] = (frame["total_line"] + team_spread) / 2.0
    frame["opponent_implied_points"] = (frame["total_line"] - team_spread) / 2.0
    report = frame["report_status"].fillna("").str.lower()
    practice = frame["practice_status"].fillna("").str.lower()
    frame["injury_reported"] = frame[
        ["report_primary_injury", "practice_primary_injury"]
    ].notna().any(axis=1).astype(float)
    frame["report_out"] = report.eq("out").astype(float)
    frame["report_doubtful"] = report.eq("doubtful").astype(float)
    frame["report_questionable"] = report.eq("questionable").astype(float)
    frame["practice_dnp"] = practice.str.contains("did not participate").astype(float)
    frame["practice_limited"] = practice.str.contains("limited").astype(float)
    frame.replace([np.inf, -np.inf], np.nan, inplace=True)
    return frame.sort_values(["gameday", "game_id", "player_id"]).reset_index(drop=True)


def feature_sets(target: str) -> dict[str, list[str]]:
    baseline = [f"{target}_ewm12"]
    player_form = [
        "player_games_prior",
        "position_code",
        f"{target}_lag1",
        f"{target}_ewm4",
        f"{target}_ewm12",
    ]
    workload = player_form + [
        "offense_pct_lag1",
        "offense_pct_ewm4",
        "offense_pct_ewm12",
        "offense_snaps_ewm4",
        "offense_snaps_ewm12",
        "st_snaps_ewm4",
        "st_snaps_ewm12",
        "played_lag1",
        "played_ewm4",
        "played_ewm12",
        "attempts_ewm4",
        "carries_ewm4",
        "targets_ewm4",
        "receptions_ewm4",
        "target_share_ewm4",
        "receiving_air_yards_ewm4",
    ]
    context = workload + [
        f"team_{target}_ewm8",
        f"opponent_{target}_ewm8",
        "home",
        "rest_days",
        "week",
        "age",
        "years_since_draft",
        "roof_indoor",
        "surface_grass",
        "temp",
        "wind",
        "injury_reported",
        "report_out",
        "report_doubtful",
        "report_questionable",
        "practice_dnp",
        "practice_limited",
    ]
    market = context + [
        "spread_line",
        "total_line",
        "team_implied_points",
        "opponent_implied_points",
    ]
    player_market = market + market_feature_columns(target)
    admitted = {
        "passing_yards": [],
        "rushing_yards": ["opponent_rushing_yards_ewm8", "week"],
        "receiving_yards": [
            "total_line",
            "opponent_receiving_yards_ewm8",
            "report_questionable",
        ],
    }.get(target, [])
    screened = list(dict.fromkeys([*workload, *admitted]))
    return {
        "recent_mean": baseline,
        "player_form": player_form,
        "workload": workload,
        "context": context,
        "market_context": market,
        "player_market": player_market,
        "screened": screened,
    }
