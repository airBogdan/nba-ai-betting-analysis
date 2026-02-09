"""Prompt templates for betting workflow."""

import json
from typing import Any, Dict, List

MIN_ACTIONABLE_SAMPLE = 10

SYSTEM_ANALYST = """You are an expert NBA betting analyst. You analyze matchup data to identify
betting edges. Focus on statistical edges, situational factors, H2H patterns,
and injury impact. Be objective and data-driven. Acknowledge uncertainty.
Never force a bet - "no edge" is a valid conclusion."""


def compact_json(data: Any) -> str:
    """Serialize data to compact JSON, stripping None/empty values."""
    def _clean(obj):
        if isinstance(obj, dict):
            return {k: _clean(v) for k, v in obj.items()
                    if v is not None and v != [] and v != {} and not str(k).startswith("_")}
        elif isinstance(obj, list):
            return [_clean(i) for i in obj]
        return obj
    return json.dumps(_clean(data), separators=(", ", ": "))


ODDS_CONTEXT_SECTION = """## Using the Odds Data
The matchup data includes an "odds" object with betting lines:
- **spread**: Main spread with line and price for home/away teams
- **total**: Main total with line, over price, under price
- **moneyline**: Straight-up win prices for each team
- **alternate_spreads**: 4 alternate spread lines (2 lower, 2 higher than main) - prices shown are for HOME team
- **alternate_totals**: 4 alternate total lines (2 lower, 2 higher than main) - prices shown are for OVER

**Using alternates**: If your expected margin is close to the main line, check alternates for better value:
- If you expect home -8 but main line is -6.5, check if home -8.5 or -9.5 alternate has good + odds
- If you expect total of 218 but line is 224.5, the under at 220.5 alternate may offer better value
- Note: alternate_spreads prices are for HOME team; for away bets, use the main spread or mentally flip the line

**Price evaluation**: American odds context:
- -110 is standard juice (bet $110 to win $100)
- Positive odds (+150) mean underdog, higher = more value if you're confident
- Large negative odds (-300+) rarely offer value unless you have very high confidence

**Line discrepancies**: If the web search context shows different lines than the matchup data odds, prefer the web search lines — they are more current. The API odds may be hours old. Do not skip a game just because lines differ between sources.
"""

NO_ODDS_SECTION = """
Note: No odds data available for this game. Base analysis on statistical matchup data only.
"""


ANALYZE_GAME_PROMPT = """Analyze this NBA matchup for betting value across all bet types.

## Matchup: {matchup}
**{home_team} is HOME** (NBA home teams win ~58% historically)

## Matchup Data
{matchup_json}
{search_context}
## Current Strategy
{strategy}

{odds_context}
## Bet Types to Evaluate
1. **Moneyline**: Which team wins outright? Consider the price - heavy favorites (-300+) need high confidence.
2. **Spread**: Use expected_margin to determine if a team covers. Consider alternate lines if edge is marginal.
3. **Totals**: Use expected_total and H2H patterns. Check alternate totals if your projection differs from the line.

## Multiple Bets Per Game
You can recommend MULTIPLE bets on the same game if independent edges exist:
- Spread + Total often have uncorrelated edges (team wins big doesn't mean high-scoring)
- Different alternate lines can both have value (e.g., spread AND alternate total)
- Only combine if each bet has its own valid reasoning - don't force it

## Key Factors
- Net rating diff >3 is significant (~3 points of expected margin)
- Home court worth ~3 points
- Rest advantage (2+ days vs B2B) worth ~3 points
- H2H totals patterns: check avg_total in h2h_patterns
- Pace comparison affects totals (high pace = more possessions = more points)
- **IMPORTANT**: All season stats (PPG, net rating, expected_total) are FULL-STRENGTH numbers. They do NOT reflect tonight's injuries. Use `injury_impact` data when available to adjust projections. If `injury_impact` is missing but search context mentions injuries, manually estimate the impact.

## Confidence Thresholds
- High: 5+ point edge equivalent AND multiple factors align
- Medium: 3-4 point edge equivalent OR one strong factor
- Low: Slight lean but significant uncertainty
- Skip: No clear edge

## Required Analysis Steps
Before making picks, work through these calculations explicitly:
1. **Expected Margin**: Start with net_rating_diff / 2, add home_court (+3), add rest_adj, add injury_adj (use `injury_impact.missing_ppg_diff` when available) → your expected margin
2. **Expected Total**: Use `injury_adjusted_total` from totals_analysis if available (already accounts for injuries). Otherwise start with expected_total and manually subtract estimated injury PPG loss from search context.
3. **Edge Check**: For each bet type, state "My projection: X, Line: Y, Edge: Z" before assigning confidence

Respond with JSON:
{{
  "game_id": "{game_id}",
  "matchup": "{matchup}",
  "margin_calculation": {{
    "net_rating_component": 2.5,
    "home_court_adj": 3.0,
    "rest_adj": 0.0,
    "injury_adj": 0.0,
    "raw_margin": 5.5
  }},
  "expected_margin": 5.5,  // Positive = home team favored, negative = away favored
  "expected_total": 225.0,  // Your projected combined score
  "moneyline": {{
    "pick": "Team Name" | null,
    "confidence": "low" | "medium" | "high" | "skip",
    "edge": "Why this team wins"
  }},
  "spread": {{
    "pick": "Team Name",
    "line": -4.5,  // The line you're betting (can be main or alternate)
    "confidence": "low" | "medium" | "high" | "skip",
    "edge": "Why they cover at this number"
  }},
  "total": {{
    "pick": "over" | "under",
    "line": 224.5,  // The line you're betting (can be main or alternate)
    "confidence": "low" | "medium" | "high" | "skip",
    "edge": "Pace/defensive factors"
  }},
  "recommended_bets": [  // Can include 0, 1, 2, or 3 bets from this game
    {{
      "bet_type": "spread" | "total" | "moneyline",
      "pick": "Team Name" | "over" | "under",
      "line": -4.5 | 224.5 | null,  // null for moneyline
      "confidence": "low" | "medium" | "high",
      "edge": "Specific edge for this bet"
    }}
  ],
  "primary_edge": "Main edge across all bet types",
  "case_for": ["reason 1", ...],
  "case_against": ["risk 1", ...],
  "analysis_summary": "2-3 sentence summary"
}}"""


SYNTHESIZE_BETS_PROMPT = """You have analyzed multiple games. Now select up to {max_bets} bets (0 is acceptable).

## Game Analyses
{analyses_json}

Each analysis includes a "recommended_bets" array - these are the analyst's pre-selected value bets from each game. Review these carefully.

## Current Strategy
{strategy}

## Betting History Summary
{history_summary}

## Instructions
1. Review "recommended_bets" from each game analysis - these already passed initial value screening
2. **0 bets is perfectly acceptable** if no games have clear edges
3. **Multiple bets per game is encouraged** when independent edges exist:
   - Spread + Total often have uncorrelated outcomes
   - A game can have value on both the side AND the total
   - Each bet must have its own valid edge - don't bet both just because one is good
4. Quality over quantity - don't force bets to fill the {max_bets} limit
5. Assign units based on confidence:
   - High confidence: 2.0 units (requires strong, multi-factor edge)
   - Medium confidence: 1.0 units (clear single edge)
   - Low confidence: 0.5 units (slight edge, worth small position)
6. **Correlation awareness**:
   - Spread + moneyline on same team = correlated (pick one)
   - Spread + total = usually uncorrelated (can bet both)
   - Multiple games with same edge type = consider diversifying
7. Use the specific line from the analysis (may be alternate, not main line)
8. Use expected_margin to evaluate spread bets - look for meaningful edges where the margin clearly exceeds the line.

Respond with JSON:
{{
  "selected_bets": [
    {{
      "game_id": "...",
      "matchup": "Away @ Home",
      "bet_type": "moneyline" | "spread" | "total",
      "pick": "Team Name" | "over" | "under",
      "line": null | -4.5 | 224.5,
      "confidence": "low" | "medium" | "high",
      "units": 0.5 | 1.0 | 2.0,
      "reasoning": "Why this bet",
      "primary_edge": "Key factor"
    }}
  ],
  "skipped": [
    {{
      "matchup": "Away @ Home",
      "reason": "Why skipped"
    }}
  ],
  "summary": "1-2 sentence summary of today's slate"
}}"""


REFLECT_BET_PROMPT = """Reflect on this completed bet.

## Bet Details
- Matchup: {matchup}
- Bet Type: {bet_type}
- Pick: {pick}
- Line: {line}
- Confidence: {confidence}
- Units: {units}
- Reasoning: {reasoning}
- Primary Edge: {primary_edge}

## Actual Result
- Final Score: {final_score}
- Winner: {winner}
- Actual Total: {actual_total}
- Actual Margin: {actual_margin} (positive = home win)
- Our Outcome: **{outcome}**

## Instructions
Consider:
1. Was the primary edge we identified valid? (Edge can be valid even if we lost)
2. Based on the score, were there factors we might have missed or underweighted?
3. Was the process sound? Separate result luck from decision quality:
   - "sound": Good reasoning, would bet again in same spot
   - "unlucky": Good reasoning but variance went against us (close loss)
   - "flawed": Missed something important we should have caught
   - "lucky": Won but reasoning was weak
4. What's the actionable lesson?

Keep the summary brief - 1-2 sentences max.

Respond with JSON:
{{
  "edge_valid": true | false,
  "missed_factors": ["factor 1", ...],
  "process_assessment": "sound" | "flawed" | "unlucky" | "lucky",
  "key_lesson": "One sentence takeaway",
  "summary": "1-2 sentence reflection"
}}"""


UPDATE_STRATEGY_PROMPT = """Review the betting strategy and propose small, targeted adjustments based on actual results.

## Current Strategy
{current_strategy}

## Performance Summary (Record: {wins}-{losses}, ROI: {roi}%)
{history_summary}

## Recent Bets (last 20)
{recent_bets}

## Reflection Patterns
{reflection_patterns}

## Recent Journal Entries
{recent_journals}

## Instructions
Propose 0-3 SMALL, SPECIFIC adjustments to the strategy. These will compound over many runs.

**Rules:**
1. Each adjustment targets ONE specific rule, threshold, or guideline
2. Each MUST be supported by data from 10+ bets in the relevant category
3. Ignore any category marked "(small sample — not actionable)"
4. Do NOT rewrite entire sections — change one thing per adjustment
5. If data doesn't clearly support a change, propose 0 adjustments
6. Check the Change Log at the bottom of the strategy to avoid reverting recent changes or flip-flopping

**What qualifies as an adjustment:**
- Adjusting a threshold (e.g., "raise spread edge minimum from 5 to 6 points")
- Adding ONE specific rule backed by data (e.g., "avoid totals bets on B2B games")
- Removing a rule that data shows doesn't work
- Reweighting a factor based on results

**What does NOT qualify:**
- Rewriting a section's structure or tone
- Generic advice not tied to specific numbers
- Changes based on fewer than 10 bets
- Multiple changes bundled into one adjustment

The `updated_content` field must contain the COMPLETE new content for that section — all lines, including unchanged ones. Do NOT include the ## header line itself.

Respond with JSON:
{{
  "adjustments": [
    {{
      "section": "Exact name of the ## section to modify",
      "updated_content": "Full replacement content for this section",
      "change_description": "One-line summary of what changed",
      "reasoning": "Data-backed justification citing actual W-L records or patterns"
    }}
  ],
  "no_change_reasons": ["Why a specific area was left unchanged despite data"],
  "summary": "1-sentence summary of this update"
}}

If no changes are warranted, return an empty adjustments array with explanations in no_change_reasons."""


EXTRACT_INJURIES_PROMPT = """Extract injured/out players from this pre-game report.

## Teams
Team 1: {team1}
Team 2: {team2}

## Report
{search_context}

## Instructions
Return a JSON array of players who are **Out** or **Doubtful** only. Skip Questionable/Probable/Available.
Each entry: {{"team": "Full Team Name", "player": "Player Name", "status": "Out" or "Doubtful"}}
If no players are out/doubtful, return an empty array: []

Respond with only the JSON array, no other text."""


SEARCH_QUERY_SYSTEM = (
    "You identify research angles for NBA game betting analysis. "
    "When generating a research directive, use 1-2 clear sentences describing what to investigate and why. "
    "Not keywords. Be specific. Follow the user's instructions exactly."
)

SEARCH_PERPLEXITY_WRAPPER = """Research the following for an NBA betting analysis.

Game: {matchup}

**Research focus:** {directive}

Report your findings organized under clear headers. Include:
- Specific facts, statuses, and numbers (not speculation)
- Sources or timeframes for injury/news items when available
- Any context that explains *why* something matters for this game

Keep it factual and concise. Do not make predictions or betting recommendations."""

SEARCH_TEMPLATE_PROMPT = """I need a pre-game research report for an NBA game today.

**Game: {matchup}**

Research and report on the following, organized under these exact headers:

### Injury Report
Current injury/availability statuses for both teams. List each player with their status (out, doubtful, questionable, probable) and injury type.

### Betting Lines
Current consensus spread, moneyline odds, and over/under total.

### Line Movement
Notable moves from opening lines. What drove the movement if known.

### Recent News
Relevant team news from the last 48 hours — roster moves, rotation changes, notable performances, rest decisions.

Facts only. If a section has no relevant information, state that briefly."""

SEARCH_FOLLOWUP_GENERATION_PROMPT = """Review the initial search results below and identify any important gaps for betting analysis.

Matchup: {matchup}

{search_summary}

### Initial Search Results
{search_results}

If the results adequately cover injuries, betting lines, line movement, and recent news, respond with exactly: "No follow-up needed"

Otherwise, describe in 1-2 sentences what additional information would be most valuable for betting analysis on this game and why. Be specific — not keywords, but a clear research directive."""


def format_analyses_for_synthesis(
    analyses: List[Dict[str, Any]],
) -> str:
    """Format analyses for synthesis prompt."""
    return json.dumps(analyses, indent=2)


SYSTEM_SIZING = """You are an expert betting bankroll manager. Your job is to:
1. Review proposed bets and validate the reasoning
2. Assign appropriate dollar amounts based on edge strength and bankroll management
3. Veto bets with weak reasoning (assign $0)
You have full discretion. Learn from results over time.

IMPORTANT: The roster/player data comes from a live API and reflects current rosters including recent trades. Trades happen frequently and your training data may be outdated."""


SIZING_PROMPT = """Review these proposed bets and assign dollar amounts.

## Current Bankroll
- Starting: ${starting:.2f}
- Current: ${current:.2f}
- Available: ${available:.2f}

## Today's Proposed Bets
{proposed_bets_json}

## Sizing Strategy (from strategy.md)
{sizing_strategy}

## Recent Performance
{history_summary}

## Sizing Method: Half Kelly Criterion
Each bet includes `kelly_recommended` — the mathematically optimal half-Kelly amount based on:
- Confidence → win probability: high=65%, medium=57%, low=54%
- Actual odds price for the bet
- Capped at 3% of bankroll per bet

## Your Job
For each bet:
1. **Validate**: Is the reasoning sound? Is the edge real?
2. **Size**: Use `kelly_recommended` as your baseline. You may reduce below Kelly for weak reasoning.
3. **Veto**: Assign $0 if the edge isn't real. Do NOT size above `kelly_recommended`.

Respond with JSON:
{{
  "sizing_decisions": [
    {{
      "bet_id": "...",
      "action": "place" | "skip",
      "amount": 25.00,
      "reasoning": "Why this amount (or why vetoed)"
    }}
  ],
  "daily_exposure": 75.00,
  "sizing_notes": "Brief note on today's approach"
}}"""


def format_history_summary(summary: Dict[str, Any]) -> str:
    """Format history summary for prompts."""
    if summary.get("total_bets", 0) == 0:
        return "No betting history yet - first day of tracking."

    # Build record string, include pushes if any
    pushes = summary.get("pushes", 0)
    if pushes > 0:
        record_str = f"{summary['wins']}-{summary['losses']}-{pushes}"
    else:
        record_str = f"{summary['wins']}-{summary['losses']}"

    lines = [
        f"Record: {record_str} ({summary['win_rate']:.1%})",
        f"Net Units: {summary['net_units']:+.1f}",
        f"ROI: {summary['roi']:.1%}",
        f"Current Streak: {summary['current_streak']}",
    ]

    if summary.get("by_confidence"):
        lines.append("\nBy Confidence:")
        for conf, stats in summary["by_confidence"].items():
            n = stats["wins"] + stats["losses"] + stats.get("pushes", 0)
            tag = "" if n >= MIN_ACTIONABLE_SAMPLE else " (small sample — not actionable)"
            lines.append(
                f"  {conf}: {stats['wins']}-{stats['losses']} ({stats['win_rate']:.1%}){tag}"
            )

    if summary.get("by_bet_type"):
        lines.append("\nBy Bet Type:")
        for bet_type, stats in summary["by_bet_type"].items():
            n = stats["wins"] + stats["losses"] + stats.get("pushes", 0)
            tag = "" if n >= MIN_ACTIONABLE_SAMPLE else " (small sample — not actionable)"
            lines.append(
                f"  {bet_type}: {stats['wins']}-{stats['losses']} ({stats['win_rate']:.1%}){tag}"
            )

    if summary.get("by_primary_edge"):
        lines.append("\nBy Edge Type:")
        for edge, stats in summary["by_primary_edge"].items():
            n = stats["wins"] + stats["losses"] + stats.get("pushes", 0)
            tag = "" if n >= MIN_ACTIONABLE_SAMPLE else " (small sample — not actionable)"
            lines.append(
                f"  {edge}: {stats['wins']}-{stats['losses']} ({stats['win_rate']:.1%}){tag}"
            )

    return "\n".join(lines)
