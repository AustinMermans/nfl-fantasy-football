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

Players with no NFL history receive the median model projection of experienced
players at the same position and current depth rank. Experienced players listed
beyond the normal starting depth are capped at that role median when their stale
history would otherwise imply starter volume. These are explicit preseason role
priors, retained in `results/current_role_adjustments.csv` when the command runs.

The live draft sort is a sequential recommendation rather than a fixed weighted
list. League size and lineup slots determine replacement levels directly: base
starters are allocated first, then FLEX demand goes to the highest projected
remaining RB/WR/TE players. There are no hand-set QB, TE, or K discounts.

At every Mine/Taken action, the board recomputes the current snake pick, the
number of selections before the user's next turn, the user's starter
composition, and the players likely to leave the available pool. Candidates are
ordered by projected starter value from the current pick plus the best single
option at the next turn, with empty slots scored at format-derived replacement.
Ties then use expected disappearance and the same-position points gap. Controls
support 8-16 teams, any snake slot, an adaptive
room, a balanced room, and explicit first-two-round RB or WR runs. This is a
deterministic one-turn lookahead using model value as the opponent policy, not
market ADP or a multi-round stochastic draft solution.

`draft-policy-stress-test` replays every snake slot against balanced, RB-run,
and WR-run opponent policies and reports projected and realized starter points.
On the 2024 diagnostic, next-turn lookahead beats a fixed format-value list but
does not consistently beat a simpler roster-aware greedy policy: it wins the RB
run and trails slightly in balanced and WR-run rooms. The report is written to
`results/draft_policy_stress_test.csv`.

Because the stronger comparator wins two of the three current stress cases, the
published board defaults to **Roster value**. **Next-turn lookahead** remains an
explicit policy option for positional-run sensitivity rather than being treated
as universally superior.

This is deliberately called a stress test, not a preseason backtest. The 2024
board aggregates weekly out-of-sample forecasts that use information available
before each game, including in-season role and injury updates, rather than one
frozen snapshot available before Week 1. A valid preseason policy evaluation
still requires yearly Week-0 feature snapshots and point-in-time ADP.

The current board omits hindsight and actual columns until 2026 games are
completed. Historical validation outputs remain in `results/`; no realized
outcome enters the live recommendation or replacement-value calculation.

The public GitHub Pages site contains only this draft-board interface. Pushes to
`main` run the test suite and deploy the static `web/` directory through
`.github/workflows/pages.yml`. The workflow also refreshes and deploys current
inputs daily at 11:00 UTC, which is 4:00 AM Pacific during daylight time.

See `docs/METHODOLOGY.md`, `docs/SOURCES.md`, and `results/MODEL_CARD.md`.
