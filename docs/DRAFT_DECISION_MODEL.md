# Draft Decision Model

## Objective and state

The deployed objective is expected points from 18 separately managed weekly
lineups. It is not championship probability or best-ball scoring. The state
contains the overall pick, snake order, available
players, observed picks, inferred manager rosters, league size, lineup slots,
and scoring weights.

Scoring rules transform component-stat forecasts after prediction. League size
and roster slots determine replacement levels and draft utility; they do not
change the raw football forecast.

The draft layer always consumes the preserved Week-0 projection. Daily in-season
updates are published as a separate rest-of-season view so observed results
cannot retroactively alter the draft recommendation. ROS value uses only
unplayed games, an unconditional point mean, and the same format-derived replacement
logic, providing a foundation for waiver and trade comparisons without changing
the draft-room opponent model.

## Player distributions

Veterans currently have point forecasts. Rookies with no prior NFL games receive
a historical analog distribution using same-position rookie seasons from
2012-2025. Analog weights decay with distance in log draft pick. The cohort is
combined with the current depth-role center. The UI exposes P10, P50, P90, and
effective sample size.

The range is empirical and uncalibrated, so it is display-only and does not enter
the deployed decision simulation. It does not yet impose a shared team
opportunity budget. A future version should estimate a smoothed rookie role
state, validate interval coverage, update it with preseason depth, and resample
entire historical component trajectories within that role.

## Historical policy benchmark

The primary benchmark is legal ADP drafting, not a fixed projection list. For
each historical draft the baseline takes the best available market player while
enforcing roster maxima and preserving enough remaining selections to fill every
starter slot. All other simulated managers use that same fixed policy and react
only to availability and their own roster, so policy comparisons do not change
the opponents between treatments.

The market snapshots are MyFantasyLeague AUG15 ADP for the exact season and
8-, 10-, 12-, or 14-team format. Standard and PPR ADPs are interpolated to half
PPR. The policy pool joins those snapshots to frozen Week-0 model forecasts and
realized weekly half-PPR points. Missing rookies and unmatched forecasts fall
back to market-implied points rather than hindsight.

The original evaluator chose the highest realized scorer from each roster every
week. That is a best-ball oracle, not managed-lineup evaluation, and its earlier
policy deltas are superseded. The corrected evaluator chooses a legal weekly
lineup using only the frozen preseason selection score, then reveals that week's
realized points. It cannot use the outcome to decide who started.

The corrected search first retested forecast weights, roster utility, ADP reach,
and next-turn lookahead. Those flexible rules still failed in noisy 2025 rooms.
The useful intervention was simpler: retain exact ADP ordering, preserve a legal
finish, and cap the drafted roster at two QBs, two TEs, and one kicker. RB and WR
continue to use the league maxima. The control uses the league maxima at every
position. The caps moved about 1.6 picks per 10-team roster from surplus QB/TE/K
depth to RB/WR without using the player forecast to reorder the market.

This cap was selected in rolling origin using prior seasons only. In 10-team
leagues, candidate-minus-control H2H deltas for 2020-2025 were `+0.0040`,
`-0.0014`, `+0.0087`, `+0.0153`, `+0.0075`, and `+0.0020`; managed-point deltas
were positive in all six years. The mean H2H delta was `+0.0060` with a two-sided
year-level 95% interval of approximately `[-0.0001, +0.0122]`; the mean point
delta was `+10.66`, interval `[+3.54, +17.78]`. The H2H evidence is promising
but borderline, so the board exposes the uncapped control and does not call the
cap universally optimal.

The frozen 2025 cross-size test used 20 noisy rooms per draft slot. Results were:

| Teams | ADP H2H | Capped ADP H2H | H2H delta | Point delta |
|--:|--:|--:|--:|--:|
| 8 | 0.5389 | 0.5396 | +0.0007 | -4.90 |
| 10 | 0.5315 | 0.5323 | +0.0008 | +2.21 |
| 12 | 0.5004 | 0.5081 | +0.0077 | +12.28 |
| 14 | 0.5249 | 0.5301 | +0.0052 | +7.05 |

The 12-team slot-clustered intervals excluded zero for both H2H and points. The
8- and 10-team single-season differences were small and uncertain. H2H uses each
preseason-selected weekly lineup against every other roster in Weeks 1-14;
season points use the same managed lineups in Weeks 1-17. Opponent ADP receives
a reproducible normal shock growing from roughly 3 picks early to 13 at pick
100, capped at 20. Control and candidate share every realized room draw.

## Live pick policy

The default takes the highest available ADP player from the selected room market
subject to `QB <= 2`, `TE <= 2`, `K <= 1`, the league's RB/WR limits, and the
ability to finish every starter slot. It introduces no model-based reaches.
ESPN, Sleeper half-PPR ADP, and their mean are selectable. The list recalculates
after every logged or edited pick. Plain legal market ADP remains selectable as
the control.

The weekly-roster and probability-lookahead options below remain experimental
diagnostics rather than the deployed optimum.

For each candidate `a`, the board estimates:

`Q(state, a) = E[managed weekly points after a and the next snake turn]`.

It uses 256 common-seed market paths. Each intervening manager samples an
available player from a softmax over ESPN ADP/custom-rank market center, unfilled starter need,
duplicate-position cost, RB/WR bench demand, and a sampled room archetype.
While the user waits, the simulator includes the entire prefix before the user's
pick and ranks players by how often they enter the optimal available turn pair.
At a consecutive snake turn it maximizes both picks even when zero opponents
select between them. The board reports survival to the user's pick while off
clock and return survival while on clock.

For every candidate, 16 common outcome paths run across Weeks 1-18. A missing
scheduled game is a bye and scores zero. Within each week, the simulator chooses
the best legal QB/RB/WR/TE/FLEX/K lineup from the roster and fills empty slots at
the position's format-derived weekly replacement level. Position-specific
lognormal volatility is fit from 2018-2024 expanding-window out-of-sample
residuals. Eight explicit bench slots cap the roster at 17 players; once full,
the candidate is valued only after optimally dropping one current player.

Every path also samples persistent injury-availability states from position-level
onset and duration baselines. Injury duration is geometric, capped at eight
weeks, and advances through bye weeks. Current Out, Doubtful, and Questionable
designations imply 100%, 95%, and 25% absence probabilities in the exact report
week only. Player recurrence, prior severity, and BMI estimates remain audit-only
until an all-status injury panel is validated.

Healthy-game output is scaled by each player's simulated availability rate.
This preserves the published marginal point mean and makes the new process a
model of bench insurance and replacement timing, rather than an unannounced
downward revision to the player forecast.

A final-round kicker timing prior prevents the short horizon from spending an
early pick on a position whose replacement pool is expected to remain available.
This is a declared fallback assumption until the opponent model is fitted to
timestamped draft sequences.

This is a transparent quantal-response prior. Current ESPN ADP and Standard/PPR
ranks or current Sleeper half-PPR ADP are ingested daily into the experimental
opponent-choice layer, not the player-value forecast. Its probabilities are not
historically calibrated because the repository does not contain raw manager-level
draft-room sequences.

The adaptive room model begins with a 40% Balanced prior and 15% each on
RB-heavy, WR-heavy, Early-QB, and Zero-RB. For every logged opponent pick, it
computes the probability that each archetype would select that position from
the then-available risk set and applies Bayes' rule. Each simulation samples one
archetype from the resulting posterior, preserving uncertainty instead of
switching abruptly after a recent-pick threshold. These priors and likelihood
bonuses are declared assumptions pending historical draft-log calibration.

## Research basis

The formulation follows several results from the operations-research and
decision-science literature:

- Becker and Sun formulate fantasy roster decisions as mixed-integer programs
  aimed at weekly matchup wins rather than raw point totals:
  <https://doi.org/10.1515/jqas-2013-0009>.
- Fry, Lundberg, and Ohlmann model the draft as a stochastic dynamic program and
  use a deterministic approximation because the exact game tree is too large:
  <https://iro.uiowa.edu/esploro/outputs/journalArticle/A-Player-Selection-Heuristic-for-a/9984380640402771>.
- Lee and Liu's study of 1,350 Sleeper leagues finds that strategy performance
  depends on competitors and that some less-common RB/WR-heavy roster
  constructions outperform common constructions:
  <https://www.cambridge.org/core/journals/judgment-and-decision-making/article/drafting-strategies-in-fantasy-football-a-study-of-competitive-sequential-human-decision-making/2AB841B3F446833348D784C0FC54DAD2>.
- Matthews, Ramchurn, and Chalkiadakis describe fantasy decision-making as a
  belief-state MDP with Bayesian reinforcement learning:
  <https://ojs.aaai.org/index.php/AAAI/article/view/8259>.
- Haugh and Singal show why opponent modeling and a stochastic outperform-the-
  field objective matter in fantasy contests:
  <https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3393127>.

These papers motivate an eventual belief-state stochastic program. They do not
validate this implementation. The production rule is deliberately the smallest
intervention supported by this repository's historical evidence.

## Empirical opponent-choice model

The research CLI can collect completed Sleeper redraft snake sequences from an
explicit user, league, or draft seed. Requests are kept below Sleeper's stated
rate guideline. Persisted snapshots exclude user IDs, usernames, league names,
and draft names. D/ST picks are retained as sequence events so snake timing is
correct, but D/ST is excluded from the offensive-player choice target.

For a manager state `s`, available choice set `C`, and candidate player `i`, the
model is:

`P(i | C, s) = exp(beta' x(i,s)) / sum[j in C] exp(beta' x(j,s))`.

`x(i,s)` contains market rank, player position, whether the manager still needs
that starter position, the manager's current count at the position, the last
six picks at that position, draft progress, and the fraction of managers before
the next snake turn who currently need that position. The ADP comparator uses
the same sets and only the market-rank term.

Evaluation is expanding in draft start time within an exact season, team count,
scoring, rounds, lineup, bench, and D/ST format. Each fold derives its ADP proxy
and coefficients from earlier drafts only. Later-draft players absent from the
training market are excluded and reported through known-pick coverage rather
than assigned hindsight ranks. The risk set is capped at the top 50 available
training-market players plus the observed choice during fitting.

The report includes multinomial log loss and Brier score, top-1/top-5 accuracy,
ICI, E50/E90/Emax, and logistic calibration intercept/slope. These are one-step
choice metrics. Survival-to-next-turn must subsequently be evaluated by rolling
the fitted probabilities through the draft simulator without conditioning on
future realized picks.

## Expert review consensus

Five independent reviews covered rookie forecasting, football roles, Bayesian
availability/injury updating, game theory, draft-market behavior, and validation.
Their convergent recommendations are:

1. Separate player outcome value from opponent selection behavior.
2. Represent rookie role and season output as distributions, preserving weekly
   and same-team dependence.
3. Treat missing injury reports as unknown and model availability, health, and
   role separately.
4. Infer opponent choices from timestamped ADP and raw draft sequences, then
   update manager tendencies from observed picks.
5. Describe the deployed policy as a Bayesian optimal response, not a Nash
   equilibrium or proven optimal draft.

## Data roadmap

- Continue timestamped ESPN and Sleeper snapshots by scoring, retrieval time,
  and response hash.
- Retain MyFantasyLeague league-size ADP snapshots for historical policy tests.
- Collect PII-minimized Sleeper sequences from explicit public user, league, or
  draft seeds; Sleeper exposes no global league-list endpoint.
- Fit and evaluate the implemented pick-level Plackett-Luce model with ADP,
  roster need, position runs, format, snake geometry, and intervening-manager
  demand. Current coefficients remain research-only until a sufficiently large
  seed corpus exists.
- Replace the simulated survival prior only after rolling-origin calibration.

## Validation gates

Use rolling-origin frozen Week-0 snapshots through 2025 and reserve 2026 as the
next untouched policy season. Evaluate player distributions with CRPS, interval coverage,
and joint energy/variogram scores. Evaluate survival with log loss, Brier score,
ICI, slope/intercept, and false-wait/false-reach rates. Evaluate the complete
policy with common-random-number regret versus roster-aware greedy, format VOR,
ADP/ECR, and a nondeployable outcome oracle.

Future policy promotion requires a positive untouched-season win-rate delta
against legal ADP, stability across league sizes and draft slots, and no material
managed-points regression. Capped ADP clears the directional gate but not a
strong universal-significance claim; more point-in-time seasons and raw draft
sequences are still required. Player-feature promotion separately retains the
expanding-window and placebo-feature requirements.

## Injuries and starters

The production board joins the latest daily active roster and depth chart, so it
does have current starter/depth information. It optionally joins current injury
report fields: body part, game status, and practice status. If that seasonal
asset is absent, the feed flag is false and the UI says current designations are
unavailable. Active roster status is eligibility, not evidence of health.
