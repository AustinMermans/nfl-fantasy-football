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
nfl-fantasy draft-board
python -m pytest
```

Raw nflverse assets are cached under `data/raw/` and ignored by Git. Generated
development reports are written under `results/`. Do not use
`--include-holdout` during feature or model iteration.

## Draft board

Run `nfl-fantasy draft-board`, then open `web/index.html`. The board shows the
latest available out-of-sample development projections, supports search and
position filters, expands each player into opponent-aware game-by-game and
component projections, and stores Mine/Taken actions and undo history in the
local browser. It is a model-inspection view until a current-season production
forecast and final league roster settings are available.

The default draft-order sort converts projected points into value over a
position-specific replacement player for a 12-team, 1QB/2RB/2WR/1TE/1 FLEX
format. It applies explicit opportunity-cost discounts to QB, TE, and K. Raw
model season points and points per game remain separate sortable views. This is
a model-based draft heuristic, not market ADP.

Because the current board is built from the completed 2024 validation season,
it also reports and sorts by actual fantasy points at the season and game level.
Actual outcomes are evaluation context only and do not enter the draft-value
calculation.

Every player row shows draft rank, raw model projected-points rank, and realized
actual-points rank side by side.

The public GitHub Pages site contains only this draft-board interface. Pushes to
`main` run the test suite and deploy the static `web/` directory through
`.github/workflows/pages.yml`.

See `docs/METHODOLOGY.md`, `docs/SOURCES.md`, and `results/MODEL_CARD.md`.
