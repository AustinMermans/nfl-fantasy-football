from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class ResearchConfig:
    first_season: int
    development_end_season: int
    locked_test_season: int
    first_validation_season: int
    selection_season: int
    random_seed: int
    min_player_games: int
    positions: tuple[str, ...]


def load_config(path: Path | None = None) -> ResearchConfig:
    source = path or PROJECT_ROOT / "config" / "research.toml"
    with source.open("rb") as handle:
        raw = tomllib.load(handle)
    return ResearchConfig(
        first_season=int(raw["data"]["first_season"]),
        development_end_season=int(raw["data"]["development_end_season"]),
        locked_test_season=int(raw["data"]["locked_test_season"]),
        first_validation_season=int(raw["validation"]["first_validation_season"]),
        selection_season=int(raw["validation"]["selection_season"]),
        random_seed=int(raw["model"]["random_seed"]),
        min_player_games=int(raw["model"]["min_player_games"]),
        positions=tuple(raw["model"]["positions"]),
    )

