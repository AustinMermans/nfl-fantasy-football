from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from .calibration import nested_calibration_backtest
from .config import PROJECT_ROOT, load_config
from .data import download_nflverse, load_player_games
from .draft_board import export_draft_board
from .evaluation import BacktestSpec, summarize_backtest, walk_forward_backtest
from .factor_study import screen_context_factors
from .features import build_features
from .fantasy import build_fantasy_point_predictions, evaluate_fantasy_points
from .participation import summarize_participation, walk_forward_participation


DEFAULT_TARGETS = ("passing_yards", "rushing_yards", "receiving_yards")


def _build_dataset(args: argparse.Namespace) -> None:
    config = load_config()
    last = config.locked_test_season if args.include_holdout else config.development_end_season
    seasons = list(range(config.first_season, last + 1))
    download_nflverse(seasons, refresh=args.refresh)
    frame = build_features(load_player_games(seasons, positions=config.positions))
    destination = PROJECT_ROOT / "data" / "processed" / "player_games.parquet"
    destination.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(destination, index=False)
    print(f"wrote {len(frame):,} rows to {destination}")


def _backtest(args: argparse.Namespace) -> None:
    config = load_config()
    source = PROJECT_ROOT / "data" / "processed" / "player_games.parquet"
    frame = pd.read_parquet(source)
    last_season = config.development_end_season
    if frame["season"].max() > last_season:
        frame = frame[frame["season"] <= last_season].copy()
    spec = BacktestSpec(
        first_test_season=config.first_validation_season,
        last_test_season=last_season,
        seed=config.random_seed,
        min_player_games=config.min_player_games,
    )
    metric_frames = []
    prediction_frames = []
    for target in args.targets:
        print(f"backtesting {target}...", flush=True)
        metrics, predictions = walk_forward_backtest(
            frame,
            target,
            spec,
            model_names=tuple(args.models),
            set_names=tuple(args.feature_sets),
        )
        metric_frames.append(metrics)
        prediction_frames.append(predictions)
    results = PROJECT_ROOT / "results"
    results.mkdir(exist_ok=True)
    metrics = pd.concat(metric_frames, ignore_index=True)
    predictions = pd.concat(prediction_frames, ignore_index=True)
    prefix = args.output_prefix
    metrics.to_csv(results / f"{prefix}_backtest_by_season.csv", index=False)
    predictions.to_parquet(results / f"{prefix}_predictions.parquet", index=False)
    summary = summarize_backtest(metrics)
    summary.to_csv(results / f"{prefix}_backtest_summary.csv", index=False)
    print(summary.to_string(index=False))


def _participation(args: argparse.Namespace) -> None:
    config = load_config()
    source = PROJECT_ROOT / "data" / "processed" / "player_games.parquet"
    frame = pd.read_parquet(source)
    frame = frame[frame["season"] <= config.development_end_season].copy()
    metrics, predictions = walk_forward_participation(
        frame,
        first_test_season=config.first_validation_season,
        last_test_season=config.development_end_season,
        min_player_games=config.min_player_games,
        seed=config.random_seed,
    )
    results = PROJECT_ROOT / "results"
    results.mkdir(exist_ok=True)
    metrics.to_csv(results / "participation_backtest_by_season.csv", index=False)
    predictions.to_parquet(results / "participation_predictions.parquet", index=False)
    summary = summarize_participation(metrics)
    summary.to_csv(results / "participation_backtest_summary.csv", index=False)
    print(summary.to_string(index=False))


def _calibration(args: argparse.Namespace) -> None:
    results = PROJECT_ROOT / "results"
    predictions = pd.read_parquet(results / "participation_predictions.parquet")
    selected = predictions[
        predictions["feature_set"].eq("context") & predictions["model"].eq("hist")
    ].copy()
    by_season, summary = nested_calibration_backtest(selected)
    by_season.to_csv(results / "participation_calibration_by_season.csv", index=False)
    summary.to_csv(results / "participation_calibration_summary.csv", index=False)
    print(summary.to_string(index=False))


def _factor_study(args: argparse.Namespace) -> None:
    config = load_config()
    frame = pd.read_parquet(
        PROJECT_ROOT / "data" / "processed" / "player_games.parquet"
    )
    frame = frame[frame["season"] <= config.development_end_season].copy()
    screens = [
        screen_context_factors(
            frame,
            target,
            first_test_season=config.first_validation_season,
            last_test_season=config.development_end_season,
            min_player_games=config.min_player_games,
            random_repetitions=args.random_repetitions,
            seed=config.random_seed,
        )
        for target in args.targets
    ]
    output = pd.concat(screens, ignore_index=True)
    destination = PROJECT_ROOT / "results" / "factor_screen.csv"
    output.to_csv(destination, index=False)
    print(output.to_string(index=False))


def _fantasy_evaluation(args: argparse.Namespace) -> None:
    results = PROJECT_ROOT / "results"
    player_games = pd.read_parquet(
        PROJECT_ROOT / "data" / "processed" / "player_games.parquet"
    )
    prediction_frames = [
        pd.read_parquet(results / "development_predictions.parquet"),
        pd.read_parquet(results / "expanded_predictions.parquet"),
    ]
    output = build_fantasy_point_predictions(prediction_frames, player_games)
    by_season, summary = evaluate_fantasy_points(output)
    output.to_parquet(results / "fantasy_point_predictions.parquet", index=False)
    by_season.to_csv(results / "fantasy_point_backtest_by_season.csv", index=False)
    summary.to_csv(results / "fantasy_point_backtest_summary.csv", index=False)
    print(summary.to_string(index=False))


def _draft_board(args: argparse.Namespace) -> None:
    destination = export_draft_board(season=args.season)
    print(f"wrote draft-board projections to {destination}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nfl-fantasy")
    commands = parser.add_subparsers(required=True)
    dataset = commands.add_parser("build-dataset")
    dataset.add_argument("--refresh", action="store_true")
    dataset.add_argument("--include-holdout", action="store_true")
    dataset.set_defaults(handler=_build_dataset)
    backtest = commands.add_parser("backtest")
    backtest.add_argument("--targets", nargs="+", default=list(DEFAULT_TARGETS))
    backtest.add_argument(
        "--models", nargs="+", default=["recent_mean", "linear", "hist"]
    )
    backtest.add_argument("--output-prefix", default="development")
    backtest.add_argument(
        "--feature-sets",
        nargs="+",
        default=[
            "recent_mean", "player_form", "workload", "screened", "context",
            "market_context",
        ],
    )
    backtest.set_defaults(handler=_backtest)
    participation = commands.add_parser("participation-backtest")
    participation.set_defaults(handler=_participation)
    calibration = commands.add_parser("calibration-backtest")
    calibration.set_defaults(handler=_calibration)
    factors = commands.add_parser("factor-study")
    factors.add_argument("--targets", nargs="+", default=list(DEFAULT_TARGETS))
    factors.add_argument("--random-repetitions", type=int, default=100)
    factors.set_defaults(handler=_factor_study)
    fantasy = commands.add_parser("fantasy-evaluation")
    fantasy.set_defaults(handler=_fantasy_evaluation)
    draft_board = commands.add_parser("draft-board")
    draft_board.add_argument("--season", type=int)
    draft_board.set_defaults(handler=_draft_board)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.handler(args)


if __name__ == "__main__":
    main()
