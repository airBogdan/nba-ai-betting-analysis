# NBA Betting Strategy

## Core Principles
- Only bet when there's a clear statistical or situational edge
- Prioritize moneyline bets with identifiable advantages
- Never chase losses or force bets on weak slates

## Confidence Guidelines
- **High confidence (2 units)**: Multiple strong edges align
- **Medium confidence (1 unit)**: Single strong edge with manageable risk
- **Low confidence (0.5 units)**: Slight edge, worth small position

## Key Factors to Weight
- Home/away performance differential
- Rest advantage (2+ days vs back-to-back)
- Recent form (last 10 games)
- Head-to-head patterns
- Key player availability
- **Net rating differential (prioritize 10+ point edges)** - ratings_edge bets are 12-5 (70.6%)
- **Injury-edge totals require dual criteria**: either (a) depleted team faces an elite defense (108.5 DRTG or better), or (b) both rosters are simultaneously depleted. Single-sided depletion fails repeatedly — the healthy opponent scores freely against a depleted defense.
- **Cap injury impact on totals at 10-15 points** regardless of raw PPG arithmetic. Any model-projected edge above 20 points is a model artifact; markets have already moved.

## What to Avoid
- Teams on long road trips
- Back-to-back situations against rested opponents
- Overvaluing streaks without underlying stats support
- **Laying large spreads (-6.5+) with injury edges against elite organizations** - depth can compensate
- **Injury-edge unders when the healthy opponent has a porous defense (115+ DRTG)** — role players shoot freely against depleted defenses, negating scoring suppression
- **Totals unders in likely blowouts** — garbage time scoring consistently pushes actuals over the line even when both teams play within projection for 3 quarters
- **Trade-deadline totals within 2-3 games of roster assembly** — new players come in motivated, defensive structure breaks down
- **High-confidence (2u) sizing on injury-edge totals** unless both elite-defense AND dual-depletion criteria are met simultaneously; injury-edge unders overall are 20-21 (48.8%) — break-even before juice

## Notes
- Strategy will be updated as betting history accumulates

## Change Log
### 2026-03-10
**Data basis:** All 30 journal files (2026-02-02 through 2026-03-10), game-level bets only.

- **ratings_edge win rate updated**: 7-1 → 12-5 (70.6%) with larger sample. Still highest-performing edge type. Losses cluster around B2B fatigue, large spreads not covering, and organizational depth absorbing injuries.
- **Injury-edge totals dual-criteria added**: injury_edge unders are 20-21 (48.8%) overall — break-even before juice. The winning subset consistently shares two traits: (a) depleted team faces elite defense (108.5 DRTG or better), or (b) both rosters simultaneously depleted. Single-sided depletion fails because the healthy opponent scores freely against a weakened defense.
- **Cap on projected injury impact added**: Projected edges of 30-50 points on totals are model artifacts observed in 8 cases; 6 of those 8 went over or landed within 2 points of the line. Real injury impact on totals is 10-15 points maximum.
- **Four new "What to Avoid" bullets**: (1) Injury-edge unders vs porous defenses (115+ DRTG), (2) Unders in likely blowouts due to garbage-time inflation, (3) Trade-deadline totals within 2-3 games of roster assembly, (4) High-confidence sizing (2u) on injury-edge totals unless both elite-defense AND dual-depletion criteria are met.

### 2026-02-09
- **Key Factors to Weight**: Added explicit guidance to prioritize large net rating differentials as a key factor. _ratings_edge bets are 7-1 (87.5%) - our highest-performing edge type with sufficient sample size. Reflections consistently note that large net rating differentials (10+ points) are reliable predictors. Examples: NYK vs WAS (+16 net rating, won by 31 twice), HOU vs IND (+14 net rating, won outright as dog)._
- **What to Avoid**: Added caution against large spreads based on injury edges vs elite teams. _injury_edge bets are 6-4 (60.0%) with 10 bets - notably weaker than ratings_edge. Key loss: BOS (-6.5) at HOU where Celtics won by 21 despite missing stars. Reflection noted 'elite organizations often have next man up cultures that mitigate personnel losses.' Injury edges work better on moneylines than large spreads._
