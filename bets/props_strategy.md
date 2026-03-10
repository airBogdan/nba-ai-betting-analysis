# Player Props Betting Strategy

## Core Principles
- Only bet props where your projection meaningfully differs from the line
- Focus on players with consistent minutes and usage patterns
- Treat each stat type differently — points, rebounds, and assists have distinct variance profiles

## Stat-Specific Guidance
- **Points**: Best-performing prop category at approximately 64% (7W-4L). Prefer overs on high-usage, consistent-minutes players where the line is 20%+ below season average. Matchup-specific history is a stronger edge signal than season average alone — Jokic over 27.5 vs Minnesota (40.6 PPG history) and Giannis over 25.5 vs Phoenix (35.6 PPG history) both landed comfortably. Blowout risk is the primary killer: Wemby, Reaves, and Mobley all lost due to star-player minute capping in garbage time.
- **Rebounds**: Moderate performers at approximately 56% (5W-4L, excluding confirmed DNP losses). Centers and forwards against depleted frontcourts are prime targets. This category requires confirmed pre-game availability more than any other — two of the four losses were effectively DNP situations (Poeltl: 0 rebounds; Queta: 2 rebounds in minimal blowout minutes). Never bet a rebounds prop without verifying the player is confirmed active with normal minutes expectations.
- **Assists**: Weakest category at approximately 29% (2W-5L on overs). Assist overs are acutely sensitive to game script. Four of five losses involved the player's team losing by double digits. Do not bet assists overs in games where the player's team is projected as a significant underdog. Assists unders are effective when the line is set 40%+ above the player's season average.

## Key Factors to Weight
- Season average vs line — how far off is the line from the player's mean?
- Recent form (last 5-10 games) — trending above or below season average?
- Matchup defense — opponent's ranking in allowing that stat category
- Minutes consistency — avoid players with volatile minute distributions
- Home/away splits — some players perform significantly different by venue
- Pace factor — high-pace games inflate counting stats across the board
- **Matchup-specific history** — a player's historical numbers vs a specific opponent can outweigh season averages (validated by Jokic vs Minnesota, Giannis vs Phoenix)
- **Game script projection** — assists and points are heavily suppressed in blowout losses; rebounds are less affected but garbage-time minutes reduce opportunities

## What to Avoid
- Players returning from injury or on minutes restrictions
- Lines already sharp to the season average (no edge)
- High game-to-game variance players without a clear situational edge
- Correlated props (e.g. two players on the same team both over points)
- **Assists overs when the player's team is projected to lose by 10+ points** — blowout losses are the primary cause of assists prop failures in this dataset
- **Rebounds or points props on players whose availability is uncertain on game day** — the Poeltl (DNP) and Queta (near-bench in blowout) losses both stemmed from unconfirmed availability
- **Players in adjusted roles post-trade or post-injury return** without several games of new baseline — Giddey's post-trade loss (2 rebounds) was flagged as a process error in reflection
- **Points overs in games with high blowout potential on the player's team** — star players lose 4th-quarter minutes in comfortable wins for the opposing team

## Confidence Guidelines
- **High confidence (2 units)**: Projection 15%+ above/below line with strong matchup support
- **Medium confidence (1 unit)**: Projection 10%+ off line with supporting factors
- **Low confidence (0.5 units)**: Slight edge, worth small position
- **Assists props should be sized one tier below calculated confidence** given the 29% win rate — a calculated "high confidence" assists over should be staked as medium confidence

## Notes
- Prop bets first appeared in journals starting 2026-02-19. The dataset covers roughly 3 weeks with 29 props across points, rebounds, and assists categories.
- Points overs are the most reliable prop type. Rebounds are moderate. Assists overs are currently losing propositions and should be treated with significant skepticism.

## Change Log

### 2026-03-10
**Data basis:** 29 player prop bets with confirmed results across journals 2026-02-19 through 2026-03-09.

- **Points guidance updated**: Added ~64% win rate (7W-4L). Added matchup-specific history as a validated edge signal. Added blowout-risk warning backed by three named losses (Wemby, Reaves, Mobley) all caused by garbage-time minute caps.
- **Rebounds guidance updated**: Added ~56% win rate (5W-4L). Elevated pre-game availability confirmation as a critical requirement — two losses were entirely availability failures (Poeltl DNP; Queta near-DNP), not edge failures.
- **Assists guidance updated**: Added ~29% win rate (2W-5L on overs). Identified game script as dominant loss driver — 4 of 5 losses had player's team losing by double digits. Added the only winning assists pattern: unders when line is 40%+ above season average.
- **Key Factors to Weight**: Added matchup-specific history and game script projection — both validated repeatedly in journal reflections.
- **What to Avoid**: Added four new bullets covering assists overs in projected losses, availability uncertainty, post-trade role changes, and points overs in blowout-risk games. All backed by named losses.
- **Confidence Guidelines**: Added rule to downgrade assists props one tier due to 29% overall win rate.
