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
Kalshi and Polymarket player props are a separate short-history research layer.
Each quote must carry market, player, stat, line, source timestamp, kickoff, and
liquidity fields; only the final quote before kickoff is eligible. Market models
will be evaluated on the identical common-support player-games against the core
model, so missing or newly launched props cannot create a false improvement.
