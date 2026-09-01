from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.error import URLError

import pandas as pd

from .calibration import nested_calibration_backtest
from .config import PROJECT_ROOT, load_config
from .data import download_nflverse, load_player_games
from .draft_board import build_player_rankings, export_draft_board, export_preseason_board
from .draft_strategy import simulate_draft_policy
from .evaluation import BacktestSpec, summarize_backtest, walk_forward_backtest
from .espn import write_espn_market
from .factor_study import screen_context_factors
from .features import build_features
from .fantasy import build_fantasy_point_predictions, evaluate_fantasy_points
from .market import (
    KALSHI_PLAYER_SERIES,
    kalshi_historical_markets,
    kalshi_live_markets,
    kalshi_player_market_catalog,
    kalshi_series,
    market_admission_audit,
    market_consensus_features,
    polymarket_events,
    polymarket_player_market_catalog,
)
from .participation import summarize_participation, walk_forward_participation
from .production import build_preseason_forecasts, write_production_artifacts
from .preseason import walk_forward_preseason_backtest


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


def _market_catalog_audit(args: argparse.Namespace) -> None:
    metadata = {str(item["ticker"]): item for item in kalshi_series()}
    rows: list[dict[str, object]] = []
    for ticker in args.kalshi_series:
        historical = kalshi_historical_markets(
            series_ticker=ticker, max_pages=args.kalshi_pages
        )
        live = kalshi_live_markets(series_ticker=ticker, max_pages=1)
        markets = {
            str(item.get("ticker")): item for item in [*historical, *live]
        }.values()
        catalog = kalshi_player_market_catalog(markets, series_ticker=ticker)
        item = metadata.get(ticker, {})
        rows.append(
            {
                "source": "kalshi",
                "series": ticker,
                "stat_type": KALSHI_PLAYER_SERIES.get(ticker),
                "catalog_markets": len(catalog),
                "first_open": catalog["open_time"].min() if not catalog.empty else None,
                "last_close": catalog["close_time"].max() if not catalog.empty else None,
                "catalog_volume": float(catalog["volume"].fillna(0).sum())
                if not catalog.empty
                else 0.0,
                "series_volume": pd.to_numeric(
                    item.get("volume_fp"), errors="coerce"
                ),
                "history_pages_requested": args.kalshi_pages,
                "stage": "shadow",
            }
        )

    events = [
        *polymarket_events(closed=True, max_pages=args.polymarket_pages),
        *polymarket_events(closed=False, max_pages=1),
    ]
    polymarket = polymarket_player_market_catalog(events)
    if not polymarket.empty:
        for stat_type, group in polymarket.groupby("stat_type"):
            rows.append(
                {
                    "source": "polymarket",
                    "series": "NFL tag 450",
                    "stat_type": stat_type,
                    "catalog_markets": int(group["market_id"].nunique()),
                    "first_open": group["open_time"].min(),
                    "last_close": group["close_time"].max(),
                    "catalog_volume": float(group["volume"].fillna(0).sum()),
                    "series_volume": float("nan"),
                    "history_pages_requested": args.polymarket_pages,
                    "stage": "shadow",
                }
            )

    output = pd.DataFrame(rows).sort_values(["source", "stat_type"])
    destination = PROJECT_ROOT / "results" / "market_catalog_audit.csv"
    destination.parent.mkdir(exist_ok=True)
    output.to_csv(destination, index=False)
    print(output.to_string(index=False))
    print(f"wrote catalog audit to {destination}")


def _market_feature_audit(args: argparse.Namespace) -> None:
    config = load_config()
    source = Path(args.quotes)
    quotes = (
        pd.read_parquet(source)
        if source.suffix.lower() == ".parquet"
        else pd.read_csv(source)
    )
    player_games = pd.read_parquet(
        PROJECT_ROOT / "data" / "processed" / "player_games.parquet"
    )
    features = market_consensus_features(quotes)
    audit = market_admission_audit(
        features,
        player_games,
        development_end_season=config.development_end_season,
        minimum_seasons=args.minimum_seasons,
        minimum_rows_per_season=args.minimum_rows_per_season,
    )
    results = PROJECT_ROOT / "results"
    features.to_parquet(results / "market_features.parquet", index=False)
    audit.to_csv(results / "market_admission_audit.csv", index=False)
    print(audit.to_string(index=False))


def _draft_board(args: argparse.Namespace) -> None:
    destination = export_draft_board(season=args.season)
    print(f"wrote draft-board projections to {destination}")


def _draft_policy_stress_test(args: argparse.Namespace) -> None:
    results = PROJECT_ROOT / "results"
    fantasy = pd.read_parquet(results / "fantasy_point_predictions.parquet")
    components = pd.concat(
        [
            pd.read_parquet(results / "development_predictions.parquet"),
            pd.read_parquet(results / "expanded_predictions.parquet"),
        ],
        ignore_index=True,
    )
    players = build_player_rankings(fantasy, components, season=args.season)
    rows = [
        simulate_draft_policy(
            players,
            teams=args.teams,
            draft_slot=draft_slot,
            rounds=args.rounds,
            strategy=strategy,
            scenario=scenario,
        )
        for scenario in args.scenarios
        for strategy in ("dynamic", "greedy", "format", "raw_points")
        for draft_slot in range(1, args.teams + 1)
    ]
    report = pd.DataFrame(rows)
    destination = results / "draft_policy_stress_test.csv"
    report.to_csv(destination, index=False)
    summary = report.groupby(["scenario", "strategy"], as_index=False).agg(
        mean_projected_starter_points=("projected_starter_points", "mean"),
        mean_actual_starter_points=("actual_starter_points", "mean"),
        worst_actual_starter_points=("actual_starter_points", "min"),
    )
    print(summary.round(2).to_string(index=False))
    print(f"wrote draft-policy stress test to {destination}")


def _preseason_forecast(args: argparse.Namespace) -> None:
    fantasy, components, features, as_of = build_preseason_forecasts(
        args.season, refresh=args.refresh
    )
    write_production_artifacts(fantasy, components, features)
    destination = export_preseason_board(
        fantasy,
        components,
        features,
        season=args.season,
        data_as_of=as_of,
    )
    print(
        f"wrote {args.season} preseason forecasts for "
        f"{fantasy['player_id'].nunique()} players to {destination}"
    )
    market_path = PROJECT_ROOT / "web" / "market.js"
    if args.refresh or not market_path.exists():
        try:
            write_espn_market(args.season, destination=market_path)
            print(f"wrote ESPN market prior to {market_path}")
        except (URLError, TimeoutError, json.JSONDecodeError) as error:
            print(f"warning: ESPN market refresh failed; retained existing prior: {error}")


def _preseason_backtest(args: argparse.Namespace) -> None:
    config = load_config()
    history = load_player_games(
        list(range(config.first_season, args.last_test_season + 1)),
        positions=config.positions,
    )
    predictions, by_season, summary = walk_forward_preseason_backtest(
        history,
        first_test_season=args.first_test_season,
        last_test_season=args.last_test_season,
        seed=config.random_seed,
    )
    results = PROJECT_ROOT / "results"
    predictions.to_parquet(results / "preseason_backtest_predictions.parquet", index=False)
    by_season.to_csv(results / "preseason_backtest_by_season.csv", index=False)
    summary.to_csv(results / "preseason_backtest_summary.csv", index=False)
    print(summary.round(3).to_string(index=False))


def _espn_market(args: argparse.Namespace) -> None:
    destination = write_espn_market(args.season)
    print(f"wrote ESPN market prior to {destination}")


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
    market_catalog = commands.add_parser("market-catalog-audit")
    market_catalog.add_argument(
        "--kalshi-series",
        nargs="+",
        default=["KXNFLPASSYDS", "KXNFLRSHYDS", "KXNFLRECYDS"],
    )
    market_catalog.add_argument("--kalshi-pages", type=int, default=25)
    market_catalog.add_argument("--polymarket-pages", type=int, default=25)
    market_catalog.set_defaults(handler=_market_catalog_audit)
    market_features = commands.add_parser("market-feature-audit")
    market_features.add_argument("--quotes", required=True)
    market_features.add_argument("--minimum-seasons", type=int, default=3)
    market_features.add_argument("--minimum-rows-per-season", type=int, default=100)
    market_features.set_defaults(handler=_market_feature_audit)
    draft_board = commands.add_parser("draft-board")
    draft_board.add_argument("--season", type=int)
    draft_board.set_defaults(handler=_draft_board)
    draft_policy = commands.add_parser("draft-policy-stress-test")
    draft_policy.add_argument("--season", type=int)
    draft_policy.add_argument("--teams", type=int, default=12)
    draft_policy.add_argument("--rounds", type=int, default=12)
    draft_policy.add_argument(
        "--scenarios", nargs="+", default=["balanced", "rb_rush", "wr_rush"]
    )
    draft_policy.set_defaults(handler=_draft_policy_stress_test)
    preseason = commands.add_parser("preseason-forecast")
    preseason.add_argument("--season", type=int, required=True)
    preseason.add_argument("--refresh", action="store_true")
    preseason.set_defaults(handler=_preseason_forecast)
    preseason_backtest = commands.add_parser("preseason-backtest")
    preseason_backtest.add_argument("--first-test-season", type=int, default=2018)
    preseason_backtest.add_argument("--last-test-season", type=int, default=2024)
    preseason_backtest.set_defaults(handler=_preseason_backtest)
    espn_market = commands.add_parser("espn-market")
    espn_market.add_argument("--season", type=int, required=True)
    espn_market.set_defaults(handler=_espn_market)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.handler(args)


if __name__ == "__main__":
    main()
