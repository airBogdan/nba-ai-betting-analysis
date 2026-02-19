"""Main analysis orchestration — search enrichment, game analysis, synthesis, and workflow."""

import asyncio
from typing import Any, Dict, List, Optional

from ..io import (
    BETS_DIR,
    get_active_bets,
    get_dollar_pnl,
    get_history,
    read_text,
    save_active_bets,
    save_skips,
)
from ..llm import complete_json
from ..paper import run_paper_trades
from ..polymarket_prices import fetch_polymarket_prices
from ..prompts import (
    ANALYZE_GAME_PROMPT,
    POLYMARKET_ODDS_SECTION,
    SYNTHESIZE_BETS_PROMPT,
    SYSTEM_ANALYST,
    compact_json,
    format_analyses_for_synthesis,
    format_history_summary,
)
from ..types import ActiveBet, BetRecommendation
from polymarket import get_polymarket_balance
from .bets import create_active_bet, write_journal_pre_game
from .gamedata import (
    MAX_CONCURRENT_LLM_CALLS,
    OUTPUT_DIR,
    _save_game_file,
    extract_game_id,
    format_matchup_string,
    load_games_for_date,
)
from .injuries import _extract_and_compute_injuries
from .props import _run_props_pipeline
from .sizing import _extract_poly_and_odds_price, size_bets


async def _enrich_games_with_search(games: List[Dict[str, Any]], date: str) -> None:
    """Run web search enrichment on games and save results to their JSON files."""
    from ..search import sanitize_label, search_enrich, search_player_news

    semaphore = asyncio.Semaphore(MAX_CONCURRENT_LLM_CALLS)

    async def enrich_one(game: Dict[str, Any]) -> None:
        matchup_str = format_matchup_string(game["matchup"])
        game_label = sanitize_label(matchup_str)
        print(f"  {matchup_str}")

        async def _do_template():
            async with semaphore:
                return await search_enrich(game, matchup_str, game_label)

        async def _do_player_news():
            async with semaphore:
                return await search_player_news(game, matchup_str)

        template_result, player_result = await asyncio.gather(
            _do_template(), _do_player_news(), return_exceptions=True
        )

        # Handle exceptions from either search
        if isinstance(template_result, Exception):
            print(f"    search error: {template_result}")
            template_result = None
        if isinstance(player_result, Exception):
            print(f"    player news error: {player_result}")
            player_result = None

        # Merge results
        parts = []
        if template_result:
            parts.append(template_result)
        if player_result:
            parts.append("### Player & Team News\n" + player_result)

        if parts:
            game["search_context"] = "\n\n".join(parts)
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

    # Strip internal/search keys and sportsbook odds from the JSON blob
    clean_data = {k: v for k, v in game_data.items()
                  if not k.startswith("_") and k not in ("search_context", "polymarket_odds", "odds")}

    # Polymarket context (all games reaching analysis have polymarket_odds)
    poly_odds = game_data.get("polymarket_odds")
    if poly_odds:
        polymarket_context = POLYMARKET_ODDS_SECTION.format(
            polymarket_json=compact_json(poly_odds)
        )
    else:
        polymarket_context = ""

    prompt = ANALYZE_GAME_PROMPT.format(
        matchup_json=compact_json(clean_data),
        search_context=search_section,
        strategy=strategy or "No strategy defined yet.",
        game_id=game_id,
        matchup=matchup_str,
        home_team=home_team,
        polymarket_context=polymarket_context,
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


async def run_analyze_workflow(date: str, max_bets: int = 4, force: bool = False, max_props: int = 4) -> None:
    """Run the pre-game analysis workflow."""
    # Check for existing bets on this date (before any API calls)
    active = get_active_bets()
    existing_date_bets = [b for b in active if b["date"] == date]
    if existing_date_bets and not force:
        print(f"Bets already exist for {date}. Use --force to re-analyze or run 'results' first.")
        return

    # Handle --force by removing existing bets for this date
    if existing_date_bets and force:
        print(f"Removing {len(existing_date_bets)} existing bets for {date} (--force)")
        active = [b for b in active if b["date"] != date]
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

    # Phase 1.5: Extract injuries from search and compute impact
    print("Computing injury impact...")
    await _extract_and_compute_injuries(games)

    # Phase 1.7: Fetch Polymarket prices (single event fetch, shared with props)
    print("Fetching Polymarket prices...")
    from polymarket_helpers.gamma import fetch_nba_events
    polymarket_events = await asyncio.to_thread(fetch_nba_events, date)
    await asyncio.to_thread(fetch_polymarket_prices, games, date, polymarket_events)
    # Drop games with no Polymarket market
    games = [g for g in games if g.get("polymarket_odds")]
    if not games:
        print("No games with Polymarket markets found. Exiting.")
        return

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

    # Build game lookup and extract Polymarket pricing for bets
    game_lookup: Dict[str, Dict[str, Any]] = {}
    for game in games:
        gid = str(game["api_game_id"]) if game.get("api_game_id") else extract_game_id(game["_file"])
        game_lookup[gid] = game

    for bet in new_bets:
        game = game_lookup.get(bet["game_id"], {})
        poly_price, odds_price = _extract_poly_and_odds_price(game, bet)
        bet["odds_price"] = odds_price
        if poly_price is not None:
            bet["poly_price"] = poly_price

    # Drop bets where no poly_price could be extracted (can't place on Polymarket)
    new_bets = [b for b in new_bets if b.get("poly_price") is not None]

    # Helper to enrich skip dicts with date/source/game_id for persistence
    matchup_to_game_id = {rec["matchup"]: rec["game_id"] for rec in recommendations}

    def _enrich_skip(skip, source):
        enriched = {
            "matchup": skip.get("matchup", "Unknown"),
            "reason": skip.get("reason", "No clear edge"),
            "date": date,
            "source": source,
        }
        gid = skip.get("game_id") or matchup_to_game_id.get(skip.get("matchup"))
        if gid:
            enriched["game_id"] = gid
        return enriched

    # Get Polymarket balance (needed for game-level and props sizing)
    print("Querying Polymarket balance...")
    balance = get_polymarket_balance()
    if balance is None:
        print("Error: Could not get Polymarket balance. Set POLYMARKET_PRIVATE_KEY and POLYMARKET_FUNDER.")
        enriched_skips = [_enrich_skip(s, "synthesis") for s in synthesis.get("skipped", [])]
        save_skips(date, enriched_skips)
        if enriched_skips:
            try:
                await run_paper_trades(enriched_skips, date, games)
            except Exception as e:
                print(f"Paper trading failed (non-fatal): {e}")
        return

    # Size game-level bets (skip sizing if none to size)
    sized_bets: List[ActiveBet] = []
    sizing_skipped: List[Dict[str, str]] = []
    if new_bets:
        print("Sizing bets...")
        sized_bets, sizing_skipped = await size_bets(
            new_bets, balance, strategy, history["summary"]
        )

    # Combine skipped lists for journal
    all_skipped = synthesis.get("skipped", []) + sizing_skipped

    # Enrich and persist skips
    enriched_skips = [_enrich_skip(s, "synthesis") for s in synthesis.get("skipped", [])]
    enriched_skips += [_enrich_skip(s, "sizing") for s in sizing_skipped]
    save_skips(date, enriched_skips)

    # Paper trade skipped games (runs independently, doesn't affect real bets)
    if enriched_skips:
        try:
            await run_paper_trades(enriched_skips, date, games)
        except Exception as e:
            print(f"Paper trading failed (non-fatal): {e}")

    # Save game-level bets and journal
    if sized_bets:
        save_active_bets(active + sized_bets)
    write_journal_pre_game(date, sized_bets, all_skipped, synthesis.get("summary", ""))

    if sized_bets:
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

        dollar_pnl = get_dollar_pnl()
        print(f"\nBalance: ${balance:.2f} | Dollar P&L: ${dollar_pnl:+.2f}")
        print(f"See bets/journal/{date}.md for details")
    elif new_bets:
        print("All bets were vetoed by sizing.")
    else:
        print("No game-level bets selected by analysis.")

    # --- Player Props Pipeline (only on games without a game-level bet) ---
    if max_props > 0:
        game_ids_with_bets = {b["game_id"] for b in sized_bets}
        try:
            await _run_props_pipeline(
                date, games, game_lookup, polymarket_events,
                strategy, history, balance, max_props, game_ids_with_bets,
            )
        except Exception as e:
            print(f"Player props pipeline failed (non-fatal): {e}")
