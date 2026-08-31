# Methodology

## Prediction unit

The canonical unit is one scheduled regular-season game for one QB, RB, FB, WR,
TE, or K listed as `ACT` on that week's nflverse roster. Players remain in the
sample when they record zero offensive snaps or zero statistics. This makes
availability, participation, and role loss part of the forecast rather than a
condition known in advance.

Twenty-five outputs are modeled separately. They cover passing completions,
attempts, yards, touchdowns, interceptions, and conversions; rushing attempts,
yards, touchdowns, and conversions; receiving targets, receptions, yards,
touchdowns, and conversions; lost fumbles; special-teams touchdowns; PAT makes
and misses; and made field goals in six distance buckets. Fantasy points are not
a training target. They are calculated after forecasting so scoring changes do
not require retraining component models.

## Standard scoring assumption

The active scoring configuration is `traditional_non_ppr`: 0.04 per passing
yard, four per passing touchdown, minus two per interception, 0.1 per rushing or
receiving yard, six per rushing/receiving/special-teams touchdown, two per
two-point conversion, and minus two per lost fumble. Field goals score three
through 39 yards, four from 40-49, and five from 50 or more; PAT makes score one.
There are no reception points, yardage bonuses, or missed-kick penalties.

The formula matches nflverse's 2024 generic standard score on 99.58% of skill-
player rows. The remaining 0.42% are lost-fumble rows where this configuration
deliberately applies the traditional minus-two penalty and nflverse's generic
field does not.

## Point-in-time features

Every rolling value is shifted by one game before being attached to the current
row. Player features include lag-one, four-game exponentially weighted, and
twelve-game exponentially weighted statistics; snap share; offensive snaps;
prior participation; target share; and receiving air yards. Context candidates
include lagged team-position production, lagged opponent allowance by position,
home/away, rest, week, age, career stage, roof, surface, weather, final injury
designation, practice participation, closing spread, and closing total.

Current-game snaps, current-game statistics, and post-kickoff market quotes are
never features. Tests directly verify same-row target changes cannot alter
same-row features.

## Validation

Development uses expanding-season walk-forward folds. Each fold trains on every
season before the test season, beginning with 2012-2017 training and 2018 test,
and continues through the 2024 model-selection fold. There is no rolling-window
truncation in the baseline; recency is represented by exponentially weighted
features and offseason changes can later be tested explicitly.

The 2025 season is the locked final test set. It is downloaded for data-audit
purposes but excluded from the processed development table and every current
backtest. Opening it requires a separate explicit operation that writes an
irreversible manifest under `results/.holdout_opened`.

Primary component metrics are RMSE and MAE, with Spearman rank correlation.
Poisson deviance is also reported when the target is nonnegative. Reports split
the complete active-roster population from a pregame fantasy-relevant slice
defined by four-game lagged offensive snap share of at least 25%.

## Models and admission gates

The baseline is a twelve-game exponentially weighted mean. Candidate estimators
are regularized generalized linear models and histogram gradient boosting.
Feature families enter in stages: player form, workload, screened context, full
context, and game market context.

Individual context candidates are evaluated against workload using seven
season-blocked RMSE differences. Admission requires positive average gain,
improvement on the 2024 selection fold beyond the 95th percentile gain from 100
independent Gaussian controls, and a one-sided paired test surviving Holm
family-wise correction. Nonlinear grouped layers are also compared directly
across folds because a linear marginal screen cannot rule out stable
interactions.

## Participation calibration

Participation is modeled as a separate probability. Identity, intercept-only,
temperature, Platt, beta, and isotonic calibration are compared in a nested
walk-forward study. For each calibration test season, the mapping is fit only on
base-model predictions that were generated out of sample in earlier seasons.
Selection uses log loss; Brier score, AUC, calibration intercept/slope, ICI,
E50, E90, Emax, and the Murphy Brier decomposition are diagnostics.

## Prediction markets

Closing NFL spread and total from nflverse are the first market benchmark.
Kalshi and Polymarket are now deployed as read-only shadow feeds. Discovery uses
Kalshi's series/live/historical endpoints and Polymarket's NFL tag plus CLOB
price histories. Recognized contracts are normalized to market, game, player,
stat, threshold, source timestamp, kickoff, bid/ask, volume, and open interest.
Only the final valid quote strictly before kickoff is eligible.

Alternate thresholds remain separate through the point-in-time filter. Within
each source, the over-probability ladder is made non-increasing and interpolated
at 50% to estimate a market-implied median. Source medians are then combined by
median, with source count, quote count, volume, quote age, and maximum spread
retained as quality features. This avoids treating one thin contract or one
exchange as consensus.

The `player_market` feature family is opt-in and currently shadow-only. Before
predictive comparison, a coverage gate requires at least 100 mapped player-games
in each of three development seasons by default. A promoted layer must then
improve expanding-window predictions on the identical common-support rows,
exceed the random-feature benchmark, and survive Holm correction. Missing-market
indicators cannot create a false improvement by changing the evaluation sample.

The August 31, 2026 catalog audit found Kalshi histories beginning October 6,
2025 for passing, rushing, and receiving-yard contracts. That is after the
2012-2024 development window and overlaps the locked 2025 holdout. Polymarket
contains a longer anytime-touchdown catalog but only one recognized 2024
passing-yard contract. These sources therefore cannot yet be used to tune the
official model without violating the holdout design.

## Draft recommendation

The draft layer does not train new player outcomes or alter the component
forecast. It converts projected season points into a format-specific sequential
decision. League-wide base starter counts are the number of teams times each
position slot. FLEX slots are allocated to the highest projected remaining
RB/WR/TE players, and each position's last selected starter defines replacement
value. This removes the former fixed replacement ranks and positional weights.

During a draft, the browser persists the Mine/Taken log and league settings,
computes the snake turn, and projects opponent selections until the user's next
turn. For each available candidate, it protects that player, removes the
projected intervening selections, takes the best single surviving option at the
next turn, and optimizes a QB/RB/WR/TE/FLEX/K starting lineup from those picks
and the user's roster. Empty slots are filled at format-derived replacement so
an incomplete roster does not make raw QB points dominate. Candidate ordering
is lexicographic: two-pick projected starter value, expected availability,
same-position next-turn gap, then format-derived replacement value. No realized
outcome enters this recommendation.

The opponent policy can follow recent room behavior, remain balanced, or impose
an RB/WR run through round two. It is deterministic and has a one-turn horizon.
It does not yet estimate pick-by-pick survival probabilities from historical
ADP, simulate injuries or correlated weekly outcomes, value bench options, or
solve the complete draft as a stochastic game. Those require point-in-time ADP
and predictive distributions and must be evaluated in a preseason walk-forward
draft backtest before the layer can be called optimized.

The deterministic stress test replays every snake slot for three opponent
policies and compares next-turn lookahead, roster-aware greedy value, the fixed
format-value list, and raw projected points. It scores the best realized legal
starting lineup. This diagnoses policy mechanics but is not a preseason
backtest: the current season totals aggregate weekly out-of-sample forecasts
whose role, injury, and matchup inputs arrived after the preseason draft date.
A valid test must freeze features and availability before Week 1 in every year.
