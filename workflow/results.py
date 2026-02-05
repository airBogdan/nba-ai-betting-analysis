"""Post-game results workflow."""

import asyncio
from typing import Any, Dict, List, Optional, Tuple

from helpers.api import get_game_by_id, get_games_by_date
from helpers.utils import get_current_nba_season_year
from .io import (
    JOURNAL_DIR,
    OUTPUT_DIR,
    append_text,
    clear_output_dir,
    get_active_bets,
    get_bankroll,
    get_history,
    save_active_bets,
    save_bankroll,
    save_history,
)
from .llm import complete_json
from .prompts import REFLECT_BET_PROMPT, SYSTEM_ANALYST
from .types import ActiveBet, Bankroll, BetHistory, CompletedBet, GameResult

# Limit concurrent LLM calls to avoid rate limiting
MAX_CONCURRENT_LLM_CALLS = 4


def parse_single_game_result(game: Dict[str, Any]) -> GameResult:
    """Parse a single API game into GameResult."""
    status_data = game.get("status", {})
    status_long = status_data.get("long", "").lower()

    # Map API status to our status
    if status_long == "finished":
        status = "finished"
    elif status_long in ("scheduled", "not started"):
        status = "scheduled"
    else:
        status = "in_progress"

    teams = game.get("teams", {})
    scores = game.get("scores", {})

    home_team = teams.get("home", {}).get("name", "")
    away_team = teams.get("visitors", {}).get("name", "")
    home_score = scores.get("home", {}).get("points") or 0
    away_score = scores.get("visitors", {}).get("points") or 0

    if home_score > away_score:
        winner = home_team
    elif away_score > home_score:
        winner = away_team
    else:
        winner = ""

    return {
        "game_id": str(game.get("id", "")),
        "home_team": home_team,
        "away_team": away_team,
        "home_score": home_score,
        "away_score": away_score,
        "winner": winner,
        "status": status,
    }


def parse_game_results(api_response: Optional[List[Any]]) -> List[GameResult]:
    """Parse API response into GameResult list."""
    if not api_response:
        return []
    return [parse_single_game_result(game) for game in api_response]


def match_bet_to_result(
    bet: ActiveBet, results: List[GameResult]
) -> Optional[GameResult]:
    """Match bet to game result by game ID or team names."""
    game_id = bet["game_id"]

    # Try exact game ID match first (for numeric API IDs)
    for r in results:
        if r["game_id"] == game_id:
            return r

    # Fallback to team name matching (for legacy bets)
    matchup_parts = bet["matchup"].split(" @ ")
    if len(matchup_parts) != 2:
        return None

    away_team, home_team = matchup_parts

    for r in results:
        # Check if teams match (allowing for slight name variations)
        if _teams_match(r["home_team"], home_team) and _teams_match(
            r["away_team"], away_team
        ):
            return r

    return None


def _categorize_edge(edge: str) -> str:
    """Normalize edge description to a category for tracking."""
    edge_lower = edge.lower()

    # Check for common edge types
    if any(w in edge_lower for w in ["home", "home court", "home advantage"]):
        return "home_court"
    if any(w in edge_lower for w in ["rest", "fatigue", "back-to-back", "b2b", "tired"]):
        return "rest_advantage"
    if any(w in edge_lower for w in ["injury", "injured", "missing", "out", "questionable"]):
        return "injury_edge"
    if any(w in edge_lower for w in ["form", "streak", "momentum", "hot", "cold", "recent"]):
        return "form_momentum"
    if any(w in edge_lower for w in ["h2h", "head-to-head", "matchup history"]):
        return "h2h_history"
    if any(w in edge_lower for w in ["rating", "net rating", "offensive", "defensive", "efficiency"]):
        return "ratings_edge"
    if any(w in edge_lower for w in ["mismatch", "size", "pace", "style"]):
        return "style_mismatch"
    if any(w in edge_lower for w in ["total", "over", "under", "scoring"]):
        return "totals_edge"

    # Default: truncate to 25 chars
    return edge[:25] if len(edge) > 25 else edge


def _teams_match(name1: str, name2: str) -> bool:
    """Check if two team names match (case-insensitive, partial match)."""
    n1 = name1.lower().strip()
    n2 = name2.lower().strip()
    if n1 == n2 or n1 in n2 or n2 in n1:
        return True
    # Handle LA/Los Angeles variations
    n1_normalized = n1.replace("los angeles", "la").replace("l.a.", "la")
    n2_normalized = n2.replace("los angeles", "la").replace("l.a.", "la")
    return n1_normalized == n2_normalized or n1_normalized in n2_normalized or n2_normalized in n1_normalized


def _format_score(result: GameResult) -> str:
    """Format score as 'Away 110 @ Home 105' style."""
    return f"{result['away_team']} {result['away_score']} @ {result['home_team']} {result['home_score']}"


def calculate_payout(amount: float, odds_price: int, result: str) -> float:
    """Calculate payout based on American odds.

    American odds:
    - Negative (e.g., -150): Bet $150 to win $100 → payout = stake * (1 + 100/150)
    - Positive (e.g., +130): Bet $100 to win $130 → payout = stake * (1 + 130/100)
    """
    if result == "push":
        return amount  # Stake returned
    if result == "loss":
        return 0.0  # Already deducted when placed

    # Win: return stake + profit
    if odds_price == 0:
        # Fallback to -110 if odds_price is invalid
        odds_price = -110
    if odds_price < 0:
        # Favorite: profit = stake * (100 / abs(odds))
        profit = amount * (100 / abs(odds_price))
    else:
        # Underdog: profit = stake * (odds / 100)
        profit = amount * (odds_price / 100)

    return amount + profit  # Stake back + profit


def update_bankroll_for_result(bet: CompletedBet, bankroll: Bankroll) -> None:
    """Update bankroll after bet result."""
    amount = bet.get("amount", 0)
    if not amount:
        return  # Legacy bet without amount

    odds_price = bet.get("odds_price", -110)  # Default to standard juice
    payout = calculate_payout(amount, odds_price, bet["result"])

    if payout > 0:
        if bet["result"] == "win":
            description = f"WIN: {bet['matchup']} (+${payout - amount:.2f})"
        else:  # push
            description = f"PUSH: {bet['matchup']}"
        bankroll["transactions"].append({
            "date": bet["date"],
            "type": "result",
            "amount": payout,
            "bet_id": bet["id"],
            "description": description,
        })
        bankroll["current"] += payout


def _evaluate_bet(bet: ActiveBet, result: GameResult) -> tuple:
    """
    Evaluate bet outcome based on bet type.
    Returns (outcome, profit_loss) tuple.
    """
    bet_type = bet.get("bet_type", "moneyline")
    units = bet["units"]

    if bet_type == "moneyline":
        # Did the picked team win?
        if _teams_match(bet["pick"], result["winner"]):
            return "win", units
        return "loss", -units

    elif bet_type == "spread":
        # Did the picked team cover the spread?
        line = bet.get("line", 0)
        # Calculate margin from perspective of picked team
        if _teams_match(bet["pick"], result["home_team"]):
            # We picked home team
            margin = result["home_score"] - result["away_score"]
        else:
            # We picked away team
            margin = result["away_score"] - result["home_score"]

        # For spread, negative line means favorite (needs to win by more than line)
        # Positive line means underdog (can lose by less than line)
        adjusted_margin = margin + line  # line is already signed correctly

        if adjusted_margin > 0:
            return "win", units
        elif adjusted_margin < 0:
            return "loss", -units
        else:
            return "push", 0.0

    elif bet_type == "total":
        # Was the actual total over/under the line?
        line = bet.get("line", 0)
        actual_total = result["home_score"] + result["away_score"]
        pick = bet["pick"].lower()

        if pick == "over":
            if actual_total > line:
                return "win", units
            elif actual_total < line:
                return "loss", -units
            else:
                return "push", 0.0
        else:  # under
            if actual_total < line:
                return "win", units
            elif actual_total > line:
                return "loss", -units
            else:
                return "push", 0.0

    # Default to moneyline logic
    if _teams_match(bet["pick"], result["winner"]):
        return "win", units
    return "loss", -units


async def reflect_on_bet(
    bet: ActiveBet, result: GameResult, outcome: str
) -> Optional[Dict[str, Any]]:
    """Generate LLM reflection on bet outcome."""
    actual_total = result["home_score"] + result["away_score"]
    actual_margin = result["home_score"] - result["away_score"]

    # Format line display
    line = bet.get("line")
    if line is not None:
        line_str = f"{line:+.1f}" if bet.get("bet_type") == "spread" else f"{line:.1f}"
    else:
        line_str = "N/A"

    prompt = REFLECT_BET_PROMPT.format(
        matchup=bet["matchup"],
        bet_type=bet.get("bet_type", "moneyline"),
        pick=bet["pick"],
        line=line_str,
        confidence=bet["confidence"],
        units=bet["units"],
        reasoning=bet["reasoning"],
        primary_edge=bet["primary_edge"],
        winner=result["winner"],
        final_score=_format_score(result),
        actual_total=actual_total,
        actual_margin=actual_margin,
        outcome=outcome.upper(),
    )

    return await complete_json(prompt, system=SYSTEM_ANALYST)


def update_history_with_bet(history: BetHistory, bet: CompletedBet) -> BetHistory:
    """Update history with a completed bet."""
    history["bets"].append(bet)

    summary = history["summary"]
    summary["total_bets"] += 1
    summary["net_units"] += bet["profit_loss"]

    # Only count units wagered for non-push bets
    if bet["result"] != "push":
        summary["total_units_wagered"] += bet["units"]

    if bet["result"] == "win":
        summary["wins"] += 1
    elif bet["result"] == "loss":
        summary["losses"] += 1
    elif bet["result"] == "push":
        summary["pushes"] = summary.get("pushes", 0) + 1

    if summary["total_bets"] > 0:
        summary["win_rate"] = round(summary["wins"] / summary["total_bets"], 3)
        if summary["total_units_wagered"] > 0:
            summary["roi"] = round(
                summary["net_units"] / summary["total_units_wagered"], 3
            )

    # Update by_confidence (skip pushes)
    if bet["result"] != "push":
        conf = bet["confidence"]
        if conf not in summary["by_confidence"]:
            summary["by_confidence"][conf] = {"wins": 0, "losses": 0, "win_rate": 0.0}
        if bet["result"] == "win":
            summary["by_confidence"][conf]["wins"] += 1
        else:
            summary["by_confidence"][conf]["losses"] += 1
        conf_total = (
            summary["by_confidence"][conf]["wins"]
            + summary["by_confidence"][conf]["losses"]
        )
        summary["by_confidence"][conf]["win_rate"] = round(
            summary["by_confidence"][conf]["wins"] / conf_total, 3
        )

    # Update by_primary_edge (normalize to categories, skip pushes)
    if bet["result"] != "push":
        edge = _categorize_edge(bet["primary_edge"])
        if edge not in summary["by_primary_edge"]:
            summary["by_primary_edge"][edge] = {"wins": 0, "losses": 0, "win_rate": 0.0}
        if bet["result"] == "win":
            summary["by_primary_edge"][edge]["wins"] += 1
        else:
            summary["by_primary_edge"][edge]["losses"] += 1
        edge_total = (
            summary["by_primary_edge"][edge]["wins"]
            + summary["by_primary_edge"][edge]["losses"]
        )
        summary["by_primary_edge"][edge]["win_rate"] = round(
            summary["by_primary_edge"][edge]["wins"] / edge_total, 3
        )

    # Update by_bet_type (skip pushes)
    if bet["result"] != "push":
        bet_type = bet.get("bet_type", "moneyline")
        if "by_bet_type" not in summary:
            summary["by_bet_type"] = {}
        if bet_type not in summary["by_bet_type"]:
            summary["by_bet_type"][bet_type] = {"wins": 0, "losses": 0, "win_rate": 0.0}
        if bet["result"] == "win":
            summary["by_bet_type"][bet_type]["wins"] += 1
        else:
            summary["by_bet_type"][bet_type]["losses"] += 1
        type_total = (
            summary["by_bet_type"][bet_type]["wins"]
            + summary["by_bet_type"][bet_type]["losses"]
        )
        summary["by_bet_type"][bet_type]["win_rate"] = round(
            summary["by_bet_type"][bet_type]["wins"] / type_total, 3
        )

    # Update streak (ignore pushes)
    recent_results = [b["result"] for b in history["bets"][-10:] if b["result"] != "push"]
    if recent_results:
        current = recent_results[-1]
        count = 1
        for r in reversed(recent_results[:-1]):
            if r == current:
                count += 1
            else:
                break
        prefix = "W" if current == "win" else "L"
        summary["current_streak"] = f"{prefix}{count}"

    return history


def append_journal_post_game(date: str, completed: List[CompletedBet]) -> None:
    """Append post-game results to journal."""
    journal_path = JOURNAL_DIR / f"{date}.md"

    # Check if results already appended (avoid duplicates on re-run)
    existing = ""
    if journal_path.exists():
        existing = journal_path.read_text()
        if "## Post-Game Results" in existing:
            print(f"Post-game results already in journal for {date}, skipping append")
            return

    lines = []
    # Add header if journal doesn't exist
    if not existing:
        lines.extend([f"# NBA Betting Journal - {date}", "", ""])

    lines.extend(["## Post-Game Results", ""])

    wins = sum(1 for b in completed if b["result"] == "win")
    losses = sum(1 for b in completed if b["result"] == "loss")
    pushes = sum(1 for b in completed if b["result"] == "push")
    net = sum(b["profit_loss"] for b in completed)

    if pushes > 0:
        record_str = f"{wins}-{losses}-{pushes}"
    else:
        record_str = f"{wins}-{losses}"
    lines.append(f"**Record: {record_str} | Net: {net:+.1f} units**")
    lines.append("")

    for bet in completed:
        bet_type = bet.get("bet_type", "moneyline")
        pick = bet["pick"]
        line = bet.get("line")

        # Format pick display
        if bet_type == "spread" and line is not None:
            pick_display = f"{pick} {line:+.1f}"
        elif bet_type == "total" and line is not None:
            pick_display = f"{pick} {line:.1f}"
        else:
            pick_display = pick

        emoji = "+" if bet["result"] == "win" else ("-" if bet["result"] == "loss" else "=")
        result_str = bet["result"].upper()
        if bet["result"] == "push":
            profit_str = "push"
        else:
            profit_str = f"{emoji}{abs(bet['profit_loss']):.1f}u"

        lines.append(f"### {bet['matchup']} - {bet_type.upper()}")
        lines.append(f"- Pick: {pick_display}")
        lines.append(f"- Result: **{result_str}** ({profit_str})")
        lines.append(f"- Final: {bet['final_score']}")
        if bet_type == "total":
            lines.append(f"- Actual Total: {bet.get('actual_total', 'N/A')}")
        lines.append(f"- Winner: {bet['winner']}")
        if bet["reflection"]:
            lines.append(f"- Reflection: {bet['reflection']}")
        lines.append("")

    append_text(journal_path, "\n".join(lines))


async def run_results_workflow(date: Optional[str] = None) -> None:
    """Run the post-game results workflow.

    Args:
        date: Optional date in YYYY-MM-DD format. If not provided, processes all active bets.
    """
    # Get season
    season = get_current_nba_season_year()
    if not season:
        print("Could not determine current NBA season")
        return

    # Load active bets
    active = get_active_bets()
    if not active:
        print("No active bets")
        return

    # Determine which dates to process
    if date:
        dates_to_process = [date]
    else:
        dates_to_process = sorted(set(b["date"] for b in active))
        print(f"Found active bets for {len(dates_to_process)} date(s): {', '.join(dates_to_process)}")

    # Process each date
    for process_date in dates_to_process:
        await _process_results_for_date(process_date, season)

    # Clean up output directory once after all processing
    clear_output_dir()


async def _process_results_for_date(date: str, season: int) -> None:
    """Process results for a single date."""
    # Re-read active bets (may have been updated by previous date)
    active = get_active_bets()
    date_bets = [b for b in active if b["date"] == date]

    if not date_bets:
        print(f"\nNo active bets for {date}")
        return

    # Separate bets by ID type (numeric API IDs vs legacy filename-based IDs)
    numeric_id_bets = []
    legacy_bets = []
    for bet in date_bets:
        if bet["game_id"].isdigit():
            numeric_id_bets.append(bet)
        else:
            legacy_bets.append(bet)

    print(f"\nFetching results for {date}...")
    results: List[GameResult] = []
    seen_game_ids: set[str] = set()

    # Fetch games by ID for new bets (more efficient - only fetch what we need)
    if numeric_id_bets:
        unique_game_ids = set(bet["game_id"] for bet in numeric_id_bets)
        print(f"  Fetching {len(unique_game_ids)} games by ID...")
        for game_id in unique_game_ids:
            game = await get_game_by_id(int(game_id))
            if game:
                result = parse_single_game_result(game)
                results.append(result)
                seen_game_ids.add(result["game_id"])

    # Fallback: fetch all games by date for legacy bets (avoid duplicates)
    if legacy_bets:
        print(f"  Fetching all games for date (legacy bets)...")
        api_results = await get_games_by_date(season, date)
        for result in parse_game_results(api_results):
            if result["game_id"] not in seen_game_ids:
                results.append(result)
                seen_game_ids.add(result["game_id"])

    # Filter to finished games
    finished = [r for r in results if r["status"] == "finished"]

    if not finished:
        in_progress = [r for r in results if r["status"] == "in_progress"]
        scheduled = [r for r in results if r["status"] == "scheduled"]
        print(f"No finished games for {date}")
        if in_progress:
            print(f"  {len(in_progress)} games in progress")
        if scheduled:
            print(f"  {len(scheduled)} games scheduled")
        return

    print(f"Found {len(finished)} finished games")
    print(f"Processing {len(date_bets)} bets...")

    # First pass: match bets to results and determine outcomes
    history = get_history()
    unresolved: List[ActiveBet] = []
    matched: List[Tuple[ActiveBet, GameResult, str, float]] = []  # (bet, result, outcome, profit_loss)

    for bet in date_bets:
        result = match_bet_to_result(bet, finished)
        if not result:
            print(f"  No result yet for {bet['matchup']}")
            unresolved.append(bet)
            continue

        # Determine outcome based on bet type
        outcome, profit_loss = _evaluate_bet(bet, result)
        matched.append((bet, result, outcome, profit_loss))

    # Second pass: get reflections with concurrency limiting
    completed: List[CompletedBet] = []
    if matched:
        print(f"  Reflecting on {len(matched)} bets...")
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_LLM_CALLS)

        async def reflect_with_limit(bet: ActiveBet, result: GameResult, outcome: str):
            async with semaphore:
                return await reflect_on_bet(bet, result, outcome)

        reflection_tasks = [
            reflect_with_limit(bet, result, outcome)
            for bet, result, outcome, _ in matched
        ]
        reflections = await asyncio.gather(*reflection_tasks, return_exceptions=True)

        # Create completed bets
        for (bet, result, outcome, profit_loss), reflection in zip(matched, reflections):
            reflection_text = ""
            if reflection and not isinstance(reflection, Exception):
                reflection_text = reflection.get("summary", "")

            actual_total = result["home_score"] + result["away_score"]
            actual_margin = result["home_score"] - result["away_score"]  # Positive = home win

            completed_bet: CompletedBet = {
                **bet,
                "result": outcome,
                "winner": result["winner"],
                "final_score": _format_score(result),
                "actual_total": actual_total,
                "actual_margin": actual_margin,
                "profit_loss": profit_loss,
                "reflection": reflection_text,
            }
            completed.append(completed_bet)
            history = update_history_with_bet(history, completed_bet)

    # Update bankroll for completed bets
    bankroll = get_bankroll()
    for completed_bet in completed:
        update_bankroll_for_result(completed_bet, bankroll)
    save_bankroll(bankroll)

    # Update files
    # Keep bets that weren't for this date, plus unresolved bets from this date
    other_bets = [b for b in active if b["date"] != date]
    save_active_bets(other_bets + unresolved)
    save_history(history)

    # Append to journal
    if completed:
        append_journal_post_game(date, completed)

    # Print summary
    wins = sum(1 for b in completed if b["result"] == "win")
    losses = sum(1 for b in completed if b["result"] == "loss")
    pushes = sum(1 for b in completed if b["result"] == "push")
    net = sum(b["profit_loss"] for b in completed)
    if pushes > 0:
        print(f"\nResults: {wins}-{losses}-{pushes}, {net:+.1f} units")
    else:
        print(f"\nResults: {wins}-{losses}, {net:+.1f} units")

    # Print bankroll summary
    print(f"Bankroll: ${bankroll['current']:.2f}")

    if unresolved:
        print(f"{len(unresolved)} bets still pending (games not finished)")

    print(f"\nSee bets/journal/{date}.md for details")
