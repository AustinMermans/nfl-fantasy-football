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
nfl-fantasy draft-policy-backtest --team-sizes 8 10 12 14
nfl-fantasy preseason-forecast --season 2026 --refresh
nfl-fantasy season-forecast --season 2026 --refresh
nfl-fantasy preseason-backtest
nfl-fantasy espn-market --season 2026
nfl-fantasy sleeper-market --season 2026
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
The full draft ledger is editable: any pick can be replaced, reassigned, moved,
deleted, or inserted after a missed entry.
You can also give a draft a unique name, save multiple draft records, reopen them,
and continue with automatic local saves after every pick or setting change. Names
are unique without regard to capitalization. These records stay in that browser
on that device; the static GitHub Pages site does not sync them between devices.

The published board now runs the frozen component-model choices as a current
2026 preseason forecast. The production command refits those selected models
through completed 2025 games and forecasts every 2026 matchup from the active
Week 1 roster, the latest daily depth chart, current schedule, and available
game lines. Each future week is featurized independently from completed history,
so an unplayed earlier week is never treated as a zero-stat result.

`season-forecast` is the daily production entry point. Before Week 1 it emits
the preseason board. Once final scores and weekly stats are available, it fixes
realized points, removes completed game IDs from the future schedule, and
publishes a separate rest-of-season forecast. The Week-0 draft projection is
preserved rather than rewritten by later information.

The rest-of-season mean is an empirical-Bayes blend of the frozen preseason
prior and the current opponent-aware weekly model. The preseason model supplies
the complete Week-0 center; current evidence gains weight only as games are
played, with position-specific prior sample sizes. The published mean remains
unconditional because the season-total target already includes missed games.
Veterans below the season ensemble's minimum-history threshold use a labeled
current depth-role prior rather than silently reverting to the game model.
The UI separately reports scenario expected games, projected final points, and
league-specific value over replacement.

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
lineups, with eight bench slots. A bench player earns value when he beats a
rostered starter or weekly position-level waiver replacement during a bye or a
sampled high outcome. Position-specific volatility comes from 2018-2024
expanding-window out-of-sample residuals. Rookie P10/P50/P90 remains a displayed
historical analog range, but it does not affect recommendation utility until its
coverage is validated in frozen preseason folds.

Each outcome path also samples persistent injury absences from position-level
onset and duration baselines. Generic paths are mean-preserving, so they change
the insurance value of bench depth without subtracting injury risk from the
published point forecast a second time. A current Out/Doubtful/Questionable
designation applies only to its reported game week and is not normalized away.
Player recurrence, severity, and BMI modifiers remain audit-only because the
historical active-roster panel excludes many IR/PUP spells.

The default live recommendation is now the strongest validated policy: take the
best available player in the selected market order while preserving the ability
to complete a legal roster. The room market can be ESPN, Sleeper half-PPR ADP,
or their mean; ESPN remains the default for an ESPN-hosted draft. Market ADP is
an opponent and timing input and never changes the published player forecast.

The projection-based weekly-roster and probability-lookahead policies remain
selectable experiments. At every Mine/Taken action they recompute snake state,
infer roster needs, update a Bayesian room-style mixture, and run 256 common-seed
simulations of intervening selections. They are no longer the default because
they failed the independent historical promotion test below.
Controls support 8-16 teams, any snake slot, Standard/Half/Full PPR, four- or
six-point passing touchdowns, interception scoring, and RB/WR stress scenarios.

Current ESPN and Sleeper snapshots are deployed. Sleeper's current projection
feed is used only as a cross-check because it does not provide the complete
league-size-specific historical series needed by this backtest.

`draft-policy-stress-test` replays every snake slot against balanced, RB-run,
and WR-run opponent policies and reports projected and realized starter points.
On the 2024 diagnostic, next-turn lookahead beats a fixed format-value list but
does not consistently beat a simpler roster-aware greedy policy: it wins the RB
run and trails slightly in balanced and WR-run rooms. The report is written to
`results/draft_policy_stress_test.csv`.

`draft-policy-backtest` is the valid preseason policy evaluation. It uses
MyFantasyLeague AUG15 ADP by season and league size, frozen Week-0 model
forecasts, fixed legal roster-aware ADP opponents, and realized managed weekly
lineups. Policies were selected on 2019-2023 and evaluated once on 2024.
Development chose zero model weight in 8-, 10-, 12-, and 14-team leagues. On the
2024 holdout, the selected candidates trailed legal ADP by `6.5`, `12.7`, `14.7`,
and `16.5` H2H win-rate percentage points, respectively. The failed candidates
were not promoted; legal ADP is the deployed default.

This result does not prove ADP is universally optimal. It establishes that the
current forecast and heuristic draft layer have not beaten the much stronger
market baseline under this simulation design. Raw manager-level draft sequences,
auction values, trades, waivers, and playoff scheduling remain outside the test.

The current board omits hindsight and actual columns until 2026 games are
completed. Historical validation outputs remain in `results/`; no realized
outcome enters the live recommendation or replacement-value calculation.

Starter information comes from the latest nflverse depth chart and active
roster. Detailed injury designations are ingested when a current nflverse injury
file exists. Before the league publishes that report, the board displays
"unavailable" and treats missing injury data as unknown, never as healthy.
The random injury prior still runs when a current report is unavailable. When a
report is present, Out/Doubtful/Questionable status applies to its exact report week.

The public GitHub Pages site contains draft and rest-of-season views. Pushes to
`main` run the test suite and deploy the static `web/` directory through
`.github/workflows/pages.yml`. The workflow also refreshes and deploys current
inputs daily at 11:00 UTC, which is 4:00 AM Pacific during daylight time.

See `docs/DRAFT_DECISION_MODEL.md`, `docs/METHODOLOGY.md`, `docs/SOURCES.md`,
and `results/MODEL_CARD.md`.
