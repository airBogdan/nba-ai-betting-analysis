"""Pre-game analysis workflow."""

import asyncio
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .io import (
    BETS_DIR,
    JOURNAL_DIR,
    get_active_bets,
    get_bankroll,
    get_history,
    read_text,
    revert_bankroll_for_date,
    save_active_bets,
    save_bankroll,
    write_text,
)
from .llm import complete_json
from .prompts import (
    ANALYZE_GAME_PROMPT,
    SIZING_PROMPT,
    SYNTHESIZE_BETS_PROMPT,
    SYSTEM_ANALYST,
    SYSTEM_SIZING,
    compact_json,
    format_analyses_for_synthesis,
    format_history_summary,
)
from .types import ActiveBet, Bankroll, BetRecommendation, SelectedBet

# Limit concurrent LLM calls to avoid rate limiting
MAX_CONCURRENT_LLM_CALLS = 4

OUTPUT_DIR = Path(__file__).parent.parent / "output"


def load_games_for_date(date: str) -> List[Dict[str, Any]]:
    """Load matchup files for a specific date."""
    games = []
    pattern = f"*_{date}.json"
    for path in OUTPUT_DIR.glob(pattern):
        try:
            data = json.loads(path.read_text())
            data["_file"] = path.name
            games.append(data)
        except (json.JSONDecodeError, OSError) as e:
            print(f"Error loading {path}: {e}")
    return games


def extract_game_id(filename: str) -> str:
    """Extract game ID from filename."""
    return filename.replace(".json", "")


def format_matchup_string(matchup: Dict[str, Any]) -> str:
    """Format matchup as 'Away @ Home'."""
    home = matchup.get("home_team", "")
    team1 = matchup.get("team1", "")
    team2 = matchup.get("team2", "")
    if team1 == home:
        return f"{team2} @ {team1}"
    return f"{team1} @ {team2}"


def _save_game_file(game: Dict[str, Any]) -> None:
    """Save game data back to its JSON file, preserving search_context."""
    filename = game["_file"]
    path = OUTPUT_DIR / filename
    save_data = {k: v for k, v in game.items() if not k.startswith("_")}
    path.write_text(json.dumps(save_data, indent=2))


async def _enrich_games_with_search(games: List[Dict[str, Any]], date: str) -> None:
    """Run web search enrichment on games and save results to their JSON files."""
    from .search import sanitize_label, search_enrich

    semaphore = asyncio.Semaphore(MAX_CONCURRENT_LLM_CALLS)

    async def enrich_one(game: Dict[str, Any]) -> None:
        async with semaphore:
            matchup_str = format_matchup_string(game["matchup"])
            game_label = sanitize_label(matchup_str)
            print(f"  {matchup_str}")
            result = await search_enrich(game, matchup_str, game_label)
            if result:
                game["search_context"] = result
                _save_game_file(game)

    tasks = [enrich_one(game) for game in games]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for r in results:
        if isinstance(r, Exception):
            print(f"Search enrichment error: {r}")


async def analyze_game(
    game_data: Dict[str, Any],
    game_id: str,
    matchup_str: str,
    strategy: Optional[str],
) -> Optional[BetRecommendation]:
    """Analyze a single game with the LLM."""
    home_team = game_data.get("matchup", {}).get("home_team", "Unknown")

    search_context = game_data.get("search_context")
    search_section = f"\n## Web Search Context\n{search_context}\n\n" if search_context else "\n"

    # Strip internal/search keys before serializing for the LLM (search_context
    # is injected as its own prompt section, not buried in the JSON blob)
    clean_data = {k: v for k, v in game_data.items() if not k.startswith("_") and not k.startswith("search_context")}

    prompt = ANALYZE_GAME_PROMPT.format(
        matchup_json=compact_json(clean_data),
        search_context=search_section,
        strategy=strategy or "No strategy defined yet.",
        game_id=game_id,
        matchup=matchup_str,
        home_team=home_team,
    )

    result = await complete_json(prompt, system=SYSTEM_ANALYST)
    if result:
        result["game_id"] = game_id
        result["matchup"] = matchup_str
    return result


async def synthesize_bets(
    recommendations: List[BetRecommendation],
    strategy: Optional[str],
    history_summary: Dict[str, Any],
    max_bets: int,
) -> Optional[Dict[str, Any]]:
    """Synthesize recommendations into final bet selections."""
    prompt = SYNTHESIZE_BETS_PROMPT.format(
        max_bets=max_bets,
        analyses_json=format_analyses_for_synthesis(recommendations),
        strategy=strategy or "No strategy defined yet.",
        history_summary=format_history_summary(history_summary),
    )

    return await complete_json(prompt, system=SYSTEM_ANALYST)


VALID_CONFIDENCE = {"low", "medium", "high"}
VALID_BET_TYPES = {"moneyline", "spread", "total"}
CONFIDENCE_TO_UNITS = {"low": 0.5, "medium": 1.0, "high": 2.0}


def _normalize_confidence(raw: str) -> str:
    """Normalize confidence value to valid enum."""
    if raw in VALID_CONFIDENCE:
        return raw
    # Try to infer from common variations
    raw_lower = raw.lower() if raw else ""
    if "high" in raw_lower or "strong" in raw_lower:
        return "high"
    if "med" in raw_lower or "moderate" in raw_lower:
        return "medium"
    return "low"


def _normalize_bet_type(raw: str) -> str:
    """Normalize bet type to valid enum."""
    if raw in VALID_BET_TYPES:
        return raw
    raw_lower = raw.lower() if raw else ""
    if "spread" in raw_lower:
        return "spread"
    if "total" in raw_lower or "over" in raw_lower or "under" in raw_lower:
        return "total"
    return "moneyline"


def _normalize_units(raw_units: float, confidence: str) -> float:
    """Normalize units to valid values based on confidence."""
    if raw_units in (0.5, 1.0, 2.0):
        return raw_units
    # Fall back to confidence-based units
    return CONFIDENCE_TO_UNITS.get(confidence, 0.5)


def create_active_bet(selected: SelectedBet, date: str) -> ActiveBet:
    """Create an ActiveBet from a SelectedBet."""
    raw_confidence = selected.get("confidence", "low")
    confidence = _normalize_confidence(raw_confidence)
    units = _normalize_units(selected.get("units", 0.5), confidence)
    bet_type = _normalize_bet_type(selected.get("bet_type", "moneyline"))

    return {
        "id": str(uuid.uuid4()),
        "game_id": selected.get("game_id", "unknown"),
        "matchup": selected.get("matchup", "Unknown @ Unknown"),
        "bet_type": bet_type,
        "pick": selected.get("pick", "Unknown"),
        "line": selected.get("line"),
        "confidence": confidence,
        "units": units,
        "reasoning": selected.get("reasoning", "No reasoning provided"),
        "primary_edge": selected.get("primary_edge", "Unknown"),
        "date": date,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def _extract_sizing_strategy(strategy: Optional[str]) -> str:
    """Extract Position Sizing section from strategy.md."""
    if not strategy:
        return "No sizing strategy defined yet."
    # Find the Position Sizing section
    if "## Position Sizing" in strategy:
        start = strategy.index("## Position Sizing")
        # Find next ## or end of file
        rest = strategy[start + len("## Position Sizing") :]
        if "\n## " in rest:
            end = rest.index("\n## ")
            return strategy[start : start + len("## Position Sizing") + end]
        return strategy[start:]
    return "No sizing strategy defined yet."


def _get_odds_price(bet: ActiveBet) -> int:
    """Get American odds price for a bet. Default to -110 for spread/total."""
    # TODO: Could enhance to pull from stored odds data
    # For now, use -110 as standard juice for spread/total
    if bet["bet_type"] in ("spread", "total"):
        return -110
    # Moneyline: would need to look up from game data
    # For now default to -110 (conservative)
    return -110


def _fallback_sizing(bets: List[ActiveBet], bankroll: Bankroll) -> List[ActiveBet]:
    """Fallback sizing based on units if LLM fails."""
    unit_value = bankroll["current"] * 0.01  # 1% per unit
    for bet in bets:
        bet["amount"] = round(bet["units"] * unit_value, 2)
        bet["odds_price"] = _get_odds_price(bet)
    return bets


async def size_bets(
    proposed_bets: List[ActiveBet],
    bankroll: Bankroll,
    strategy: Optional[str],
    history_summary: Dict[str, Any],
) -> Tuple[List[ActiveBet], List[Dict[str, str]]]:
    """Size bets using LLM. Returns (sized_bets, sizing_skipped)."""
    # Calculate available bankroll (exclude pending bets from other dates)
    other_pending = [b for b in get_active_bets() if b.get("amount")]
    pending_amount = sum(b.get("amount", 0) for b in other_pending)
    available = bankroll["current"] - pending_amount

    prompt = SIZING_PROMPT.format(
        starting=bankroll["starting"],
        current=bankroll["current"],
        available=available,
        proposed_bets_json=json.dumps(
            [
                {
                    "id": b["id"],
                    "matchup": b["matchup"],
                    "bet_type": b["bet_type"],
                    "pick": b["pick"],
                    "line": b.get("line"),
                    "confidence": b["confidence"],
                    "units": b["units"],
                    "reasoning": b["reasoning"],
                    "primary_edge": b["primary_edge"],
                }
                for b in proposed_bets
            ],
            indent=2,
        ),
        sizing_strategy=_extract_sizing_strategy(strategy),
        history_summary=format_history_summary(history_summary),
    )

    result = await complete_json(prompt, system=SYSTEM_SIZING)
    if not result:
        # Fallback: use unit-based sizing
        return _fallback_sizing(proposed_bets, bankroll), []

    # Apply sizing decisions
    sized_bets = []
    skipped = []
    decisions = {d["bet_id"]: d for d in result.get("sizing_decisions", [])}

    for bet in proposed_bets:
        decision = decisions.get(bet["id"])
        if decision and decision.get("action") == "place" and decision.get("amount", 0) > 0:
            bet["amount"] = round(decision["amount"], 2)
            bet["odds_price"] = _get_odds_price(bet)
            sized_bets.append(bet)
        else:
            reason = decision.get("reasoning", "No reasoning") if decision else "No sizing decision"
            skipped.append({"matchup": bet["matchup"], "reason": f"Vetoed: {reason}"})

    return sized_bets, skipped


def write_journal_pre_game(
    date: str,
    selected: List[ActiveBet],
    skipped: List[Dict[str, str]],
    summary: str,
) -> None:
    """Write pre-game section to daily journal."""
    journal_path = JOURNAL_DIR / f"{date}.md"

    lines = [
        f"# NBA Betting Journal - {date}",
        "",
        "## Pre-Game Analysis",
        "",
        summary,
        "",
    ]

    if selected:
        lines.append("### Selected Bets")
        lines.append("")

        # Show total wagered if amounts are present
        total_wagered = sum(b.get("amount", 0) for b in selected)
        if total_wagered > 0:
            lines.append(f"**Total wagered: ${total_wagered:.2f}**")
            lines.append("")

        for bet in selected:
            bet_type = bet.get('bet_type', 'moneyline')
            pick = bet.get('pick', 'Unknown')
            line = bet.get('line')

            # Format the pick display based on bet type
            if bet_type == "spread" and line is not None:
                pick_display = f"{pick} {line:+.1f}"
            elif bet_type == "total" and line is not None:
                pick_display = f"{pick} {line:.1f}"
            else:
                pick_display = pick

            lines.append(f"**{bet.get('matchup', 'Unknown')}** - {bet_type.upper()}")
            lines.append(f"- Pick: {pick_display} ({bet.get('confidence', 'unknown')} confidence)")
            # Show amount if present, otherwise show units
            amount = bet.get('amount')
            if amount:
                lines.append(f"- Amount: ${amount:.2f}")
            else:
                lines.append(f"- Units: {bet.get('units', '?')}")
            lines.append(f"- Edge: {bet.get('primary_edge', 'Unknown')}")
            lines.append(f"- Reasoning: {bet.get('reasoning', 'No reasoning provided')}")
            lines.append("")
    else:
        lines.append("*No bets selected today.*")
        lines.append("")

    if skipped:
        lines.append("### Skipped Games")
        lines.append("")
        for skip in skipped:
            lines.append(f"- {skip.get('matchup', 'Unknown')}: {skip.get('reason', 'No clear edge')}")
        lines.append("")

    lines.append("---")
    lines.append("")

    write_text(journal_path, "\n".join(lines))


async def run_analyze_workflow(date: str, max_bets: int = 3, force: bool = False) -> None:
    """Run the pre-game analysis workflow."""
    # Check for existing bets on this date (before any API calls)
    active = get_active_bets()
    existing_date_bets = [b for b in active if b["date"] == date]
    if existing_date_bets and not force:
        print(f"Bets already exist for {date}. Use --force to re-analyze or run 'results' first.")
        return

    # Handle --force by reverting bankroll transactions
    bankroll = get_bankroll()
    if existing_date_bets and force:
        print(f"Removing {len(existing_date_bets)} existing bets for {date} (--force)")
        active = [b for b in active if b["date"] != date]
        # Revert bankroll transactions for this date
        bankroll = revert_bankroll_for_date(bankroll, date)
        # Save immediately so revert persists even if we exit early
        save_bankroll(bankroll)
        save_active_bets(active)

    # Load games
    games = load_games_for_date(date)
    if not games:
        print(f"No matchup files found for {date} in {OUTPUT_DIR}")
        return

    print(f"Found {len(games)} games for {date}")

    # Phase 1: Web search enrichment (saves results into game JSON files)
    print("Running web search enrichment...")
    await _enrich_games_with_search(games, date)

    # Load context
    strategy = read_text(BETS_DIR / "strategy.md")
    history = get_history()

    # Phase 2: Analyze games with concurrency limiting
    print("Analyzing games...")
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_LLM_CALLS)

    async def analyze_with_limit(game: Dict[str, Any]) -> Optional[BetRecommendation]:
        async with semaphore:
            # Prefer api_game_id from JSON, fallback to filename-based ID for legacy files
            game_id = str(game["api_game_id"]) if game.get("api_game_id") else extract_game_id(game["_file"])
            matchup_str = format_matchup_string(game["matchup"])
            return await analyze_game(game, game_id, matchup_str, strategy)

    tasks = [analyze_with_limit(game) for game in games]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    recommendations = []
    for r in results:
        if isinstance(r, Exception):
            print(f"Analysis error: {r}")
        elif r:
            recommendations.append(r)

    if not recommendations:
        print("No successful analyses. Check LLM errors above.")
        return

    print(f"Analyzed {len(recommendations)} games")

    # Synthesize
    print("Synthesizing bet selections...")
    synthesis = await synthesize_bets(
        recommendations, strategy, history["summary"], max_bets
    )

    if not synthesis:
        print("Synthesis failed. Check LLM errors above.")
        return

    # Create active bets (filter out incomplete entries)
    selected = synthesis.get("selected_bets", [])
    valid_bets = [s for s in selected if s.get("pick") and s.get("matchup")]
    new_bets = [create_active_bet(s, date) for s in valid_bets]

    if not new_bets:
        print("No bets selected by analysis.")
        write_journal_pre_game(date, [], synthesis.get("skipped", []), synthesis.get("summary", ""))
        return

    # Size bets
    print("Sizing bets...")
    sized_bets, sizing_skipped = await size_bets(
        new_bets, bankroll, strategy, history["summary"]
    )

    # Combine skipped lists for journal
    all_skipped = synthesis.get("skipped", []) + sizing_skipped

    if not sized_bets:
        print("All bets were vetoed by sizing.")
        write_journal_pre_game(date, [], all_skipped, synthesis.get("summary", ""))
        save_bankroll(bankroll)  # Save even if no bets (for force revert)
        return

    # Record bankroll transactions
    for bet in sized_bets:
        bankroll["transactions"].append({
            "date": date,
            "type": "bet",
            "amount": -bet["amount"],  # Negative = deduction
            "bet_id": bet["id"],
            "description": f"{bet['matchup']} - {bet['bet_type']} {bet['pick']}",
        })
    bankroll["current"] -= sum(b["amount"] for b in sized_bets)

    # Save everything
    save_bankroll(bankroll)
    save_active_bets(active + sized_bets)
    write_journal_pre_game(date, sized_bets, all_skipped, synthesis.get("summary", ""))

    # Print summary with amounts
    print(f"\nPlaced {len(sized_bets)} bets (${sum(b['amount'] for b in sized_bets):.2f} total):")
    for bet in sized_bets:
        bet_type = bet['bet_type']
        if bet_type == "spread" and bet.get('line') is not None:
            pick_str = f"{bet['pick']} {bet['line']:+.1f}"
        elif bet_type == "total" and bet.get('line') is not None:
            pick_str = f"{bet['pick']} {bet['line']:.1f}"
        else:
            pick_str = bet['pick']
        print(f"  {bet['matchup']}: [{bet_type.upper()}] {pick_str} - ${bet['amount']:.2f}")

    print(f"\nBankroll: ${bankroll['current']:.2f} (was ${bankroll['starting']:.2f})")
    print(f"See bets/journal/{date}.md for details")
