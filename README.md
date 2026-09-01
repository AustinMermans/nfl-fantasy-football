# NFL Fantasy Football

Leakage-safe NFL player-stat forecasting research, with fantasy scoring, draft
support, and season tracking as downstream layers.

**Draft board:** [austinmermans.github.io/nfl-fantasy-football](https://austinmermans.github.io/nfl-fantasy-football/)

## Status

The development pipeline builds weekly active-roster player-game rows for
2012-2024, forecasts 25 player-stat fields, models participation, and
uses expanding-season validation. The 2025 season is a locked final test set and
has not been used for model selection.

## Current Workstreams

- Historical player, snap, roster, injury, schedule, and market ingestion
- Weekly component-stat and participation projections
- Scoring-format-aware player values
- Draft rankings and live draft assistance
- Roster, waiver, trade, and matchup tracking
- Walk-forward model validation and calibration

## Development

```bash
python -m pip install -e '.[dev]'
nfl-fantasy build-dataset
nfl-fantasy participation-backtest
nfl-fantasy calibration-backtest
nfl-fantasy backtest
nfl-fantasy factor-study
nfl-fantasy fantasy-evaluation
nfl-fantasy market-catalog-audit
nfl-fantasy market-feature-audit --quotes path/to/canonical_quotes.parquet
nfl-fantasy draft-board
nfl-fantasy draft-policy-stress-test
nfl-fantasy preseason-forecast --season 2026 --refresh
python -m pytest
```

Raw nflverse assets are cached under `data/raw/` and ignored by Git. Generated
development reports are written under `results/`. Do not use
`--include-holdout` during feature or model iteration.

## Player markets

Kalshi and Polymarket are wired as public, read-only shadow sources. The market
layer discovers NFL products, paginates live and archived catalogs, converts
Kalshi candlesticks and Polymarket CLOB histories to one quote schema, rejects
post-kickoff quotes, and builds source-robust medians from alternate-line
ladders. Run `nfl-fantasy market-catalog-audit` to refresh source coverage.

The opt-in `player_market` feature set is not used by the published projections
yet. `market-feature-audit` requires mapped canonical quotes and enforces a
minimum common-support history before predictive testing. Promotion still
requires an expanding-window improvement over the same player-games, the random
feature threshold, and Holm correction. This prevents a short or selectively
available prop history from masquerading as model improvement.

## Draft board

Run `nfl-fantasy draft-board` to rebuild the retrospective validation view, or
`nfl-fantasy preseason-forecast --season 2026 --refresh` to rebuild the current
board, then open `web/index.html`. The interface supports search and position
filters, expands each player into opponent-aware game-by-game and component
projections, and stores Mine/Taken actions and undo history in the local browser.

The published board now runs the frozen component-model choices as a current
2026 preseason forecast. The production command refits those selected models
through completed 2025 games and forecasts every 2026 matchup from the active
Week 1 roster, the latest daily depth chart, current schedule, and available
game lines. Each future week is featurized independently from completed history,
so an unplayed earlier week is never treated as a zero-stat result.

Rookies receive an empirical predictive distribution from 2012-2025 rookie
seasons, smoothed by position and log draft-pick distance and combined with the
current depth role. The board publishes P10/P50/P90 and effective analog sample
size. Experienced reserves whose stale history implies starter volume are
capped at their current role median. The audit is retained in
`results/current_role_adjustments.csv`.

The live draft sort is a sequential recommendation rather than a fixed weighted
list. League size and lineup slots determine replacement levels directly: base
starters are allocated first, then FLEX demand goes to the highest projected
remaining RB/WR/TE players. There are no hand-set QB, TE, or K discounts.

Player value is evaluated as expected points from 18 separately managed weekly
lineups, with four bench slots. A bench player earns value when he beats a
rostered starter or weekly position-level waiver replacement during a bye or a
sampled high outcome. Position-specific volatility comes from 2018-2024
expanding-window out-of-sample residuals. Rookie P10/P50/P90 is sampled as a
season-level role state, preserving stash upside without a manual rookie bonus.

At every Mine/Taken action, the board recomputes the snake state and runs 16
common-seed simulations of the intervening picks. Opponents follow a
roster-aware quantal-response policy over format-value rank. Logged opponent
picks update a Bayesian mixture of Balanced, RB-heavy, WR-heavy, Early-QB, and
Zero-RB room styles. Candidate utility is the expected managed weekly lineup
value after the next turn. Once the 12-player roster is full, a candidate must
improve the roster after the weakest asset is dropped.
Controls support 8-16 teams, any snake slot, Standard/Half/Full PPR, four- or
six-point passing touchdowns, interception scoring, and RB/WR stress scenarios.

This is a low-confidence Bayesian response model, not a fitted ADP-survival
model or a Nash-equilibrium claim. The next production step is daily timestamped
ADP snapshots and rolling-origin calibration against raw draft sequences.

`draft-policy-stress-test` replays every snake slot against balanced, RB-run,
and WR-run opponent policies and reports projected and realized starter points.
On the 2024 diagnostic, next-turn lookahead beats a fixed format-value list but
does not consistently beat a simpler roster-aware greedy policy: it wins the RB
run and trails slightly in balanced and WR-run rooms. The report is written to
`results/draft_policy_stress_test.csv`.

Because the old lookahead failed to dominate roster-aware greedy, the new
probability lookahead is presented as an unvalidated decision aid and can be
switched to weekly roster value.

This is deliberately called a stress test, not a preseason backtest. The 2024
board aggregates weekly out-of-sample forecasts that use information available
before each game, including in-season role and injury updates, rather than one
frozen snapshot available before Week 1. A valid preseason policy evaluation
still requires yearly Week-0 feature snapshots and point-in-time ADP.

The current board omits hindsight and actual columns until 2026 games are
completed. Historical validation outputs remain in `results/`; no realized
outcome enters the live recommendation or replacement-value calculation.

Starter information comes from the latest nflverse depth chart and active
roster. Detailed injury designations are ingested when a current nflverse injury
file exists. Before the league publishes that report, the board displays
"unavailable" and treats missing injury data as unknown, never as healthy.

The public GitHub Pages site contains only this draft-board interface. Pushes to
`main` run the test suite and deploy the static `web/` directory through
`.github/workflows/pages.yml`. The workflow also refreshes and deploys current
inputs daily at 11:00 UTC, which is 4:00 AM Pacific during daylight time.

See `docs/DRAFT_DECISION_MODEL.md`, `docs/METHODOLOGY.md`, `docs/SOURCES.md`,
and `results/MODEL_CARD.md`.
