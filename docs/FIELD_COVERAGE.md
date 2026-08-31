# Field Coverage

## Standard-scoring components

| Family | Forecast fields |
|:--|:--|
| Passing | `passing_yards`, `passing_tds`, `passing_interceptions`, `passing_2pt_conversions` |
| Rushing | `rushing_yards`, `rushing_tds`, `rushing_2pt_conversions` |
| Receiving | `receiving_yards`, `receiving_tds`, `receiving_2pt_conversions` |
| Ball security | `fumbles_lost_total` |
| Returns | `special_teams_tds` |
| Field goals | `fg_made_0_19`, `fg_made_20_29`, `fg_made_30_39`, `fg_made_40_49`, `fg_made_50_59`, `fg_made_60_` |
| Extra points | `pat_made` |

## Opportunity and diagnostic fields

`completions`, `attempts`, `carries`, `targets`, `receptions`, and `pat_missed`
are also forecast even though they receive zero points in the active non-PPR
configuration. They carry predictive information, support alternative scoring,
and make the component model easier to diagnose.

Each field has a recent-mean baseline and at least workload and context model
comparisons. The model keeps the recent-mean forecast for PAT makes and misses,
where learned models do not improve development RMSE. Rare fields such as two-
point conversions and 60-yard field goals are interpreted as expected rates;
single-game rank correlation is not a useful selection metric for those fields.

Individual defensive statistics and team D/ST scoring are not in the current
player model. They require a separate team-defense prediction unit once the
league confirms that D/ST is rostered.

Kicker component predictions remain the weakest group. Adding closing total,
spread, and derived team implied points improves combined kicker-point RMSE in
five of seven seasons (`+0.044` average, paired `p=0.046`), but no individual
kicker field survives Holm correction across the eight-field family. The market
layer therefore remains a candidate for the final holdout rather than a deployed
feature. The next kicker iteration should forecast team PAT and field-goal
opportunities first, then allocate attempts to the active kicker.
