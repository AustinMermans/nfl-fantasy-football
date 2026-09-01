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

Candidate weights and lookahead were selected on 2019-2023, then evaluated once
on 2024. Every development winner assigned the player forecast zero weight. On
the holdout, candidate minus ADP H2H win-rate deltas were `-0.0651`, `-0.1270`,
`-0.1466`, and `-0.1652` for 8, 10, 12, and 14 teams. Managed-point deltas were
`-48.02`, `-131.31`, `-188.81`, and `-213.19`. Therefore no candidate was
promoted and the live board defaults to the legal market-order policy.

H2H win rate uses each managed lineup against every other roster in Weeks 1-14;
season points use managed legal lineups in Weeks 1-17. Averaging all draft slots
makes the all-ADP league baseline exactly `0.500` by construction. This is a
policy test, not evidence that a 0.500 team wins half of real leagues.

## Live pick policy

The validated default takes the highest available ADP player from the selected
room market while preserving a legal roster finish. ESPN is the default because
the current league drafts on ESPN. Sleeper half-PPR ADP and an ESPN/Sleeper mean
are selectable for rooms hosted elsewhere. The list is recalculated after every
logged or edited pick, so unavailable players disappear and late-round position
requirements can change the next legal selection.

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
- Store exact sequences only from sources and leagues whose access allows it.
- Fit a pick-level Plackett-Luce or hazard model with ADP distribution, roster
  need, position runs, format, round, and manager effects.
- Replace the simulated survival prior only after rolling-origin calibration.

## Validation gates

Use frozen Week-0 snapshots for 2018-2024 and leave 2025 unopened until all
player-model choices are frozen. Evaluate player distributions with CRPS, interval coverage,
and joint energy/variogram scores. Evaluate survival with log loss, Brier score,
ICI, slope/intercept, and false-wait/false-reach rates. Evaluate the complete
policy with common-random-number regret versus roster-aware greedy, format VOR,
ADP/ECR, and a nondeployable outcome oracle.

Future policy promotion requires a positive untouched-season win-rate delta
against legal ADP, stability across league sizes and draft slots, and no material
managed-points regression. The current candidate failed that first gate. Player
feature promotion separately retains the expanding-window and placebo-feature
requirements.

## Injuries and starters

The production board joins the latest daily active roster and depth chart, so it
does have current starter/depth information. It optionally joins current injury
report fields: body part, game status, and practice status. If that seasonal
asset is absent, the feed flag is false and the UI says current designations are
unavailable. Active roster status is eligibility, not evidence of health.
