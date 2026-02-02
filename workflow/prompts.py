"""Prompt templates for betting workflow."""

import json
from typing import Any, Dict, List

SYSTEM_ANALYST = """You are an expert NBA betting analyst. You analyze matchup data to identify
betting edges. Focus on statistical edges, situational factors, H2H patterns,
and injury impact. Be objective and data-driven. Acknowledge uncertainty.
Never force a bet - "no edge" is a valid conclusion."""


def condense_matchup(full_data: Dict[str, Any]) -> Dict[str, Any]:
    """Extract key betting-relevant data to reduce context size."""
    team1 = full_data["current_season"]["team1"]
    team2 = full_data["current_season"]["team2"]
    schedule = full_data.get("schedule", {})
    players = full_data.get("players", {})
    h2h = full_data.get("h2h", {})

    return {
        "matchup": full_data["matchup"],
        "records": {
            "team1": {
                "name": team1["name"],
                "record": team1["record"],
                "conf_rank": team1.get("conf_rank"),
                "home_record": team1.get("home_record"),
                "away_record": team1.get("away_record"),
            },
            "team2": {
                "name": team2["name"],
                "record": team2["record"],
                "conf_rank": team2.get("conf_rank"),
                "home_record": team2.get("home_record"),
                "away_record": team2.get("away_record"),
            },
        },
        "net_ratings": {
            "team1": team1.get("net_rating"),
            "team2": team2.get("net_rating"),
        },
        "offensive_ratings": {
            "team1": team1.get("ortg"),
            "team2": team2.get("ortg"),
        },
        "defensive_ratings": {
            "team1": team1.get("drtg"),
            "team2": team2.get("drtg"),
        },
        "recent_form": {
            "team1": {
                "last_ten": team1.get("last_ten"),
                "streak": schedule.get("team1", {}).get("streak"),
                "days_rest": schedule.get("team1", {}).get("days_rest"),
                "games_last_7_days": schedule.get("team1", {}).get("games_last_7_days"),
            },
            "team2": {
                "last_ten": team2.get("last_ten"),
                "streak": schedule.get("team2", {}).get("streak"),
                "days_rest": schedule.get("team2", {}).get("days_rest"),
                "games_last_7_days": schedule.get("team2", {}).get("games_last_7_days"),
            },
        },
        "recent_games": full_data.get("recent_games", {}),
        "h2h_summary": h2h.get("summary", {}),
        "h2h_patterns": h2h.get("patterns", {}),
        "h2h_quarters": h2h.get("quarters", {}),  # Include quarter-by-quarter trends
        "players": {
            "team1": {
                "top_scorers": players.get("team1", {}).get("top_scorers"),
                "full_strength": players.get("team1", {}).get("full_strength"),
                "availability_concerns": players.get("team1", {}).get(
                    "availability_concerns", []
                ),
                "star_dependency": players.get("team1", {}).get("star_dependency"),
                "bench_scoring": players.get("team1", {}).get("bench_scoring"),
            },
            "team2": {
                "top_scorers": players.get("team2", {}).get("top_scorers"),
                "full_strength": players.get("team2", {}).get("full_strength"),
                "availability_concerns": players.get("team2", {}).get(
                    "availability_concerns", []
                ),
                "star_dependency": players.get("team2", {}).get("star_dependency"),
                "bench_scoring": players.get("team2", {}).get("bench_scoring"),
            },
        },
        "totals_analysis": full_data.get("totals_analysis", {}),
        "comparison": full_data.get("comparison", {}),
        "signals": full_data.get("signals", []),
    }


ANALYZE_GAME_PROMPT = """Analyze this NBA matchup for betting value across all bet types.

## Matchup: {matchup}
**{home_team} is HOME** (NBA home teams win ~58% historically)

## Matchup Data
{matchup_json}

## Current Strategy
{strategy}

## Bet Types to Evaluate
1. **Moneyline**: Which team wins outright?
2. **Spread**: Use expected_margin to determine if a team covers. Example: if you expect Team A to win by 6, they cover -4.5.
3. **Totals**: Use expected_total and H2H patterns. Check if teams consistently go over/under in matchups.

## Key Factors
- Net rating diff >3 is significant (~3 points of expected margin)
- Home court worth ~3 points
- Rest advantage (2+ days vs B2B) worth ~3 points
- H2H totals patterns: check avg_total in h2h_patterns
- Pace comparison affects totals (high pace = more possessions = more points)

## Confidence Thresholds
- High: 5+ point edge equivalent AND multiple factors align
- Medium: 3-4 point edge equivalent OR one strong factor
- Low: Slight lean but significant uncertainty
- Skip: No clear edge

Respond with JSON:
{{
  "game_id": "{game_id}",
  "matchup": "{matchup}",
  "expected_margin": 5.5,  // Positive = home team favored, negative = away favored
  "expected_total": 225.0,  // Your projected combined score
  "moneyline": {{
    "pick": "Team Name" | null,
    "confidence": "low" | "medium" | "high" | "skip",
    "edge": "Why this team wins"
  }},
  "spread": {{
    "pick": "Team Name",
    "line": -4.5,  // Negative = favorite, positive = underdog
    "confidence": "low" | "medium" | "high" | "skip",
    "edge": "Why they cover"
  }},
  "total": {{
    "pick": "over" | "under",
    "line": 224.5,  // The projected total to bet against
    "confidence": "low" | "medium" | "high" | "skip",
    "edge": "Pace/defensive factors"
  }},
  "best_bet": "moneyline" | "spread" | "total" | "none",
  "primary_edge": "Main edge across all bet types",
  "case_for": ["reason 1", ...],
  "case_against": ["risk 1", ...],
  "analysis_summary": "2-3 sentence summary"
}}"""


SYNTHESIZE_BETS_PROMPT = """You have analyzed multiple games. Now select up to {max_bets} bets (0 is acceptable).

## Game Analyses
{analyses_json}

## Current Strategy
{strategy}

## Betting History Summary
{history_summary}

## Instructions
1. Compare edges across ALL bet types (moneyline, spread, totals) across all games
2. **0 bets is perfectly acceptable** if no games have clear edges
3. You can bet different types on the same game if edges exist (e.g., spread AND total)
4. Quality over quantity - don't force bets to fill the {max_bets} limit
5. Assign units based on confidence:
   - High confidence: 2.0 units (requires strong, multi-factor edge)
   - Medium confidence: 1.0 units (clear single edge)
   - Low confidence: 0.5 units (slight edge, worth small position)
6. **Avoid correlated bets**: Don't bet multiple moneylines on the same edge type
7. Totals bets are often less correlated with sides - can provide diversification

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


UPDATE_STRATEGY_PROMPT = """Update the betting strategy based on actual results.

## Current Strategy
{current_strategy}

## Performance Summary
{history_summary}

## Recent Bets (last 20)
{recent_bets}

## Recent Journal Entries
{recent_journals}

## Instructions
Analyze the data to find SPECIFIC patterns:

1. **Edge Analysis**: Which edge types are actually profitable? (Check by_primary_edge stats)
   - Are home court edges working? Rest advantages? Ratings edges?
   - Should we avoid any edge types that have negative ROI?

2. **Confidence Calibration**: Are our confidence levels accurate?
   - Are high confidence bets actually winning at a higher rate?
   - Should we adjust unit sizing based on actual results?

3. **Specific Thresholds**: Based on wins vs losses, identify:
   - What net rating differential actually predicts wins?
   - How much does rest advantage matter in practice?
   - Any team-specific patterns?

4. **Process Fixes**: Look at reflections in journal entries
   - What factors did we consistently miss?
   - What should we weight more/less?

Write a complete updated strategy.md document with:
- Core Principles (keep what works, cut what doesn't)
- Confidence Guidelines (adjusted based on actual calibration)
- Key Factors to Weight (with specific thresholds from data)
- What to Avoid (edges that haven't worked)
- Performance Notes (current record: {wins}-{losses}, ROI: {roi}%)

Be SPECIFIC. Use actual numbers from the data. Don't give generic advice."""


def format_analyses_for_synthesis(
    analyses: List[Dict[str, Any]],
) -> str:
    """Format analyses for synthesis prompt."""
    return json.dumps(analyses, indent=2)


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
            lines.append(
                f"  {conf}: {stats['wins']}-{stats['losses']} ({stats['win_rate']:.1%})"
            )

    if summary.get("by_bet_type"):
        lines.append("\nBy Bet Type:")
        for bet_type, stats in summary["by_bet_type"].items():
            lines.append(
                f"  {bet_type}: {stats['wins']}-{stats['losses']} ({stats['win_rate']:.1%})"
            )

    if summary.get("by_primary_edge"):
        lines.append("\nBy Edge Type:")
        for edge, stats in summary["by_primary_edge"].items():
            lines.append(
                f"  {edge}: {stats['wins']}-{stats['losses']} ({stats['win_rate']:.1%})"
            )

    return "\n".join(lines)
