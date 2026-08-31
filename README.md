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

Run `nfl-fantasy draft-board`, then open `web/index.html`. The board shows the
latest available out-of-sample development projections, supports search and
position filters, expands each player into opponent-aware game-by-game and
component projections, and stores Mine/Taken actions and undo history in the
local browser. It is a model-inspection view until a current-season production
forecast and final league roster settings are available.

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

Because the current board is built from the completed 2024 validation season,
it also reports and sorts by actual fantasy points at the season and game level.
Actual outcomes are evaluation context only and do not enter the draft-value
calculation.

Every player row shows two paired audits: live model recommendation versus
hindsight format value from actual outcomes, and model projected-points rank
versus actual-points rank. The hindsight column recomputes replacement value
from realized scoring under the selected league size; it is not a claim that a
single static order is a globally optimal draft.

The public GitHub Pages site contains only this draft-board interface. Pushes to
`main` run the test suite and deploy the static `web/` directory through
`.github/workflows/pages.yml`.

See `docs/METHODOLOGY.md`, `docs/SOURCES.md`, and `results/MODEL_CARD.md`.
