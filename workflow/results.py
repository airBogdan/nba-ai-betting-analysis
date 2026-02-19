"""Post-game results workflow."""

import asyncio
from typing import Any, Dict, List, Optional, Tuple

from helpers.api import get_game_by_id, get_game_player_stats, get_games_by_date
from helpers.utils import get_current_nba_season_year
from .io import (
    clear_output_dir,
    get_active_bets,
    get_dollar_pnl,
    get_history,
    get_paper_history,
    get_paper_trades,
    get_skips,
    save_active_bets,
    save_history,
    save_paper_history,
    save_paper_trades,
    save_skips_all,
    save_void,
)
from .llm import complete_json
from .prompts import REFLECT_BET_PROMPT, SYSTEM_ANALYST
from .evaluation import (
    PROP_TYPE_TO_STAT_KEY,
    _evaluate_bet,
    _evaluate_prop_bet,
    _find_player_stat,
    calculate_payout,
)
from .history import (
    update_history_with_bet,
    update_paper_history_with_trade,
)
from .game_results import (
    _format_score,
    _teams_match,
    match_bet_to_result,
    parse_game_results,
    parse_single_game_result,
)
from .journal import append_journal_post_game, _append_paper_journal_results
from .types import ActiveBet, CompletedBet, GameResult

# Limit concurrent LLM calls to avoid rate limiting
MAX_CONCURRENT_LLM_CALLS = 4






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

    # Build prop-specific context for player prop bets
    prop_context = ""
    if bet.get("bet_type") == "player_prop":
        player = bet.get("player_name", "Unknown")
        prop_type = bet.get("prop_type", "unknown")
        actual = bet.get("_actual_stat")
        actual_str = str(actual) if actual is not None else "DNP"
        prop_context = (
            f"- Player: {player}\n"
            f"- Stat Type: {prop_type}\n"
            f"- Actual {prop_type}: {actual_str}"
        )

    prompt = REFLECT_BET_PROMPT.format(
        matchup=bet["matchup"],
        bet_type=bet.get("bet_type", "moneyline"),
        pick=bet["pick"],
        line=line_str,
        confidence=bet["confidence"],
        units=bet["units"],
        reasoning=bet["reasoning"],
        primary_edge=bet["primary_edge"],
        prop_context=prop_context,
        winner=result["winner"],
        final_score=_format_score(result),
        actual_total=actual_total,
        actual_margin=actual_margin,
        outcome=outcome.upper(),
    )

    return await complete_json(prompt, system=SYSTEM_ANALYST)


async def _resolve_skips_for_date(date: str, season: int) -> None:
    """Fetch outcomes for skipped games on this date."""
    all_skips = get_skips()
    date_skips = [s for s in all_skips if s.get("date") == date and not s.get("outcome_resolved")]
    if not date_skips:
        return

    api_results = await get_games_by_date(season, date)
    all_results = parse_game_results(api_results) if api_results else []
    finished = [r for r in all_results if r["status"] == "finished"]
    if not finished:
        return

    resolved = 0
    for skip in date_skips:
        matched = None
        gid = skip.get("game_id")
        if gid:
            matched = next((r for r in finished if r["game_id"] == gid), None)
        if not matched:
            parts = skip["matchup"].split(" @ ")
            if len(parts) == 2:
                away, home = parts
                matched = next(
                    (r for r in finished if _teams_match(r["home_team"], home) and _teams_match(r["away_team"], away)),
                    None,
                )
        if matched:
            skip["winner"] = matched["winner"]
            skip["final_score"] = _format_score(matched)
            skip["actual_total"] = matched["home_score"] + matched["away_score"]
            skip["actual_margin"] = matched["home_score"] - matched["away_score"]
            skip["outcome_resolved"] = True
            resolved += 1

    if resolved:
        save_skips_all(all_skips)
        print(f"  Resolved outcomes for {resolved} skipped game(s)")


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

    # Resolve skip outcomes for all dates that have unresolved skips
    all_skips = get_skips()
    skip_dates = set(s["date"] for s in all_skips if not s.get("outcome_resolved"))
    for skip_date in sorted(skip_dates):
        await _resolve_skips_for_date(skip_date, season)

    # Resolve paper trade outcomes
    try:
        paper_trades = get_paper_trades()
        paper_dates = set(t["date"] for t in paper_trades if "result" not in t)
        for pt_date in sorted(paper_dates):
            await _resolve_paper_trades_for_date(pt_date, season)
    except Exception as e:
        print(f"Paper trade resolution failed (non-fatal): {e}")

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
    unresolved: List[ActiveBet] = []
    matched: List[Tuple[ActiveBet, GameResult, str, float]] = []  # (bet, result, outcome, profit_loss)

    # Cache box scores per game_id for player prop bets (avoid duplicate API calls)
    box_score_cache: Dict[str, Optional[list[dict]]] = {}

    for bet in date_bets:
        result = match_bet_to_result(bet, finished)
        if not result:
            print(f"  No result yet for {bet['matchup']}")
            unresolved.append(bet)
            continue

        # Player prop bets need box score data
        if bet.get("bet_type") == "player_prop":
            gid = bet["game_id"]

            # Invalid game ID — can't fetch box score
            if not gid.isdigit():
                print(f"  Void: invalid game_id {gid!r} for {bet.get('player_name')}")
                save_void(bet, f"Invalid game_id: {gid!r}")
                continue

            # Fetch box score (cache per game, preserve None vs [] distinction)
            if gid not in box_score_cache:
                box_score_cache[gid] = await get_game_player_stats(int(gid))
            box_score = box_score_cache[gid]

            if box_score is None:
                print(f"  Void: box score unavailable for game {gid}")
                save_void(bet, f"Box score unavailable for game {gid}")
                continue

            # Unsupported prop type — can't evaluate
            prop_type = bet.get("prop_type", "")
            if prop_type not in PROP_TYPE_TO_STAT_KEY:
                print(f"  Void: unsupported prop type {prop_type!r}")
                save_void(bet, f"Unsupported prop type: {prop_type!r}")
                continue

            # Check if player actually played — DNP voids the bet
            actual_stat = _find_player_stat(
                box_score, bet.get("player_name", ""), prop_type
            )
            if actual_stat is None:
                print(f"  DNP void: {bet.get('player_name')} — moving to voids.json")
                save_void(bet, f"DNP: {bet.get('player_name')} not in box score")
                continue

            outcome, profit_loss = _evaluate_prop_bet(bet, actual_stat)
            bet["_actual_stat"] = actual_stat
            matched.append((bet, result, outcome, profit_loss))
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
            structured_ref = None
            if reflection and not isinstance(reflection, Exception):
                reflection_text = reflection.get("summary", "")
                structured_ref = {
                    "edge_valid": reflection.get("edge_valid", True),
                    "missed_factors": reflection.get("missed_factors", []),
                    "process_assessment": reflection.get("process_assessment", "sound"),
                    "key_lesson": reflection.get("key_lesson", ""),
                    "summary": reflection_text,
                }

            actual_total = result["home_score"] + result["away_score"]
            actual_margin = result["home_score"] - result["away_score"]  # Positive = home win

            # Strip internal keys before creating completed bet
            clean_bet = {k: v for k, v in bet.items() if not k.startswith("_")}
            completed_bet: CompletedBet = {
                **clean_bet,
                "result": outcome,
                "winner": result["winner"],
                "final_score": _format_score(result),
                "actual_total": actual_total,
                "actual_margin": actual_margin,
                "profit_loss": profit_loss,
                "reflection": reflection_text,
            }
            # Add actual_stat for player prop bets
            if bet.get("bet_type") == "player_prop" and bet.get("_actual_stat") is not None:
                completed_bet["actual_stat"] = bet["_actual_stat"]
            if structured_ref:
                completed_bet["structured_reflection"] = structured_ref
            # Compute dollar P&L from payout
            amount = bet.get("amount")
            odds_price = bet.get("odds_price")
            if amount and odds_price:
                payout = calculate_payout(amount, odds_price, outcome)
                completed_bet["dollar_pnl"] = round(payout - amount, 2)
            completed.append(completed_bet)

    # Update history with completed bets
    if completed:
        history = get_history()
        for bet in completed:
            update_history_with_bet(history, bet)
        save_history(history)

    # Update active bets: keep bets not for this date + unresolved from this date
    other_bets = [b for b in active if b["date"] != date]
    save_active_bets(other_bets + unresolved)

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

    # Print dollar P&L
    total_pnl = get_dollar_pnl()
    print(f"Dollar P&L: ${total_pnl:+.2f}")

    if unresolved:
        print(f"{len(unresolved)} bets still pending (games not finished)")

    print(f"\nSee bets/journal/{date}.md for details")


# --- Paper trade resolution ---


async def _resolve_paper_trades_for_date(date: str, season: int) -> None:
    """Resolve paper trade outcomes for a date."""
    all_trades = get_paper_trades()
    date_trades = [t for t in all_trades if t.get("date") == date and "result" not in t]
    if not date_trades:
        return

    api_results = await get_games_by_date(season, date)
    all_results = parse_game_results(api_results) if api_results else []
    finished = [r for r in all_results if r["status"] == "finished"]
    if not finished:
        return

    resolved = 0
    paper_history = get_paper_history()

    for trade in date_trades:
        matched = None
        gid = trade.get("game_id")
        if gid:
            matched = next((r for r in finished if r["game_id"] == str(gid)), None)
        if not matched:
            parts = trade["matchup"].split(" @ ")
            if len(parts) == 2:
                away, home = parts
                matched = next(
                    (r for r in finished if _teams_match(r["home_team"], home) and _teams_match(r["away_team"], away)),
                    None,
                )
        if matched:
            outcome, profit_loss = _evaluate_bet(trade, matched)
            trade["result"] = outcome
            trade["profit_loss"] = profit_loss
            trade["winner"] = matched["winner"]
            trade["final_score"] = _format_score(matched)
            trade["actual_total"] = matched["home_score"] + matched["away_score"]
            trade["actual_margin"] = matched["home_score"] - matched["away_score"]
            update_paper_history_with_trade(paper_history, trade)
            resolved += 1

    if resolved:
        save_paper_trades(all_trades)
        save_paper_history(paper_history)
        _append_paper_journal_results(date, [t for t in date_trades if "result" in t])
        print(f"  Resolved {resolved} paper trade(s)")
