from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.error import URLError

import pandas as pd

from .calibration import nested_calibration_backtest
from .config import PROJECT_ROOT, load_config
from .data import download_nflverse, load_player_games
from .draft_board import (
    build_player_rankings,
    export_draft_board,
    export_preseason_board,
)
from .draft_backtest import (
    add_market_implied_points,
    build_historical_player_pool,
    fetch_mfl_adp_snapshot,
    policy_grid,
    simulate_historical_draft,
    summarize_policy_results,
)
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
from .opponent_choice import chronological_choice_backtest
from .production import build_season_forecasts, write_production_artifacts
from .preseason import walk_forward_preseason_backtest
from .sleeper import write_sleeper_market
from .sleeper_drafts import collect_sleeper_draft_corpus


DEFAULT_TARGETS = ("passing_yards", "rushing_yards", "receiving_yards")


def _build_dataset(args: argparse.Namespace) -> None:
    config = load_config()
    last = (
        config.locked_test_season
        if args.include_holdout
        else config.development_end_season
    )
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
                "last_close": catalog["close_time"].max()
                if not catalog.empty
                else None,
                "catalog_volume": float(catalog["volume"].fillna(0).sum())
                if not catalog.empty
                else 0.0,
                "series_volume": pd.to_numeric(item.get("volume_fp"), errors="coerce"),
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


def _draft_policy_backtest(args: argparse.Namespace) -> None:
    """Tune a market-anchored policy, then evaluate one untouched season."""
    history = pd.read_parquet(
        PROJECT_ROOT / "data" / "processed" / "player_games.parquet"
    )
    preseason = pd.read_parquet(
        PROJECT_ROOT / "results" / "preseason_backtest_predictions.parquet"
    )
    cache_dir = PROJECT_ROOT / "data" / "raw" / "mfl_adp"
    seasons = list(range(args.first_season, args.holdout_season + 1))
    pools: dict[tuple[int, int], pd.DataFrame] = {}
    coverage_rows: list[dict[str, object]] = []
    for teams in args.team_sizes:
        prior_pools: list[pd.DataFrame] = []
        for season in seasons:
            print(f"building {season} {teams}-team market pool...", flush=True)
            adp = fetch_mfl_adp_snapshot(
                season,
                teams,
                cache_dir=cache_dir,
                period=args.period,
                cutoff=args.cutoff,
                refresh=args.refresh,
            )
            pool = build_historical_player_pool(history, preseason, adp, season=season)
            training = (
                pd.concat(prior_pools, ignore_index=True)
                if prior_pools
                else pd.DataFrame(columns=["position", "adp", "actual_points"])
            )
            pool = add_market_implied_points(pool, training)
            pools[(season, teams)] = pool
            coverage_rows.append(
                {
                    "season": season,
                    "teams": teams,
                    "market_players": len(pool),
                    "realized_match_rate": float(
                        pool["actual_weekly"].map(bool).mean()
                    ),
                    "model_match_rate": float(pool["season_ensemble"].notna().mean()),
                }
            )
            prior_pools.append(pool)

    configurations = policy_grid(
        model_weights=args.model_weights,
        bench_weights=args.bench_weights,
        adp_reaches=args.adp_reaches or [None],
        roster_profiles=args.roster_profiles,
        lookahead_values=[mode == "lookahead" for mode in args.policy_modes],
        decision_rules=args.decision_rules,
        timing_profiles=args.timing_profiles,
    )
    development_rows: list[dict[str, object]] = []
    baseline_rows: list[dict[str, object]] = []
    development_seasons = range(args.first_season + 1, args.holdout_season)
    development_repetitions = (
        1 if args.room_noise <= 0 else args.development_repetitions
    )
    holdout_repetitions = 1 if args.room_noise <= 0 else args.holdout_repetitions
    for teams in args.team_sizes:
        print(
            f"simulating development policies for {teams}-team leagues...", flush=True
        )
        for season in development_seasons:
            pool = pools[(season, teams)]
            for draft_slot in range(1, teams + 1):
                for repetition in range(development_repetitions):
                    noise_seed = (
                        season * 1_000_000
                        + teams * 10_000
                        + draft_slot * 100
                        + repetition
                    )
                    baseline = simulate_historical_draft(
                        pool,
                        teams=teams,
                        draft_slot=draft_slot,
                        rounds=args.rounds,
                        strategy="adp",
                        room_noise=args.room_noise,
                        noise_seed=noise_seed,
                        lookahead_samples=args.lookahead_samples,
                        lineup_mode=args.lineup_mode,
                    )
                    baseline_rows.append(
                        {
                            **baseline,
                            "season": season,
                            "split": "development",
                            "room_repetition": repetition,
                        }
                    )
                    for config in configurations:
                        result = simulate_historical_draft(
                            pool,
                            teams=teams,
                            draft_slot=draft_slot,
                            rounds=args.rounds,
                            strategy="hybrid",
                            policy=config,
                            room_noise=args.room_noise,
                            noise_seed=noise_seed,
                            lookahead_samples=args.lookahead_samples,
                            lineup_mode=args.lineup_mode,
                        )
                        development_rows.append(
                            {
                                **result,
                                "season": season,
                                "split": "development",
                                "room_repetition": repetition,
                                "model_weight": config.model_weight,
                                "bench_weight": config.bench_weight,
                                "lookahead": config.lookahead,
                                "max_adp_reach": config.max_adp_reach,
                                "roster_profile": config.roster_profile,
                                "decision_rule": config.decision_rule,
                                "timing_profile": config.timing_profile,
                            }
                        )

    development = pd.DataFrame(development_rows)
    selection = (
        development.groupby(
            [
                "teams",
                "policy",
                "model_weight",
                "bench_weight",
                "lookahead",
                "max_adp_reach",
                "roster_profile",
                "decision_rule",
                "timing_profile",
            ],
            as_index=False,
            dropna=False,
        )
        .agg(
            development_win_rate=("h2h_win_rate", "mean"),
            development_points=("managed_points_week_1_17", "mean"),
        )
        .sort_values(
            ["teams", "development_win_rate", "development_points", "model_weight"],
            ascending=[True, False, False, True],
        )
        .groupby("teams", as_index=False)
        .first()
    )

    holdout_rows: list[dict[str, object]] = []
    for selected in selection.itertuples():
        teams = int(selected.teams)
        config = next(item for item in configurations if item.name == selected.policy)
        pool = pools[(args.holdout_season, teams)]
        for draft_slot in range(1, teams + 1):
            for repetition in range(holdout_repetitions):
                noise_seed = (
                    args.holdout_season * 1_000_000
                    + teams * 10_000
                    + draft_slot * 100
                    + repetition
                )
                for strategy, policy in (("adp", None), ("hybrid", config)):
                    result = simulate_historical_draft(
                        pool,
                        teams=teams,
                        draft_slot=draft_slot,
                        rounds=args.rounds,
                        strategy=strategy,
                        policy=policy,
                        room_noise=args.room_noise,
                        noise_seed=noise_seed,
                        lookahead_samples=args.lookahead_samples,
                        lineup_mode=args.lineup_mode,
                    )
                    holdout_rows.append(
                        {
                            **result,
                            "season": args.holdout_season,
                            "split": "holdout",
                            "room_repetition": repetition,
                            "model_weight": config.model_weight if policy else 0.0,
                            "bench_weight": config.bench_weight if policy else 0.0,
                            "lookahead": config.lookahead if policy else False,
                            "max_adp_reach": (
                                config.max_adp_reach if policy is not None else 0.0
                            ),
                            "roster_profile": (
                                config.roster_profile if policy else "league"
                            ),
                            "decision_rule": (
                                config.decision_rule if policy else "adp"
                            ),
                            "timing_profile": (
                                config.timing_profile if policy else "none"
                            ),
                        }
                    )

    all_results = pd.concat(
        [pd.DataFrame(baseline_rows), development, pd.DataFrame(holdout_rows)],
        ignore_index=True,
    )
    summary = summarize_policy_results(all_results)
    results_dir = PROJECT_ROOT / "results"
    suffix = f"_{args.output_suffix}" if args.output_suffix else ""
    all_results.to_csv(results_dir / f"draft_policy_backtest{suffix}.csv", index=False)
    summary.to_csv(
        results_dir / f"draft_policy_backtest_summary{suffix}.csv", index=False
    )
    selection.to_csv(results_dir / f"draft_policy_selected{suffix}.csv", index=False)
    pd.DataFrame(coverage_rows).to_csv(
        results_dir / f"draft_policy_market_coverage{suffix}.csv", index=False
    )
    print("\nselected policies")
    print(selection.round(4).to_string(index=False))
    print("\nholdout results")
    print(summary[summary["split"].eq("holdout")].round(4).to_string(index=False))
    print(f"wrote historical draft-policy results to {results_dir}")


def _preseason_forecast(args: argparse.Namespace) -> None:
    fantasy, components, features, as_of, actual_history, completed_week = (
        build_season_forecasts(args.season, refresh=args.refresh)
    )
    write_production_artifacts(fantasy, components, features)
    destination = export_preseason_board(
        fantasy,
        components,
        features,
        season=args.season,
        data_as_of=as_of,
        actual_history=actual_history,
        completed_week=completed_week,
    )
    print(
        f"wrote {args.season} {'rest-of-season' if completed_week else 'preseason'} forecasts for "
        f"{fantasy['player_id'].nunique()} players to {destination}"
    )
    market_path = PROJECT_ROOT / "web" / "market.js"
    if args.refresh or not market_path.exists():
        try:
            write_espn_market(args.season, destination=market_path)
            print(f"wrote ESPN market prior to {market_path}")
        except (URLError, TimeoutError, json.JSONDecodeError) as error:
            print(
                f"warning: ESPN market refresh failed; retained existing prior: {error}"
            )
    sleeper_path = PROJECT_ROOT / "web" / "sleeper.js"
    if args.refresh or not sleeper_path.exists():
        try:
            write_sleeper_market(args.season, destination=sleeper_path)
            print(f"wrote Sleeper market cross-check to {sleeper_path}")
        except (URLError, TimeoutError, json.JSONDecodeError) as error:
            print(
                f"warning: Sleeper market refresh failed; retained existing cross-check: {error}"
            )


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
    predictions.to_parquet(
        results / "preseason_backtest_predictions.parquet", index=False
    )
    by_season.to_csv(results / "preseason_backtest_by_season.csv", index=False)
    summary.to_csv(results / "preseason_backtest_summary.csv", index=False)
    print(summary.round(3).to_string(index=False))


def _espn_market(args: argparse.Namespace) -> None:
    destination = write_espn_market(args.season)
    print(f"wrote ESPN market prior to {destination}")


def _sleeper_market(args: argparse.Namespace) -> None:
    destination = write_sleeper_market(args.season)
    print(f"wrote Sleeper market cross-check to {destination}")


def _sleeper_draft_corpus(args: argparse.Namespace) -> None:
    if not any((args.user_ids, args.league_ids, args.draft_ids)):
        raise ValueError("provide at least one --user-id, --league-id, or --draft-id")
    destination = Path(args.destination) if args.destination else None
    picks, manifest = collect_sleeper_draft_corpus(
        seasons=args.seasons,
        user_ids=args.user_ids,
        league_ids=args.league_ids,
        draft_ids=args.draft_ids,
        team_sizes=args.team_sizes,
        minimum_rounds=args.minimum_rounds,
        maximum_drafts=args.maximum_drafts,
        destination=destination,
    )
    print(f"wrote normalized Sleeper picks to {picks}")
    print(f"wrote PII-minimized corpus manifest to {manifest}")


def _opponent_choice_backtest(args: argparse.Namespace) -> None:
    source = Path(args.picks)
    picks = pd.read_parquet(source)
    results, coefficients = chronological_choice_backtest(
        picks,
        minimum_train_drafts=args.minimum_train_drafts,
        test_drafts_per_fold=args.test_drafts_per_fold,
        choice_set_size=args.choice_set_size,
        l2=args.l2,
    )
    if results.empty:
        raise ValueError(
            "no format has enough chronological drafts for the requested folds"
        )
    output = PROJECT_ROOT / "results"
    suffix = f"_{args.output_suffix}" if args.output_suffix else ""
    result_path = output / f"opponent_choice_backtest{suffix}.csv"
    coefficient_path = output / f"opponent_choice_coefficients{suffix}.csv"
    results.to_csv(result_path, index=False)
    coefficients.to_csv(coefficient_path, index=False)
    comparison = results.groupby("strategy", as_index=False).agg(
        folds=("fold", "count"),
        known_pick_coverage=("known_pick_coverage", "mean"),
        log_loss=("log_loss", "mean"),
        multiclass_brier=("multiclass_brier", "mean"),
        top1_accuracy=("top1_accuracy", "mean"),
        top5_accuracy=("top5_accuracy", "mean"),
        ici=("ici", "mean"),
        e50=("e50", "mean"),
        e90=("e90", "mean"),
        emax=("emax", "mean"),
        calibration_intercept=("calibration_intercept", "mean"),
        calibration_slope=("calibration_slope", "mean"),
    )
    print(comparison.round(4).to_string(index=False))
    print(f"wrote opponent choice results to {result_path}")
    print(f"wrote opponent choice coefficients to {coefficient_path}")


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
            "recent_mean",
            "player_form",
            "workload",
            "screened",
            "context",
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
    policy_backtest = commands.add_parser("draft-policy-backtest")
    policy_backtest.add_argument("--first-season", type=int, default=2018)
    policy_backtest.add_argument("--holdout-season", type=int, default=2024)
    policy_backtest.add_argument(
        "--team-sizes", nargs="+", type=int, default=[8, 10, 12, 14]
    )
    policy_backtest.add_argument("--rounds", type=int, default=17)
    policy_backtest.add_argument("--period", default="AUG15")
    policy_backtest.add_argument("--cutoff", type=int, default=1)
    policy_backtest.add_argument(
        "--model-weights", nargs="+", type=float, default=[0.0, 0.25, 0.5]
    )
    policy_backtest.add_argument(
        "--bench-weights", nargs="+", type=float, default=[0.15]
    )
    policy_backtest.add_argument("--refresh", action="store_true")
    policy_backtest.add_argument("--room-noise", type=float, default=0.0)
    policy_backtest.add_argument("--development-repetitions", type=int, default=1)
    policy_backtest.add_argument("--holdout-repetitions", type=int, default=1)
    policy_backtest.add_argument("--lookahead-samples", type=int, default=2)
    policy_backtest.add_argument("--adp-reaches", nargs="+", type=float)
    policy_backtest.add_argument(
        "--roster-profiles",
        nargs="+",
        choices=[
            "league",
            "one_qb_one_te",
            "one_qb_two_te",
            "two_qb_one_te",
            "two_qb_two_te",
        ],
        default=["league"],
    )
    policy_backtest.add_argument(
        "--lineup-mode", choices=["managed", "best_ball"], default="managed"
    )
    policy_backtest.add_argument(
        "--policy-modes",
        nargs="+",
        choices=["greedy", "lookahead"],
        default=["greedy", "lookahead"],
    )
    policy_backtest.add_argument(
        "--decision-rules",
        nargs="+",
        choices=["adp", "utility"],
        default=["utility"],
    )
    policy_backtest.add_argument(
        "--timing-profiles",
        nargs="+",
        choices=["none", "last_k", "late_reserves"],
        default=["none"],
    )
    policy_backtest.add_argument("--output-suffix", default="")
    policy_backtest.set_defaults(handler=_draft_policy_backtest)
    preseason = commands.add_parser("preseason-forecast")
    preseason.add_argument("--season", type=int, required=True)
    preseason.add_argument("--refresh", action="store_true")
    preseason.set_defaults(handler=_preseason_forecast)
    season_forecast = commands.add_parser("season-forecast")
    season_forecast.add_argument("--season", type=int, required=True)
    season_forecast.add_argument("--refresh", action="store_true")
    season_forecast.set_defaults(handler=_preseason_forecast)
    preseason_backtest = commands.add_parser("preseason-backtest")
    preseason_backtest.add_argument("--first-test-season", type=int, default=2018)
    preseason_backtest.add_argument("--last-test-season", type=int, default=2024)
    preseason_backtest.set_defaults(handler=_preseason_backtest)
    espn_market = commands.add_parser("espn-market")
    espn_market.add_argument("--season", type=int, required=True)
    espn_market.set_defaults(handler=_espn_market)
    sleeper_market = commands.add_parser("sleeper-market")
    sleeper_market.add_argument("--season", type=int, required=True)
    sleeper_market.set_defaults(handler=_sleeper_market)
    sleeper_corpus = commands.add_parser("sleeper-draft-corpus")
    sleeper_corpus.add_argument("--seasons", nargs="+", type=int, required=True)
    sleeper_corpus.add_argument("--user-id", dest="user_ids", action="append", default=[])
    sleeper_corpus.add_argument(
        "--league-id", dest="league_ids", action="append", default=[]
    )
    sleeper_corpus.add_argument(
        "--draft-id", dest="draft_ids", action="append", default=[]
    )
    sleeper_corpus.add_argument(
        "--team-sizes", nargs="+", type=int, default=[8, 10, 12, 14]
    )
    sleeper_corpus.add_argument("--minimum-rounds", type=int, default=12)
    sleeper_corpus.add_argument("--maximum-drafts", type=int, default=500)
    sleeper_corpus.add_argument("--destination")
    sleeper_corpus.set_defaults(handler=_sleeper_draft_corpus)
    choice_backtest = commands.add_parser("opponent-choice-backtest")
    choice_backtest.add_argument(
        "--picks",
        default=str(
            PROJECT_ROOT / "data" / "processed" / "sleeper_draft_picks.parquet"
        ),
    )
    choice_backtest.add_argument("--minimum-train-drafts", type=int, default=20)
    choice_backtest.add_argument("--test-drafts-per-fold", type=int, default=10)
    choice_backtest.add_argument("--choice-set-size", type=int, default=50)
    choice_backtest.add_argument("--l2", type=float, default=1.0)
    choice_backtest.add_argument("--output-suffix", default="")
    choice_backtest.set_defaults(handler=_opponent_choice_backtest)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.handler(args)


if __name__ == "__main__":
    main()
