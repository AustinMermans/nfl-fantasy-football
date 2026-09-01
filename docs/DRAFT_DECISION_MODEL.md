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

## Player distributions

Veterans currently have point forecasts. Rookies with no prior NFL games receive
a historical analog distribution using same-position rookie seasons from
2012-2025. Analog weights decay with distance in log draft pick. The cohort is
combined with the current depth-role center. The UI exposes P10, P50, P90, and
effective sample size.

The range is empirical and uncalibrated. The deployed simulation samples one
P10/P50/P90 rookie role state per season path and combines it with weekly
outcome noise. It does not yet impose a shared team opportunity budget. The next
version should estimate a smoothed rookie role state, update it with preseason
depth, and resample entire historical component trajectories within that role.

## Live pick policy

For each candidate `a`, the board estimates:

`Q(state, a) = E[managed weekly points after a and the next snake turn]`.

It uses 16 common-seed Monte Carlo paths. Each intervening manager samples an
available player from a softmax over format-value rank, unfilled starter need,
duplicate-position cost, RB/WR bench demand, and a sampled room archetype.
The candidate with the largest expected two-turn weekly-lineup value ranks first.
The board also reports the fraction of baseline paths in which each player
survives to the next turn.

For every candidate, 16 common outcome paths run across Weeks 1-18. A missing
scheduled game is a bye and scores zero. Within each week, the simulator chooses
the best legal QB/RB/WR/TE/FLEX/K lineup from the roster and fills empty slots at
the position's format-derived weekly replacement level. Position-specific
lognormal volatility is fit from 2018-2024 expanding-window out-of-sample
residuals. Four explicit bench slots cap the roster at 12 players; once full,
the candidate is valued only after optimally dropping one current player.

Every path also samples persistent injury-availability states. The position
baseline is the historical weekly rate of a zero-snap game accompanied by an
injury report. Player recurrence is a beta-binomial-style posterior with 34
position-prior games. Mean episode length is shrunk by two position-prior
episodes and represents prior severity. Within-position BMI terciles contribute
an empirical-Bayes risk ratio with 300 exposure games of shrinkage. Injury
duration is geometric and capped at eight weeks; it advances through bye weeks.
Current Out, Doubtful, and Questionable designations imply 100%, 75%, and 25%
Week 1 absence probabilities.

Healthy-game output is scaled by each player's simulated availability rate.
This preserves the published marginal point mean and makes the new process a
model of bench insurance and replacement timing, rather than an unannounced
downward revision to the player forecast.

A final-round kicker timing prior prevents the short horizon from spending an
early pick on a position whose replacement pool is expected to remain available.
This is a declared fallback assumption until the opponent model is fitted to
timestamped draft sequences.

This is a transparent quantal-response prior. Its probabilities are not yet
calibrated because the repository does not contain point-in-time historical
draft-room logs. Market ADP belongs in this opponent-choice layer, not in the
player-value forecast.

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

- Snapshot the Fantasy Football Calculator ADP API daily by scoring, league
  size, retrieval time, and response hash.
- Cross-check actual-draft behavior with the MyFantasyLeague ADP report.
- Store exact sequences only from sources and leagues whose access allows it.
- Fit a pick-level Plackett-Luce or hazard model with ADP distribution, roster
  need, position runs, format, round, and manager effects.
- Replace the simulated survival prior only after rolling-origin calibration.

## Validation gates

Use frozen Week-0 snapshots for 2018-2024 and leave 2025 unopened until all
choices are frozen. Evaluate player distributions with CRPS, interval coverage,
and joint energy/variogram scores. Evaluate survival with log loss, Brier score,
ICI, slope/intercept, and false-wait/false-reach rates. Evaluate the complete
policy with common-random-number regret versus roster-aware greedy, format VOR,
ADP/ECR, and a nondeployable outcome oracle.

Promotion requires improvement in at least five of seven development seasons,
season-clustered uncertainty intervals, and gains above a family-wise maximum
placebo-feature benchmark. Until those gates pass, ranges and survival values
remain decision aids rather than calibrated probabilities.

## Injuries and starters

The production board joins the latest daily active roster and depth chart, so it
does have current starter/depth information. It optionally joins current injury
report fields: body part, game status, and practice status. If that seasonal
asset is absent, the feed flag is false and the UI says current designations are
unavailable. Active roster status is eligibility, not evidence of health.
