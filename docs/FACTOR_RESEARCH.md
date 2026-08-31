# Factor Research

## Admission rule

Context candidates are added to the workload model one at a time. A factor must
improve average RMSE over seven expanding-season folds, beat the 95th percentile
gain from 100 independent Gaussian controls on the 2024 selection fold, and
retain a one-sided season-blocked improvement after Holm correction within the
target family. These are development decisions; 2025 remains locked.

## Individual yardage screen

No individual passing-yard factor passed all gates. Rushing yards admitted
lagged opponent rushing allowance and week. Receiving yards admitted closing
game total, lagged opponent receiving allowance, and a current questionable
designation. Weather, venue, age, career stage, generic injury indicators,
spread, rest, and other tested factors were rejected where they failed either
the random-control or corrected significance hurdle. Full results are in
`results/factor_screen.csv`.

## Nonlinear grouped layers

The full context model remains superior to the individually screened subset for
passing, and is modestly better for rushing and receiving. This is treated as
evidence of stable interactions rather than as individual-factor admission.
Grouped context must still beat workload across walk-forward folds.

Closing spread and total were then added together to the nonlinear context
model and tested on the pregame fantasy-relevant population. Holm correction
was applied across all 11 component targets.

| Target | Mean RMSE gain | Unadjusted p | Holm p | Decision |
|:--|--:|--:|--:|:--|
| Receiving yards | 0.04085 | 0.00041 | 0.00451 | Retain |
| Receiving TDs | 0.00092 | 0.00125 | 0.01255 | Retain |
| Rushing TDs | 0.00160 | 0.00141 | 0.01268 | Retain |
| Passing TDs | 0.01231 | 0.00726 | 0.05808 | Reject |
| Receptions | 0.00262 | 0.00973 | 0.06813 | Reject |
| Passing yards | 0.72394 | 0.04720 | 0.28319 | Reject |
| Carries | 0.00622 | 0.06239 | 0.31194 | Reject |
| Attempts | 0.03397 | 0.08733 | 0.34934 | Reject |
| Targets | 0.00084 | 0.19118 | 0.57354 | Reject |
| Interceptions | 0.00014 | 0.47586 | 0.95172 | Reject |
| Rushing yards | -0.00023 | 0.50679 | 0.95172 | Reject |

The official market layer contains consensus closing spread and total. Kalshi
and Polymarket player props are implemented as a shadow `player_market` layer
but are not admitted official features. Prediction-market props require their own
common-support and liquidity screen before entering this table.
