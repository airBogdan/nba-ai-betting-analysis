"""Player props analysis and pipeline."""

import asyncio
import json
from typing import Any, Dict, List, Optional

from ..io import append_text, get_active_bets, read_text, save_active_bets, write_text, JOURNAL_DIR
from ..llm import complete_json
from ..names import names_match, normalize_name
from ..polymarket_prices import extract_poly_price_for_prop, fetch_polymarket_player_props
from ..prompts import (
    ANALYZE_PLAYER_PROPS_PROMPT,
    SYNTHESIZE_PLAYER_PROPS_PROMPT,
    SYSTEM_PROPS_ANALYST,
    compact_json,
    format_history_summary,
)
from polymarket_helpers.odds import poly_price_to_american
from .bets import create_prop_bet
from .gamedata import MAX_CONCURRENT_LLM_CALLS, format_matchup_string, load_props_for_date
from .sizing import size_bets


async def analyze_player_props(
    props_data: Dict[str, Any],
    prop_markets: list[dict],
    game_id: str,
    matchup_str: str,
    strategy: Optional[str],
    search_context: Optional[str],
    props_search_context: Optional[str],
) -> Optional[dict]:
    """Analyze player props for a single game with the LLM."""
    # Team names from props data (team1 = home per main.py convention)
    home_team = props_data.get("home_team", props_data.get("team1", "Home"))
    team1 = props_data.get("team1", "")
    team2 = props_data.get("team2", "")
    away_team = team2 if team1 == home_team else team1

    # Only send stats for players that have prop markets (reduce noise)
    prop_names = [m.get("player_name", "") for m in prop_markets]

    def _has_prop(player: dict) -> bool:
        return any(names_match(player.get("name", ""), pn) for pn in prop_names)

    home_players = [p for p in props_data.get("team1_players", []) if _has_prop(p)]
    away_players = [p for p in props_data.get("team2_players", []) if _has_prop(p)]

    prompt = ANALYZE_PLAYER_PROPS_PROMPT.format(
        matchup=matchup_str,
        game_id=game_id,
        home_team=home_team,
        away_team=away_team,
        home_players_json=compact_json(home_players),
        away_players_json=compact_json(away_players),
        prop_markets_json=compact_json(prop_markets),
        search_context=search_context or "No search context available.",
        props_search_context=props_search_context or "No props-specific context available.",
        strategy=strategy or "No strategy defined yet.",
    )

    result = await complete_json(prompt, system=SYSTEM_PROPS_ANALYST)
    if result:
        result["game_id"] = game_id
        result["matchup"] = matchup_str
    return result


async def synthesize_player_props(
    recommendations: list[dict],
    strategy: Optional[str],
    history_summary: Dict[str, Any],
    max_props: int,
) -> Optional[dict]:
    """Synthesize prop recommendations into final selections."""
    prompt = SYNTHESIZE_PLAYER_PROPS_PROMPT.format(
        max_props=max_props,
        recommendations_json=json.dumps(recommendations, indent=2),
        strategy=strategy or "No strategy defined yet.",
        history_summary=format_history_summary(history_summary),
    )

    return await complete_json(prompt, system=SYSTEM_PROPS_ANALYST)


async def _run_props_pipeline(
    date: str,
    games: List[Dict[str, Any]],
    game_lookup: Dict[str, Dict[str, Any]],
    polymarket_events: list[dict],
    strategy: Optional[str],
    history: dict,
    balance: float,
    max_props: int,
    exclude_game_ids: set[str] | None = None,
) -> None:
    """Run the player props analysis pipeline.

    Args:
        exclude_game_ids: Game IDs that already have game-level bets.
            Props on these games are skipped to avoid correlated exposure.
    """
    from ..search import search_player_props

    # 1. Load props data from output/props_*.json
    props_data_list = load_props_for_date(date)
    if not props_data_list:
        print("\nNo props data files found, skipping player props.")
        return

    # 2. Fetch prop markets from pre-fetched events
    print("\nFetching player prop markets...")
    prop_markets = await asyncio.to_thread(
        fetch_polymarket_player_props, games, date, polymarket_events
    )
    if not prop_markets:
        print("No player prop markets available.")
        return

    # Exclude games that already have game-level bets (avoid correlated exposure)
    if exclude_game_ids:
        excluded = {gid for gid in prop_markets if gid in exclude_game_ids}
        if excluded:
            prop_markets = {gid: m for gid, m in prop_markets.items() if gid not in exclude_game_ids}
            print(f"Excluding {len(excluded)} game(s) with game-level bets from props")
        if not prop_markets:
            print("No prop markets remaining after excluding games with bets.")
            return

    total_props = sum(len(v) for v in prop_markets.values())
    print(f"Found {total_props} prop markets across {len(prop_markets)} games")

    # Build props_data lookup by game_id
    props_by_game: Dict[str, Dict[str, Any]] = {}
    for pd in props_data_list:
        gid = str(pd.get("api_game_id", ""))
        if gid:
            props_by_game[gid] = pd

    # 3. Props-specific Perplexity search per game (concurrent)
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_LLM_CALLS)

    async def search_props_for_game(game_id: str, markets: list[dict]) -> tuple[str, Optional[str]]:
        game = game_lookup.get(game_id, {})
        matchup = game.get("matchup", {})
        matchup_str = format_matchup_string(matchup) if matchup else "Unknown"
        async with semaphore:
            result = await search_player_props(matchup_str, markets)
        return game_id, result

    print("Running props-specific search...")
    search_tasks = [
        search_props_for_game(gid, markets)
        for gid, markets in prop_markets.items()
    ]
    search_results_raw = await asyncio.gather(*search_tasks, return_exceptions=True)

    props_search: Dict[str, Optional[str]] = {}
    for r in search_results_raw:
        if isinstance(r, Exception):
            print(f"  Props search error: {r}")
        else:
            gid, ctx = r
            props_search[gid] = ctx

    # 4. Analyze player props per game (concurrent)
    print("Analyzing player props...")

    async def analyze_props_for_game(game_id: str) -> Optional[dict]:
        pd = props_by_game.get(game_id)
        if not pd:
            return None
        markets = prop_markets.get(game_id, [])
        if not markets:
            return None
        game = game_lookup.get(game_id, {})
        matchup = game.get("matchup", {})
        matchup_str = format_matchup_string(matchup) if matchup else "Unknown"
        search_ctx = game.get("search_context")
        props_ctx = props_search.get(game_id)
        async with semaphore:
            return await analyze_player_props(
                pd, markets, game_id, matchup_str, strategy, search_ctx, props_ctx
            )

    analysis_tasks = [analyze_props_for_game(gid) for gid in prop_markets]
    analysis_results = await asyncio.gather(*analysis_tasks, return_exceptions=True)

    prop_recommendations = []
    for r in analysis_results:
        if isinstance(r, Exception):
            print(f"  Props analysis error: {r}")
        elif r and r.get("prop_recommendations"):
            prop_recommendations.append(r)

    if not prop_recommendations:
        print("No prop recommendations from analysis.")
        return

    total_recs = sum(len(r.get("prop_recommendations", [])) for r in prop_recommendations)
    print(f"Got {total_recs} prop recommendations across {len(prop_recommendations)} games")

    # 5. Synthesize across games
    print("Synthesizing prop selections...")
    synthesis = await synthesize_player_props(
        prop_recommendations, strategy, history["summary"], max_props
    )
    if not synthesis:
        print("Props synthesis failed.")
        return

    selected = synthesis.get("selected_props", [])
    if not selected:
        print("No props selected.")
        return

    # Build lookup from original recommendations to recover authoritative game_id/matchup
    # (don't trust LLM to transcribe these correctly)
    _prop_origin: Dict[tuple, tuple] = {}  # (norm_name, prop_type, line) -> (game_id, matchup)
    for rec in prop_recommendations:
        gid = rec.get("game_id", "")
        mup = rec.get("matchup", "")
        for p in rec.get("prop_recommendations", []):
            key = (normalize_name(p.get("player_name", "")), p.get("prop_type", ""), p.get("line"))
            _prop_origin[key] = (gid, mup)

    # 6. Create prop bets and attach Polymarket prices
    prop_bets = []
    for sel in selected:
        # Recover game_id and matchup from original recommendations
        lookup_key = (normalize_name(sel.get("player_name", "")), sel.get("prop_type", ""), sel.get("line"))
        origin = _prop_origin.get(lookup_key)
        if origin:
            sel["game_id"] = origin[0]
            sel["matchup"] = origin[1]

        bet = create_prop_bet(sel, date)
        if bet is None:
            continue
        game_id = bet["game_id"]
        markets = prop_markets.get(game_id, [])
        poly_price = extract_poly_price_for_prop(
            markets, bet.get("prop_type", ""), bet.get("player_name", ""),
            bet.get("line"), bet["pick"],
        )
        if poly_price is not None:
            bet["poly_price"] = poly_price
            bet["odds_price"] = poly_price_to_american(poly_price)
            prop_bets.append(bet)
        else:
            print(f"  Dropping prop (no Polymarket price): {bet.get('player_name')} {bet.get('prop_type')}")

    if not prop_bets:
        print("No placeable prop bets (all missing Polymarket prices).")
        return

    # 7. Size prop bets (reuses existing sizing — exposure includes game-level bets)
    print("Sizing prop bets...")
    sized_props, props_skipped = await size_bets(
        prop_bets, balance, strategy, history["summary"]
    )

    if not sized_props:
        print("All prop bets vetoed by sizing.")
        return

    # 8. Save prop bets to active.json
    current_active = get_active_bets()
    save_active_bets(current_active + sized_props)

    # Print summary
    print(f"\nPlaced {len(sized_props)} prop bets (${sum(b['amount'] for b in sized_props):.2f} total):")
    for bet in sized_props:
        print(f"  {bet['matchup']}: {bet.get('player_name', '?')} {bet.get('prop_type', '?')} "
              f"{bet['pick']} {bet.get('line', '?')} - ${bet['amount']:.2f}")

    # Append prop bets to pre-game journal
    journal_path = JOURNAL_DIR / f"{date}.md"
    lines = ["### Player Prop Bets", ""]
    total_wagered = sum(b.get("amount", 0) for b in sized_props)
    if total_wagered > 0:
        lines.append(f"**Total wagered: ${total_wagered:.2f}**")
        lines.append("")
    for bet in sized_props:
        player = bet.get("player_name", "?")
        prop = bet.get("prop_type", "?")
        pick = bet["pick"]
        line = bet.get("line")
        pick_display = f"{player} {prop} {pick} {line}" if line else f"{player} {prop} {pick}"
        lines.append(f"**{bet.get('matchup', 'Unknown')}** - PLAYER_PROP")
        lines.append(f"- Pick: {pick_display} ({bet.get('confidence', 'unknown')} confidence)")
        amount = bet.get("amount")
        if amount:
            lines.append(f"- Amount: ${amount:.2f}")
        else:
            lines.append(f"- Units: {bet.get('units', '?')}")
        lines.append(f"- Edge: {bet.get('primary_edge', 'Unknown')}")
        lines.append(f"- Reasoning: {bet.get('reasoning', 'No reasoning provided')}")
        lines.append("")
    # Insert before the --- separator so props appear inside pre-game section
    content = read_text(journal_path)
    props_block = "\n".join(lines)
    if content:
        stripped = content.rstrip()
        if stripped.endswith("---"):
            base = stripped[:-3].rstrip()
            write_text(journal_path, base + "\n\n" + props_block + "---\n")
        else:
            append_text(journal_path, "\n" + props_block)
    else:
        append_text(journal_path, props_block)
