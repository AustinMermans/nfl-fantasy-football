# NFL Player Forecast Model Card

## Status

Development selections with a production preseason refit. Half PPR is the
default; the board can rescore component forecasts for Standard, Half
PPR, Full PPR, four/six-point passing touchdowns, and interception rules. The draft board now publishes current 2026
preseason forecasts using frozen model choices refit through completed 2025
games. The board accepts league size and draft slot, with the traditional lineup
shown below as its default.

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
2012-2024 development window and Polymarket's 2024 yardage sample is too sparse.
The production refit therefore retains the previously frozen specifications
while the feeds collect forward shadow predictions.

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

When the selected component forecasts are recombined under the deployed half-PPR
scoring, the fantasy-relevant player-game forecast has MAE `4.546`, RMSE `6.085`,
and Spearman correlation `0.645`. The recent-component baseline has MAE `4.662`,
RMSE `6.297`, and Spearman `0.607`, so the model improves RMSE by `3.4%` and
meaningfully improves ordering while remaining only moderately precise at the
single-game level.

The generated draft board aggregates current 2026 game-level forecasts by
player. It reports projected season points, points per game, position rank,
model lift versus recent form, current depth rank, and the selected component-
stat forecasts. Each player expands to the underlying weekly opponent, fantasy-
point, and position-relevant component forecasts. The production refit retains
the specifications selected in walk-forward development; it does not reopen
feature or model selection on 2025.

The current preseason cohort uses the active Week 1 roster and the latest daily
nflverse depth chart. Every future week is featurized independently against
completed 2012-2025 history, preventing earlier unplayed games from entering
later-week rolling features as zeros.

Veteran season totals use a compact Ridge/histogram ensemble built from the
prior two seasons' points, points per game, games, games played, snap share,
age, experience, draft pick, career length, and position. The season model
supplies 100% of every eligible veteran's Week-0 center. Component forecasts determine
weekly matchup shape and gain mean weight only as current-season games are
observed. Veterans below the 20-point minimum-history threshold use a labeled
current position-depth role-prior fallback; they do not revert to the game model.

The season-total model is evaluated with an expanding 2018-2024 walk-forward
window. Against prior-season points, fold-average RMSE improves from `65.024` to
`58.085`, MAE from `48.685` to `44.302`, and Spearman from `0.646` to `0.673`.
For the prior-year top decile, RMSE improves from `102.684` to `83.337` and
Spearman from `0.392` to `0.447`. This is the relevant Week-0 task; the separate
game-level backtest remains useful for in-season updates.

Zero-history rookies receive a historical position/draft-capital predictive
range combined explicitly with current depth role. Depth-1 players weight
cohort and role equally; reserves weight current role 75%. P10/P50/P90 analog
ranges are exported for inspection but do not enter live decision paths.
Experienced reserves whose historical workload exceeds their current nonstarter
role are capped at that same role median after preseason/in-season blending.
The analog intervals are display-only until their coverage is validated. The adjustment audit is written to
`results/current_role_adjustments.csv`.

### Rest-of-season layer

The production artifact separates the preserved Week-0 draft projection,
realized points, an unconditional rest-of-season point mean, scenario expected
games, and projected final points. A game crosses the cutoff only after its final
score and corresponding player stats and snaps are published, so a partial or
delayed week is handled game by game. Weekly features are rebuilt using completed
current-season evidence and the exact remaining schedule.

Current-form weight starts at zero and increases monotonically with games played
using declared position-specific empirical-Bayes prior sample sizes. Generic
availability scenarios are mean-preserving and do not discount the published
mean; a current designation affects only its report week. ROS value
over replacement is recomputed under league size and starting slots. This layer
has unit coverage for prior updating, remaining-game prorating, and availability,
but it does not yet have a multi-season ROS calibration report.

This provides current starter/depth information. Current injury designations are
joined only when the seasonal nflverse report asset exists. If it is absent,
the published feed flag is false and missing designations mean unknown, not
healthy. Active roster status alone is not an injury signal.

The live board does not show nonexistent 2026 actuals. The retrospective
validation artifacts remain available in the research outputs, but actual
outcomes never enter current projection ranks, replacement values, or draft
ranks.

The current board reports the live recommendation and raw model-points rank.
Retrospective validation builds additionally report hindsight format value and
actual season-points rank; those evaluation benchmarks never enter the live
recommendation.

Replacement demand is now derived from the selected team count and the default
1QB/2RB/2WR/1TE/2 FLEX/1K starting lineup. Base slots are allocated first and
FLEX slots go to the highest projected remaining RB/WR/TE players. Draft value
is the unweighted point difference from the last format-derived starter; the
former fixed QB12/RB30/WR36/TE12/K12 ranks and `0.55/1.0/1.0/0.8/0.05`
positional multipliers have been removed.

### Draft-policy validation

Public MyFantasyLeague AUG15 ADP was collected for 2018-2025 at 8, 10, 12, and
14 teams, with Standard/PPR ranks interpolated to half PPR. Opponents draft from
legal ADP with reproducible normal rank shocks that widen from roughly 3 picks
early to 13 at pick 100, capped at 20. Control and candidate share each realized
room draw.

The original retrospective evaluator selected the highest realized scorer from
each roster every week. That leaked outcomes and was best-ball evaluation, not
managed lineups. Its reported policy deltas are superseded. The corrected
evaluator freezes a preseason selection score, chooses each legal weekly lineup
from that score, and only then applies realized Week 1-17 points. Pairwise H2H
uses Weeks 1-14.

Forecast weights, unconstrained roster utility, ADP-reach guardrails, and
probability lookahead all failed against ADP after the correction. The only
promoted intervention retains exact market order while capping the roster at
two QBs, two TEs, and one kicker. RB and WR retain the league maxima and every
pick must preserve a legal finish. In 10-team rooms this reallocates about 1.6
picks from surplus QB/TE/K depth to RB/WR.

Rolling-origin 10-team candidate-minus-ADP results were:

| Season | H2H delta | Managed-point delta |
|--:|--:|--:|
| 2020 | +0.0040 | +7.06 |
| 2021 | -0.0014 | +2.74 |
| 2022 | +0.0087 | +10.75 |
| 2023 | +0.0153 | +20.85 |
| 2024 | +0.0075 | +16.28 |
| 2025 | +0.0020 | +6.28 |

The six-year mean H2H delta is `+0.0060`; its two-sided year-level 95% interval
is approximately `[-0.0001, +0.0122]`. Mean managed points improve by `+10.66`,
interval `[+3.54, +17.78]`. The H2H result is directionally consistent but
borderline under a two-sided test.

The frozen 2025 cross-size test used 20 noisy rooms per slot:

| Teams | ADP H2H | Capped ADP H2H | H2H delta | Point delta |
|--:|--:|--:|--:|--:|
| 8 | 0.5389 | 0.5396 | +0.0007 | -4.90 |
| 10 | 0.5315 | 0.5323 | +0.0008 | +2.21 |
| 12 | 0.5004 | 0.5081 | +0.0077 | +12.28 |
| 14 | 0.5249 | 0.5301 | +0.0052 | +7.05 |

The 12-team slot-clustered intervals exclude zero for H2H and points. The 8-
and 10-team single-season effects are small and uncertain. The production board
therefore describes capped ADP as the best tested policy, not a global optimum,
and keeps uncapped market ADP selectable as the control.

The experimental live layer evaluates the available pool, inferred opponent
rosters, the user's roster, snake slot, and picks until the next turn. ESPN ADP and the
midpoint of ESPN Standard/PPR rank form a separate opponent-availability prior;
they never alter our player forecast mean. Two hundred fifty-six common-seed
market paths sample roster-aware quantal-response opponent choices. While the
user is off the clock, paths include every selection before the user's pick and
aggregate the best available turn pair. At the 10/11 turn, zero intervening
picks still triggers pair optimization. After pick 11, lookahead resumes toward
pick 30. The roster utility uses 16 common outcome paths across Weeks 1-18, sets
bye weeks to zero, optimizes the legal QB/RB/WR/TE/FLEX/K lineup each week, and
fills open slots at a position-level waiver replacement. Eight bench slots make
depth valuable only when it enters a weekly lineup; an 18th player must displace
an existing roster asset. Recommendation eligibility enforces QB 4, RB 8, WR 8,
TE 3, and K 3 league maxima.

Weekly outcome volatility is estimated from 2018-2024 expanding-window
out-of-sample fantasy-point residuals among the upper half of each position's
forecast distribution. The central 68% relative-error scales are `0.466` QB,
`0.594` RB, `0.683` WR, `0.779` TE, and `0.504` K. Simulations use mean-preserving
lognormal weekly shocks. Rookie P10/P50/P90 is displayed as an uncalibrated
historical analog range but does not enter decision paths. The UI reports immediate roster gain
alongside simulated next-turn survival.

Injury availability is simulated as persistent multiweek episodes using
position-level onset and duration baselines. Historical onsets require zero snaps
plus a contemporaneous injury report. The observed position baselines are approximately 1.8% weekly for K, 2.0% for
QB, 2.6% for TE, 2.7% for WR, and 3.0% for RB, with mean episodes near two weeks.
Durations are geometrically sampled, capped at eight weeks, and continue through
byes. Current Out/Doubtful/Questionable reports apply 100%/95%/25% absence
probabilities to the exact report week only. Player recurrence, severity, and
BMI modifiers remain audit-only until an all-status panel is validated.

Availability simulations are mean-preserving: healthy-game output is rescaled
by simulated availability, leaving the published marginal season projection
unchanged. The injury layer therefore values backup coverage and replacement
timing without double-counting absence risk already implicit in historical
component forecasts.

Adaptive opponent behavior is a five-model Bayesian mixture: 40% prior mass on
Balanced and 15% each on RB-heavy, WR-heavy, Early-QB, and Zero-RB. Each observed
opponent position updates the mixture by its conditional likelihood over the
then-available risk set. A simulation samples one archetype from the posterior.
The market center is `70% ESPN ADP + 30% half-PPR rank midpoint`, with our rank
retained only as a small tie-breaker. The coefficients and room-style updates
are visible but remain uncalibrated pending point-in-time draft logs.

The earlier 2024 deterministic stress test covers all 12 snake slots. Mean realized
starter points for next-turn lookahead versus roster-aware greedy selection are
`1393.85` versus `1423.91` in balanced rooms, `1506.23` versus `1476.28` in an
RB run, and `1629.48` versus `1658.15` in a WR run. Lookahead consistently beats
the fixed format-value list, but it does not dominate the stronger comparator.
These values are policy diagnostics, not an independent performance estimate.
Those diagnostics are superseded for deployment by the point-in-time ADP
backtest above. Both model-driven policies remain selectable experiments.

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
- Rookie forecasts are empirical analog ranges rather than calibrated role-state
  trajectory simulations; coaching and offensive-line changes remain absent.
- NGS and advanced charting require common-support studies. Kalshi and
  Polymarket connectors are in shadow mode but still require mapped,
  liquidity-filtered common-support studies before model admission.
- Individual defensive statistics and team D/ST are not yet modeled.
- Kicker single-game ranking is weak. A team-implied-points layer has a modest
  grouped improvement but fails the individual-field multiple-testing gate.
- Injury onsets are independent across players and the body-part labels do not
  yet distinguish recurrence mechanisms. Team-level injury correlation,
  rehabilitation news, same-team opportunity constraints, schedule-level
  dependence, head-to-head win probability, and championship objectives remain
  absent. The injury approximation has not yet passed a rolling-origin
  calibration study and should not be interpreted as a medical forecast.
- The policy test uses aggregate MFL ADP rather than raw, timestamped manager
  sequences. A PII-minimized Sleeper collector and expanding-time Plackett-Luce
  evaluation harness now exist, but no seeded sequence corpus is checked into
  the repository and no fitted opponent-aware coefficients are deployed.
  Opponent deviations are still simulated, waiver/trade and playoff outcomes
  are absent, and several cross-size estimates remain imprecise. The capped-ADP
  edge does not establish universal optimality.
- The ROS empirical-Bayes weights are declared priors, not yet selected in a
  nested historical rest-of-season backtest. The next research gate is
  rolling-origin error and calibration by position and week of season.
- Historical injury exposure is built from active-roster player-game rows, so
  IR/inactive weeks can be censored before player recurrence is estimated.
  Individual injury-history counts are lower-confidence than position baselines.
- The current depth join covers all displayed players but only about 66% of
  active RBs and 71% of active WRs. Unmatched players are omitted rather than
  assigned a fabricated role.

## Deployment gates

1. Run point-in-time audits for injuries, rosters, and player props.
2. Accumulate and map shadow player-prop quotes, then finish their common-support
   and incremental-value studies alongside NGS and charting.
3. Freeze the model and calibration manifest.
4. Preserve the frozen 2025 evaluation manifest separately from production
   refits and report it without further tuning.
5. Simulate correlated player outcomes, then optimize the draft.
