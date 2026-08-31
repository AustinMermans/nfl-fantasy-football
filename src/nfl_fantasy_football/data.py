from __future__ import annotations

from pathlib import Path
from urllib.request import urlopen

import pandas as pd

from .config import PROJECT_ROOT


NFLVERSE_RELEASE = "https://github.com/nflverse/nflverse-data/releases/download"
SCHEDULE_URL = "https://github.com/nflverse/nfldata/raw/master/data/games.csv"
RAW_DIR = PROJECT_ROOT / "data" / "raw" / "nflverse"

STAT_COLUMNS = (
    "completions",
    "attempts",
    "passing_yards",
    "passing_tds",
    "passing_interceptions",
    "passing_2pt_conversions",
    "carries",
    "rushing_yards",
    "rushing_tds",
    "rushing_2pt_conversions",
    "targets",
    "receptions",
    "receiving_yards",
    "receiving_tds",
    "receiving_2pt_conversions",
    "receiving_air_yards",
    "target_share",
    "air_yards_share",
    "special_teams_tds",
    "fumbles_lost_total",
    "fg_made_0_19",
    "fg_made_20_29",
    "fg_made_30_39",
    "fg_made_40_49",
    "fg_made_50_59",
    "fg_made_60_",
    "pat_made",
    "pat_missed",
)


def _download(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    with urlopen(url, timeout=120) as response, temporary.open("wb") as handle:
        while chunk := response.read(1024 * 1024):
            handle.write(chunk)
    temporary.replace(destination)


def download_nflverse(seasons: range | list[int], *, refresh: bool = False) -> None:
    for season in seasons:
        assets = {
            RAW_DIR / f"stats_player_week_{season}.parquet": (
                f"{NFLVERSE_RELEASE}/stats_player/"
                f"stats_player_week_{season}.parquet"
            ),
            RAW_DIR / f"snap_counts_{season}.parquet": (
                f"{NFLVERSE_RELEASE}/snap_counts/snap_counts_{season}.parquet"
            ),
            RAW_DIR / f"roster_weekly_{season}.parquet": (
                f"{NFLVERSE_RELEASE}/weekly_rosters/roster_weekly_{season}.parquet"
            ),
            RAW_DIR / f"injuries_{season}.parquet": (
                f"{NFLVERSE_RELEASE}/injuries/injuries_{season}.parquet"
            ),
        }
        for destination, url in assets.items():
            if refresh or not destination.exists():
                _download(url, destination)
    shared = {
        RAW_DIR / "players.parquet": f"{NFLVERSE_RELEASE}/players/players.parquet",
        RAW_DIR / "games.csv": SCHEDULE_URL,
    }
    for destination, url in shared.items():
        if refresh or not destination.exists():
            _download(url, destination)


def _load_many(pattern: str, seasons: list[int]) -> pd.DataFrame:
    paths = [RAW_DIR / pattern.format(season=season) for season in seasons]
    missing = [path for path in paths if not path.exists()]
    if missing:
        names = ", ".join(path.name for path in missing[:3])
        raise FileNotFoundError(f"missing nflverse assets: {names}; run download first")
    return pd.concat((pd.read_parquet(path) for path in paths), ignore_index=True)


def load_player_games(
    seasons: list[int],
    *,
        positions: tuple[str, ...] = ("QB", "RB", "FB", "WR", "TE", "K"),
) -> pd.DataFrame:
    """Build one row per active-roster skill player and scheduled regular-season game."""
    stats = _load_many("stats_player_week_{season}.parquet", seasons)
    snaps = _load_many("snap_counts_{season}.parquet", seasons)
    rosters = _load_many("roster_weekly_{season}.parquet", seasons)
    injuries = _load_many("injuries_{season}.parquet", seasons)
    schedules = pd.read_csv(RAW_DIR / "games.csv", low_memory=False)

    stats = stats[
        stats["season_type"].eq("REG") & stats["position"].isin(positions)
    ].copy()
    snaps = snaps[
        snaps["game_type"].eq("REG")
        & snaps["position"].isin(positions)
    ].copy()
    rosters = rosters[
        rosters["game_type"].eq("REG")
        & rosters["position"].isin(positions)
        & rosters["status"].eq("ACT")
        & rosters["gsis_id"].notna()
    ].copy()
    rosters = rosters.drop_duplicates(
        ["season", "week", "team", "gsis_id"], keep="last"
    )

    schedule_core = schedules[
        schedules["season"].isin(seasons) & schedules["game_type"].eq("REG")
    ].copy()
    shared_game_columns = [
        "game_id", "season", "week", "gameday", "home_team", "away_team",
        "spread_line", "total_line", "roof", "surface", "temp", "wind",
    ]
    home_games = schedule_core[shared_game_columns + ["home_rest"]].rename(
        columns={"home_team": "team", "away_team": "opponent_team", "home_rest": "rest_days"}
    )
    home_games["home"] = 1.0
    away_games = schedule_core[shared_game_columns + ["away_rest"]].rename(
        columns={"away_team": "team", "home_team": "opponent_team", "away_rest": "rest_days"}
    )
    away_games["home"] = 0.0
    team_games = pd.concat([home_games, away_games], ignore_index=True)

    roster_columns = [
        "season", "week", "team", "gsis_id", "pfr_id", "full_name", "position",
        "birth_date", "years_exp", "rookie_year", "draft_number",
    ]
    base = rosters[roster_columns].merge(
        team_games,
        on=["season", "week", "team"],
        how="inner",
        validate="many_to_one",
    ).rename(
        columns={
            "gsis_id": "player_id",
            "full_name": "player_name",
            "rookie_year": "draft_year",
            "draft_number": "draft_pick",
        }
    )

    snap_columns = [
        "game_id", "pfr_player_id", "offense_snaps", "offense_pct",
        "defense_snaps", "st_snaps",
    ]
    base = base.merge(
        snaps[snap_columns].drop_duplicates(["game_id", "pfr_player_id"], keep="last"),
        left_on=["game_id", "pfr_id"],
        right_on=["game_id", "pfr_player_id"],
        how="left",
        validate="many_to_one",
    )
    base["played"] = (
        base["offense_snaps"].fillna(0).gt(0)
        | base["st_snaps"].fillna(0).gt(0)
    ).astype(float)
    for column in ["offense_snaps", "offense_pct", "defense_snaps", "st_snaps"]:
        base[column] = base[column].fillna(0.0)

    stat_columns = ["game_id", "player_id", *STAT_COLUMNS]
    observed = stats[stat_columns].drop_duplicates(["game_id", "player_id"], keep="last")
    frame = base.merge(
        observed,
        on=["game_id", "player_id"],
        how="left",
        validate="one_to_one",
    )
    frame[list(STAT_COLUMNS)] = frame[list(STAT_COLUMNS)].fillna(0.0)

    def first_non_null(values: pd.Series):
        non_null = values.dropna()
        return non_null.iloc[-1] if not non_null.empty else None

    injury_columns = [
        "report_primary_injury", "report_secondary_injury", "report_status",
        "practice_primary_injury", "practice_secondary_injury", "practice_status",
    ]
    injury_week = (
        injuries[injuries["game_type"].eq("REG")]
        .groupby(["season", "week", "team", "gsis_id"], as_index=False)[injury_columns]
        .agg(first_non_null)
        .rename(columns={"gsis_id": "player_id"})
    )
    frame = frame.merge(
        injury_week,
        on=["season", "week", "team", "player_id"],
        how="left",
        validate="one_to_one",
    )
    frame["gameday"] = pd.to_datetime(frame["gameday"], errors="coerce")
    frame["birth_date"] = pd.to_datetime(frame["birth_date"], errors="coerce")
    frame["draft_year"] = pd.to_numeric(frame["draft_year"], errors="coerce")
    frame["draft_pick"] = pd.to_numeric(frame["draft_pick"], errors="coerce")
    frame["years_exp"] = pd.to_numeric(frame["years_exp"], errors="coerce")
    frame["age"] = (frame["gameday"] - frame["birth_date"]).dt.days / 365.25
    frame["years_since_draft"] = frame["season"] - frame["draft_year"]
    frame = frame.sort_values(["gameday", "game_id", "player_id"]).reset_index(drop=True)
    return frame
