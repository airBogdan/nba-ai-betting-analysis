# Paper Trading Strategy

## Purpose
Find value in games the primary analyst skips. Track contrarian picks to discover
which skip patterns leave money on the table.

## Overall Performance (as of 2026-03-10)
- **22 settled trades: 14W-8L (63.6% win rate), +2.5 net units**
- Totals: 11W-6L (64.7%)
- Spreads: 3W-2L (60.0%)
- The system is profitable. The primary analyst's skip reasoning is frequently wrong in systematic, predictable ways.

---

## Approach
- Challenge skip reasoning — look for edges dismissed too quickly
- Focus on games skipped for "no clear edge" — these often have subtle value
- Be honest about confidence — low confidence is fine for paper trading
- Track which skip categories yield the best results
- Prioritize finding real edge over matching the primary analyst's bet count limits

---

## What to Look For
- Injury uncertainty games where the line overreacted
- "Coin flip" games where one side actually has a lean
- Games skipped due to variance where statistical edges exist
- Sizing vetos where the edge was real but below threshold

---

## Skip Patterns That Produce Value

### 1. "Terrible defense / tanking teams unpredictable" — Win Rate: 3W-1L (75%)
The primary analyst repeatedly skips injury-driven unders because "both teams have 116+ DRTG" or "tanking teams are unpredictable." This is the most reliably wrong skip reason in the dataset.

**Confirmed wins using this pattern:**
- IND @ WAS under 230.5 — WON. Analyst said "terrible defense could lead to easy buckets." Final: 217 total, 13 under the line.
- TOR @ MIL under 219.5 — WON. Final: 216 total. Bad defenses did not bail out depleted offenses.
- BOS @ LAL under 227.5 — WON. Final: 200 total. Celtics missing two star scorers, Lakers could not compensate.

**Why the skip reason is wrong:** When a team is missing 20-30 PPG from injuries, their offense is compromised regardless of the opposing DRTG. Bad defense does not automatically produce buckets — you still need scorers. The "easy buckets" logic only holds when the injured team's replacements are also capable scorers, not when the injury carnage is systemic.

**Actionable rule:** When injury-adjusted total is 15+ points below the posted line AND the skip reason is purely "bad defense creates variance," take the under. Bad defense does not overcome massive offensive voids.

### 2. "H2H historically high-scoring" when rosters are decimated — Win Rate: 4W-2L (67%)
The primary analyst frequently cites H2H history as a disqualifier even when the current rosters share nothing with the historical matchup personnel. Examples:
- MIL @ CHI under 228.5 — WON. Analyst cited "68% over 220 H2H rate." Final: 217 without Giannis.
- POR @ ATL under 237.5 — WON. Analyst said "injury reports may not be updated." Final: 236 total.
- HOU @ MIA under 223.5 — WON. Analyst worried about "Heat high-scoring at home recently." Final: 220.
- CLE @ BKN under 222.5 — WON (Mitchell OUT). Final: 208.
- Losses: CHA @ WAS (final 241) and DAL @ IND (final 264) — both had two-sided bad defenses where injured teams still had capable replacement scorers.

**Why the skip reason is wrong:** H2H historical over rates are computed with healthy rosters. When 40-60+ combined PPG is missing, historical patterns no longer apply. The base rate needs to be reset to injury-adjusted projections, not historical averages.

**Actionable rule:** Discount H2H over rate history when combined PPG missing exceeds 30 points. The current injury context overrides historical matchup tendencies. Exception: if both teams have 115+ DRTG AND the missing players have capable backups, H2H history retains some weight.

### 3. "Smaller edge than other plays / portfolio limits" — Win Rate: 6W-1L (86%)
The primary analyst frequently acknowledges a real edge but skips because "better opportunities exist" or "already at bet limit." This is the single most profitable skip category in paper trading.

**Confirmed wins:**
- MIL @ CHI under 228.5: "Under has 22-point edge but less certainty than other injury-driven unders" — WON
- POR @ ATL under 237.5: "Medium confidence doesn't warrant selection over high-confidence plays" — WON
- DET @ ORL spread -5.5: "Better plays available" — WON
- CLE @ BKN under 222.5: "Less clean than selected plays" — WON
- MIN @ DEN under 239.5: "Less clean than selected plays" — WON
- MEM @ IND spread +1.0: "50-point edge claim is unrealistic" veto — WON
- ORL @ MIN under 224.5: "Diversifying away from all-unders slate" — WON

**Only loss in this category:** BKN @ DET spread -14.5 (Brooklyn won outright as underdogs)

**Why this matters:** When the primary analyst acknowledges an edge in the skip reason itself — even while choosing not to act on it — that acknowledged edge is typically real and exploitable. The primary analyst's bet limits create systematic opportunity for paper trading.

**Actionable rule:** If the skip reason says "acknowledged edge but not selected due to portfolio limits," treat this as a high-priority paper trade. The edge was identified by the same analytical process that picks winners — the skip was portfolio management, not analytical doubt.

### 4. "Injury uncertainty / GTD status" when the injury is confirmed OUT — Win Rate: 4W-2L (67%)
The primary analyst treats "questionable" and "OUT" the same way, applying equal caution to both. When the primary's skip reason cites injury uncertainty but the player is actually confirmed OUT, the skip reason is analytically wrong.

**Key wins:**
- CLE @ BKN under 222.5: "Mitchell's status creates uncertainty" — Mitchell was confirmed OUT. WON by 14 total points.
- POR @ ATL under 237.5: "Injury reports may not be fully updated" — Trae Young and Sharpe confirmed OUT. WON.

**Losses include:** BKN @ DET spread -14.5 where Cunningham was genuinely GTD and uncertainty was real.

**Actionable rule:** Distinguish confirmed OUTs from genuine GTD status. If the skip reason cites "injury uncertainty" but the player is confirmed OUT in game logs, the uncertainty is resolved and the edge is real. Reserve caution for true GTD situations.

### 5. Spread value against teams in multi-game collapse — Win Rate: 2W-1L (67%)
When a team is on a long losing streak with poor margins, the primary analyst sometimes passes on the opposing spread due to "home court," "bounce-back potential," or "H2H history." Collapsing teams rarely bounce back in single games.

**Confirmed wins:**
- DAL @ TOR spread (TOR -9.5): Mavs on 6-game skid, 7-22 road record. WON by 30 points.
- MEM @ IND spread (MEM +1.0): Indiana decimated, Memphis clearly better team. WON by 19 points.

**Loss:** BKN @ DET spread -14.5: Brooklyn was collapsing (0-10 L10) but Cunningham played and they won outright — large spread with key-player uncertainty materialized badly.

**Actionable rule:** When a team is on a 6+ game losing streak with consistent double-digit losing margins, medium spreads (-9.5 or less, or getting points) against them remain exploitable. Avoid large spreads (-14.5+) even against collapsing teams.

---

## What to Avoid

### 1. Large spreads (-14.5+) with injury-edge reasoning — unreliable
The history shows large spreads are high-variance regardless of the edge quality. BKN @ DET -14.5 lost despite Detroit being the clearly dominant team on paper. Large number spreads require the injured/weaker team to not just lose but lose by a lot — too many ways to fail.

**Rule:** Cap paper trade spreads at -12 max. Prefer +/- 10 or less for contrarian spread plays.

### 2. Injury-driven unders against teams with two-sided bad defense AND capable replacements
When both teams have 115+ DRTG and the injured players have known depth behind them, the under math overstates the impact. The DAL @ IND (264 total), CHA @ WAS (241 total), and DEN @ GSW (245 total) losses all featured situations where depleted offenses still found enough scoring via pace and garbage time.

**Warning signals for under failures:**
- Both teams DRTG above 115
- Line was set for a depleted roster (market already partially adjusted)
- Replacement players have known scoring capability
- H2H games historically go over regardless of personnel

### 3. Vetoed plays based on Jimmy Butler roster confusion — recurrent analytical error
Multiple vetoes cite "Jimmy Butler plays for the Warriors" as a disqualifying logic error. This is a recurring data error in the primary analysis. Evaluate the underlying edge independently for vetoed plays that cite Butler as a Warriors player. However, do not automatically take every vetoed play — the underlying edge must be confirmed separately, and some vetoes (Kelly Criterion at extreme juice, clear hallucination in injury data) are analytically correct.

### 4. Overs based purely on H2H historical over rates — requires mathematical edge
The 2026-02-23 over play on Utah @ Houston (over 226.5) was taken because "H2H is 96% over 220." But the injury-adjusted total matched the line at 226.5, meaning zero mathematical edge. Taking overs requires a positive mathematical edge, not just historical pattern-matching.

---

## Bet Sizing

### Confidence-Adjusted Sizing
Historical results strongly suggest **inverse confidence sizing** — low-confidence plays have outperformed high-confidence plays in this dataset.

| Confidence | Record | Win Rate | Notes |
|---|---|---|---|
| High | 3W-4L | 42.9% | Worst tier — aggressive picks on "obvious" injury edges |
| Medium | 6W-4L | 60.0% | Solid, in line with overall rate |
| Low | 5W-0L | 100.0% | Best tier — small, disciplined plays win every time |

**Interpretation:** High-confidence paper trades tend to be the games where the paper trader is most aggressive AND where the primary analyst had the strongest stated reason to skip (usually high-variance situations). The "obvious" contrarian plays — massive claimed injury edges — blow up most often because markets already partially price them in.

**Revised sizing rules:**
- Low confidence: 0.5u — these are hitting 100%, keep sizing small to maximize frequency
- Medium confidence: 1.0u — solid performers, standard size
- High confidence: 1.0u max (never 2.0u) — the 2.0u high-confidence format is net-negative

**Why 2.0u high-confidence sizing is net-negative:** The four 2.0u losses (DEN @ GSW, CHA @ WAS, WAS @ NOP, ORL @ PHX) cost -8.0u in losses. The 2.0u wins returned only +6.0u. Net on 2.0u sizing: -2.0u. At 1.0u sizing those same bets would be -4.0u losses, +3.0u wins = -1.0u, a worse raw number but better EV relative to the confidence signal.

---

## Results by Bet Type

### Totals: 11W-6L (64.7%)
Unders dominate the sample — essentially all total plays are unders. The edge is real but not as consistent as the raw injury math suggests. A 13-point injury-adjusted edge does not guarantee a win — the actual total can still come in over due to pace, garbage time, and replacement-player performance.

**Profitable under setups:**
- Injury-adjusted edge 10+ points AND H2H avg total well below the line
- Injury-adjusted edge 10+ points AND combined recent scoring significantly below season averages
- Both teams on B2B with confirmed injury impact

**Marginal/losing under setups:**
- Injury-adjusted edge 25+ points where the line seems obviously wrong (market already adjusted)
- Both teams 115+ DRTG with the under — bad defenses do not produce points for bad offenses, but they also do not prevent opponents from running pace

### Spreads: 3W-2L (60%)
Smaller sample but consistently profitable. Best spread plays:
- Favorite team against genuinely collapsing opponent (long losing streak + poor road record) at reasonable spread size
- Net rating edge + H2H dominance + star player missing from opponent
- Getting points with the demonstrably better team when the opponent has structural injury issues

---

## Main Analyst Blind Spots

### Blind Spot 1: H2H history overweighted when rosters are fundamentally different
The analyst consistently cites H2H over rates (76%, 95%, 100% over 220) as a disqualifier for injury-driven unders. But historical H2H was played with different personnel. When a team is missing 25+ PPG, the H2H base rate is irrelevant. This is the most common incorrect skip reason in the dataset.

### Blind Spot 2: Bad defense treated as a multiplier for offense
The analyst writes "bad defense could lead to easy buckets" as if a 116+ DRTG opponent automatically compensates for the loss of 25 PPG from injuries. Bad defense allows points when the offense is functional — it does not create points when the offense is gutted. The net effect of bad defense on a depleted team's total scoring is near-zero in most observed cases.

### Blind Spot 3: Bet limits treated as analytical limits
When the primary analyst says "already at bet limit," they are applying portfolio management to what should be an analytical decision. If a 22-point edge exists on a game, that edge does not disappear because 3 other bets were already placed. Paper trading should systematically capture these dismissed edges — they carry a 86% win rate (6W-1L).

### Blind Spot 4: "Elite organizations" exemption overrides injury math
The strategy warns against injury-based edges vs "elite organizations" (Celtics, Pistons, etc.) because of their depth culture. In practice, even elite organizations drop significantly in scoring when stars are out. BOS @ LAL won with both Tatum and Brown out (final: 200). TOR @ MIL won with Giannis and Barnes out (final: 216). Elite depth does not fully compensate for 40+ PPG in absences.

### Blind Spot 5: "Bounce-back" potential for losing streak teams
The analyst frequently cites "bounce-back potential" for teams on long losing streaks. In practice, teams on 6-10+ game losing streaks with structural roster problems (injuries, tanking) do not bounce back in single games. Dallas (6-game skid) lost to Toronto by 30. The data supports treating losing streaks as persistent signals, not mean-reversion opportunities.

---

## Actionable Decision Framework

When evaluating a skipped game, work through these checks in order:

1. **Identify the stated skip reason** — is it analytical (no edge) or portfolio (limits, diversification)?
2. **If portfolio-based:** Take the play at the stated confidence level. These hit at 86% win rate (6W-1L).
3. **If "high variance" or "bad defense":** Check the injury-adjusted total. If 15+ points below the posted line, take the under regardless of DRTG concerns.
4. **If "H2H historically high-scoring":** Check if combined PPG missing exceeds 30. If yes, current injury context overrides H2H history. Take the under.
5. **If "injury uncertainty":** Verify if the player is actually confirmed OUT or genuinely GTD. If confirmed OUT, the uncertainty is resolved and the stated edge applies.
6. **If veto:** Check if the veto is based on a factual error (Butler roster assignment, player identity confusion) vs a genuine analytical flaw. If factual error, evaluate the underlying edge independently.
7. **Cap sizing:** Never exceed 1.0u on a single paper trade. Do not use 2.0u sizing — the high-confidence 2.0u format is net-negative on a gross unit basis.
8. **Cap spreads:** Do not take paper trades on spreads larger than -12. Prefer spreads under 10 points for contrarian spread plays.

---

## Change Log

### 2026-03-10 — Major expansion based on 22 settled trades and 19 daily journals

**What changed:** Expanded the strategy from a 4-bullet stub to a full data-driven document covering skip pattern win rates, bet sizing rules, blind spot identification, and a decision framework.

**Data reviewed:**
- 22 settled trades from 2026-02-20 through 2026-03-09 (history.json)
- 20 daily journals from 2026-02-19 through 2026-03-10 (~90+ individual picks across all journals)
- Overall settled record: 14W-8L (63.6%), +2.5 net units

**Key findings that drove changes:**

1. **Confidence inversion discovered — Low 5W-0L, High 3W-4L (sample: 22 trades):** Added explicit sizing cap of 1.0u max for all plays. Eliminated the 2.0u high-confidence sizing format. The four 2.0u losses (DEN @ GSW, CHA @ WAS, WAS @ NOP, ORL @ PHX) cost -8.0u; the 2.0u wins returned only +6.0u. Net on the 2.0u format: -2.0u across 7 bets.

2. **Portfolio-limit skip pattern: 6W-1L (86%, sample: 7 trades):** The primary analyst's bet-count limits systematically leave value on the table. Added dedicated section and decision rule: when a skip reason acknowledges an edge but cites portfolio limits, treat as a high-priority paper trade.

3. **"Bad defense" skip reason is wrong 75% of the time (sample: 4 trades):** Added explicit rule: bad team DRTG does not compensate for offensive voids from injuries. Injury math overrides defensive rating concerns when the injury-adjusted gap is 15+ points.

4. **H2H history irrelevant when 30+ PPG missing (sample: 6 trades, 4W-2L):** Added rule discounting H2H over rates under mass-injury conditions. The analyst cited H2H as a skip reason repeatedly; paper trades won 4 of 6 by ignoring it.

5. **Spread sizing cap added at -12:** The BKN @ DET -14.5 loss (Brooklyn won outright) demonstrated that large spreads fail even against genuinely inferior teams. Added -12 ceiling for paper trade spreads.

6. **Jimmy Butler roster error identified as recurrent veto trigger:** At least 4 vetoes across multiple journal dates were based on "Butler plays for Warriors" analytical error. Added guidance to evaluate vetoed plays independently when the veto cites a factual roster error rather than a logical flaw in the edge calculation.
