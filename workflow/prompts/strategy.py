"""Strategy, reflection, and history formatting prompts."""

from typing import Any, Dict

MIN_ACTIONABLE_SAMPLE = 10


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
{prop_context}

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

## Context
{date_context}

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

## Paper Trading Insights (games we skipped)
{paper_trade_insights}

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


UPDATE_PAPER_STRATEGY_PROMPT = """Review the paper trading strategy and propose adjustments.

## Context
{date_context}

## Current Paper Strategy
{current_strategy}

## Paper Trade Performance ({wins}-{losses}, {win_rate:.1%} win rate, {net_units:+.1f} units)
{history_summary}

## Recent Paper Trades (last 20)
{recent_trades}

## Recent Paper Journal Entries
{recent_journals}

## Instructions
Paper trading tracks games the primary analyst SKIPPED. Your goal is to get better at
finding value in these skipped games. Analyze patterns:

1. Which skip reasons lead to the most profitable paper trades?
2. Which bet types work best on skipped games?
3. Are there confidence levels that are consistently profitable?
4. What contrarian edges keep showing up?

Propose 0-3 targeted adjustments to improve paper trade selection.

Respond with JSON:
{{
  "adjustments": [
    {{
      "section": "Section name to modify",
      "updated_content": "Full replacement content",
      "change_description": "What changed",
      "reasoning": "Data-backed justification"
    }}
  ],
  "insights_for_main_strategy": [
    "Insight that could improve the main strategy's skip decisions"
  ],
  "summary": "1-sentence summary"
}}"""


MIN_PAPER_TRADES_FOR_INSIGHTS = 15


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


def format_paper_history_summary(summary: dict) -> str:
    """Format paper trade history summary for prompts."""
    if summary.get("total_trades", 0) == 0:
        return "No paper trade history yet."

    pushes = summary.get("pushes", 0)
    if pushes > 0:
        record_str = f"{summary['wins']}-{summary['losses']}-{pushes}"
    else:
        record_str = f"{summary['wins']}-{summary['losses']}"

    lines = [
        f"Record: {record_str} ({summary['win_rate']:.1%})",
        f"Net Units: {summary['net_units']:+.1f}",
    ]

    if summary.get("by_confidence"):
        lines.append("\nBy Confidence:")
        for conf, stats in summary["by_confidence"].items():
            lines.append(f"  {conf}: {stats['wins']}-{stats['losses']} ({stats['win_rate']:.1%})")

    if summary.get("by_bet_type"):
        lines.append("\nBy Bet Type:")
        for bt, stats in summary["by_bet_type"].items():
            lines.append(f"  {bt}: {stats['wins']}-{stats['losses']} ({stats['win_rate']:.1%})")

    if summary.get("by_skip_reason_category"):
        lines.append("\nBy Skip Reason:")
        for reason, stats in summary["by_skip_reason_category"].items():
            lines.append(f"  {reason}: {stats['wins']}-{stats['losses']} ({stats['win_rate']:.1%})")

    return "\n".join(lines)


def format_paper_trade_insights(summary: dict) -> str:
    """Format paper trade performance for inclusion in main strategy update."""
    total = summary.get("total_trades", 0)
    if total < MIN_PAPER_TRADES_FOR_INSIGHTS:
        return f"Paper trading: Not enough data yet ({total} trades, need {MIN_PAPER_TRADES_FOR_INSIGHTS})."

    wins = summary.get("wins", 0)
    losses = summary.get("losses", 0)
    net = summary.get("net_units", 0.0)

    lines = [
        f"Paper trading on skipped games: {wins}-{losses} ({summary.get('win_rate', 0):.1%}), {net:+.1f} units",
    ]

    by_reason = summary.get("by_skip_reason_category", {})
    if by_reason:
        lines.append("By skip reason:")
        for reason, stats in sorted(by_reason.items(), key=lambda x: x[1].get("win_rate", 0), reverse=True):
            n = stats["wins"] + stats["losses"]
            lines.append(f"  {reason}: {stats['wins']}-{stats['losses']} ({stats['win_rate']:.1%}) — {n} trades")

    return "\n".join(lines)
