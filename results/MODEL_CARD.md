# NFL Player Forecast Model Card

## Status

Development model. The 2025 final holdout has not been opened. Traditional
non-PPR scoring is now the working assumption. The draft board publishes the
latest 2024 out-of-sample development ranking for model inspection; it is not a
current-season preseason ranking or a globally optimized draft order. The live
board now accepts league size and draft slot, with the traditional lineup shown
below as its default.

## Data and cohort

- Training origin: 2012
- Expanding validation seasons: 2018-2024
- Final locked test: 2025
- Population: weekly active-roster QB/RB/FB/WR/TE/K players with scheduled games
- Development rows before history filters: 100,274
- Component targets: 25 scoring, opportunity, and diagnostic statistics

## Current selections

Participation uses nonlinear context features. Across seven development folds it
has mean ROC AUC `0.9694`, log loss `0.1718`, and Brier score `0.0495` over
50,710 predictions. Nested calibration selects intercept-only adjustment by log
loss (`0.16508` versus `0.16559` identity on the five eligible nested folds).
Beta calibration has slightly better mean Brier than intercept-only but worse
log loss; isotonic reduces miscalibration but worsens log loss and introduces
ranking ties.

The nonlinear model beats the twelve-game recent-mean baseline on the original
11 offensive targets in both evaluation populations. Fantasy-relevant results are:

| Target | Selected layer | RMSE | Baseline RMSE | Gain |
|:--|:--|--:|--:|--:|
| Attempts | Context | 11.104 | 12.658 | 12.3% |
| Passing yards | Context | 88.548 | 97.388 | 9.1% |
| Passing TDs | Context | 1.115 | 1.137 | 1.9% |
| Interceptions | Context | 0.842 | 0.886 | 5.0% |
| Carries | Context | 2.957 | 3.075 | 3.8% |
| Rushing yards | Context | 18.227 | 18.692 | 2.5% |
| Rushing TDs | Market context | 0.355 | 0.365 | 2.8% |
| Targets | Context | 2.516 | 2.601 | 3.3% |
| Receptions | Context | 1.947 | 1.998 | 2.6% |
| Receiving yards | Market context | 26.697 | 27.490 | 2.9% |
| Receiving TDs | Market context | 0.432 | 0.447 | 3.4% |

The raw table ranks market context first for most targets, but deployment uses
the simpler context model unless the market-layer improvement survives Holm
correction across all 11 targets. Closing spread/total passes that gate only for
receiving yards (`p_adj=0.0045`), receiving touchdowns (`0.0126`), and rushing
touchdowns (`0.0127`). Kalshi and Polymarket are deployed as shadow data feeds,
not as official projection features.

The shadow layer now includes public catalog discovery, live/historical
pagination, Kalshi candlestick and Polymarket CLOB normalization, strict
pre-kickoff selection, bid/ask and liquidity diagnostics, alternate-line
market-implied medians, and an opt-in `player_market` feature family. The August
31, 2026 audit found 3,584 Kalshi passing-yard, 4,746 rushing-yard, and 10,376
receiving-yard contracts, with history beginning October 6, 2025. Polymarket
had 948 recognized anytime-touchdown contracts from September 2024 onward, but
only one recognized passing-yard contract. These are catalog counts before
player/game mapping and quote-quality filters.

No market-prop coefficient or blend weight has been fit. Kalshi begins after the
2012-2024 development window and overlaps the locked 2025 holdout; using it for
selection now would contaminate the final test. Polymarket's 2024 yardage sample
is too sparse. The official model therefore remains unchanged while the feeds
collect forward shadow predictions.

Every context forecast is opponent-aware. It includes the opposing defense's
strictly lagged eight-game allowance for the target statistic and position,
along with venue, rest, weather, surface, injury, and workload context. The
admitted market layer also includes closing spread, game total, and team and
opponent implied points. This is game-level matchup modeling; it is not yet a
fantasy-roster H2H simulator or matchup win-probability model.

The expanded field study adds completions, all two-point conversions, lost
fumbles, special-teams touchdowns, PATs, and six field-goal distance buckets.
Learned models improve development RMSE for every new field except PAT makes and
misses, where the recent-mean baseline remains selected. Full results are in
`results/expanded_backtest_summary.csv`.

When the selected component forecasts are recombined under traditional non-PPR
scoring, the fantasy-relevant player-game forecast has MAE `4.13`, RMSE `5.63`,
and Spearman correlation `0.653`. The recent-component baseline has MAE `4.23`,
RMSE `5.82`, and Spearman `0.616`, so the model improves RMSE by `3.4%` and
meaningfully improves ordering while remaining only moderately precise at the
single-game level.

The generated draft board aggregates those game-level forecasts by player for
the 2024 validation season. It reports projected season points, points per game,
position rank, model lift versus recent form, and the selected component-stat
forecasts. Each player expands to the underlying weekly opponent, fantasy-point,
and position-relevant component forecasts. The board deliberately labels the
season and development status to avoid presenting retrospective validation
output as a live forecast.

The validation board also exposes actual 2024 fantasy points by season and game
for direct forecast auditing. Actual outcomes are display-only and do not enter
projection ranks, replacement values, or draft ranks.

Rows report four distinct ranks: a live recommendation and hindsight format
value, plus raw model and actual season-points ranks. The hindsight ranking is
an evaluation benchmark and never enters the recommendation.

Replacement demand is now derived from the selected team count and the default
1QB/2RB/2WR/1TE/1 FLEX/1K starting lineup. Base slots are allocated first and
FLEX slots go to the highest projected remaining RB/WR/TE players. Draft value
is the unweighted point difference from the last format-derived starter; the
former fixed QB12/RB30/WR36/TE12/K12 ranks and `0.55/1.0/1.0/0.8/0.05`
positional multipliers have been removed.

The live layer evaluates the available pool, the user's current roster, snake
slot, picks until the next turn, and a deterministic opponent policy. Each
candidate is evaluated with the best single option at the next turn; empty
starter slots are scored at format-derived replacement. Ordering then considers
expected disappearance and the points gap to the best same-position survivor.
Explicit RB-run and WR-run scenarios expose sensitivity to positional cascades;
an adaptive setting follows a strong recent room run.

The 2024 deterministic stress test covers all 12 snake slots. Mean realized
starter points for next-turn lookahead versus roster-aware greedy selection are
`1393.85` versus `1423.91` in balanced rooms, `1506.23` versus `1476.28` in an
RB run, and `1629.48` versus `1658.15` in a WR run. Lookahead consistently beats
the fixed format-value list, but it does not dominate the stronger comparator.
These values are policy diagnostics, not an independent performance estimate.

## Factor screen

Each context candidate was compared with 100 random controls and seven
season-blocked paired improvements, with Holm correction. No individual
passing-yard candidate passed. Rushing admitted lagged opponent allowance and
week. Receiving admitted closing total, lagged opponent allowance, and
questionable designation. Full nonlinear context remains a candidate where its
cross-fold grouped improvement exceeds the screened subset.

## Known limitations

- Injury reports have no intraday timestamps in the current table; production
  refreshes must preserve the exact report available at forecast time.
- Snap-count and roster feeds can be revised after games; archived point-in-time
  snapshots are preferable for live-production auditability.
- Rookie priors, coaching changes, offensive line quality, depth-chart movement,
  and player transactions are not yet modeled explicitly.
- NGS and advanced charting require common-support studies. Kalshi and
  Polymarket connectors are in shadow mode but still require mapped,
  liquidity-filtered common-support studies before model admission.
- Individual defensive statistics and team D/ST are not yet modeled.
- Kicker single-game ranking is weak. A team-implied-points layer has a modest
  grouped improvement but fails the individual-field multiple-testing gate.
- Component dependence and predictive distributions are not yet simulated, so
  ceiling, floor, best-ball, and head-to-head draft objectives are not available.
- The live draft policy has only a deterministic one-turn lookahead. Historical
  point-in-time ADP, probabilistic player survival, bench option value, and a
  preseason walk-forward draft backtest are not yet available. The current
  stress test aggregates weekly forecasts containing in-season information, so
  recommendation ranks should not be interpreted as a proven optimal policy.

## Deployment gates

1. Run point-in-time audits for injuries, rosters, and player props.
2. Accumulate and map shadow player-prop quotes, then finish their common-support
   and incremental-value studies alongside NGS and charting.
3. Freeze the model and calibration manifest.
4. Open the 2025 holdout once and report every metric without further tuning.
5. Add league scoring, simulate correlated player outcomes, then optimize the draft.
