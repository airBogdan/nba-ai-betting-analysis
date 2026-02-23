"""Player props analysis and pipeline."""

import asyncio
import json
from typing import Any, Dict, List, Optional

INITIAL_PROPS_STRATEGY = """# Player Props Betting Strategy

## Core Principles
- Only bet props where your projection meaningfully differs from the line
- Focus on players with consistent minutes and usage patterns
- Treat each stat type differently — points, rebounds, and assists have distinct variance profiles

## Stat-Specific Guidance
- **Points**: Highest volume but most variable. Prefer overs on high-usage players in favorable matchups
- **Rebounds**: More matchup-dependent (opponent pace, size). Centers against small-ball lineups are prime targets
- **Assists**: Lowest variance for primary playmakers. Look for assists overs against poor perimeter defense

## Key Factors to Weight
- Season average vs line — how far off is the line from the player's mean?
- Recent form (last 5-10 games) — trending above or below season average?
- Matchup defense — opponent's ranking in allowing that stat category
- Minutes consistency — avoid players with volatile minute distributions
- Home/away splits — some players perform significantly different by venue
- Pace factor — high-pace games inflate counting stats across the board

## What to Avoid
- Players returning from injury or on minutes restrictions
- Lines already sharp to the season average (no edge)
- High game-to-game variance players without a clear situational edge
- Correlated props (e.g. two players on the same team both over points)

## Confidence Guidelines
- **High confidence (2 units)**: Projection 15%+ above/below line with strong matchup support
- **Medium confidence (1 unit)**: Projection 10%+ off line with supporting factors
- **Low confidence (0.5 units)**: Slight edge, worth small position

## Notes
- Strategy will be updated as player prop betting history accumulates

## Change Log
"""

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


async def _fetch_and_filter_prop_markets(
    games: List[Dict[str, Any]],
    date: str,
    polymarket_events: list[dict],
    exclude_game_ids: set[str] | None,
) -> Optional[Dict[str, list]]:
    """Fetch prop markets and exclude games with game-level bets."""
    print("\nFetching player prop markets...")
    prop_markets = await asyncio.to_thread(
        fetch_polymarket_player_props, games, date, polymarket_events
    )
    if not prop_markets:
        print("No player prop markets available.")
        return None

    if exclude_game_ids:
        excluded = {gid for gid in prop_markets if gid in exclude_game_ids}
        if excluded:
            prop_markets = {gid: m for gid, m in prop_markets.items() if gid not in exclude_game_ids}
            print(f"Excluding {len(excluded)} game(s) with game-level bets from props")
        if not prop_markets:
            print("No prop markets remaining after excluding games with bets.")
            return None

    total_props = sum(len(v) for v in prop_markets.values())
    print(f"Found {total_props} prop markets across {len(prop_markets)} games")
    return prop_markets


async def _search_props(
    prop_markets: Dict[str, list],
    game_lookup: Dict[str, Dict[str, Any]],
    semaphore: asyncio.Semaphore,
) -> Dict[str, Optional[str]]:
    """Concurrent Perplexity search per game for props context."""
    from ..search import search_player_props

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
    return props_search


async def _analyze_props(
    prop_markets: Dict[str, list],
    props_by_game: Dict[str, Dict[str, Any]],
    game_lookup: Dict[str, Dict[str, Any]],
    props_search: Dict[str, Optional[str]],
    strategy: Optional[str],
    semaphore: asyncio.Semaphore,
) -> Optional[List[dict]]:
    """Concurrent LLM analysis per game, returns recommendations or None."""
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
        return None

    total_recs = sum(len(r.get("prop_recommendations", [])) for r in prop_recommendations)
    print(f"Got {total_recs} prop recommendations across {len(prop_recommendations)} games")
    return prop_recommendations


def _create_and_price_prop_bets(
    selected: list[dict],
    prop_recommendations: List[dict],
    prop_markets: Dict[str, list],
    date: str,
) -> List[dict]:
    """Match origins, create bets, and attach Polymarket prices."""
    _prop_origin: Dict[tuple, tuple] = {}
    for rec in prop_recommendations:
        gid = rec.get("game_id", "")
        mup = rec.get("matchup", "")
        for p in rec.get("prop_recommendations", []):
            key = (normalize_name(p.get("player_name", "")), p.get("prop_type", ""), p.get("line"))
            _prop_origin[key] = (gid, mup)

    prop_bets = []
    for sel in selected:
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

    return prop_bets


def _save_and_journal_props(sized_props: List[dict], date: str) -> None:
    """Save prop bets to active.json, print summary, and write journal."""
    current_active = get_active_bets()
    save_active_bets(current_active + sized_props)

    print(f"\nPlaced {len(sized_props)} prop bets (${sum(b['amount'] for b in sized_props):.2f} total):")
    for bet in sized_props:
        print(f"  {bet['matchup']}: {bet.get('player_name', '?')} {bet.get('prop_type', '?')} "
              f"{bet['pick']} {bet.get('line', '?')} - ${bet['amount']:.2f}")

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
    # 1. Load props data
    props_data_list = load_props_for_date(date)
    if not props_data_list:
        print("\nNo props data files found, skipping player props.")
        return

    # 2. Fetch and filter prop markets
    prop_markets = await _fetch_and_filter_prop_markets(games, date, polymarket_events, exclude_game_ids)
    if not prop_markets:
        return

    props_by_game: Dict[str, Dict[str, Any]] = {}
    for pd in props_data_list:
        gid = str(pd.get("api_game_id", ""))
        if gid:
            props_by_game[gid] = pd

    # 3. Search and analyze
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_LLM_CALLS)
    props_search = await _search_props(prop_markets, game_lookup, semaphore)
    prop_recommendations = await _analyze_props(
        prop_markets, props_by_game, game_lookup, props_search, strategy, semaphore
    )
    if not prop_recommendations:
        return

    # 4. Synthesize
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

    # 5. Create and price bets
    prop_bets = _create_and_price_prop_bets(selected, prop_recommendations, prop_markets, date)
    if not prop_bets:
        print("No placeable prop bets (all missing Polymarket prices).")
        return

    # 6. Size
    print("Sizing prop bets...")
    sized_props, props_skipped = await size_bets(
        prop_bets, balance, strategy, history["summary"]
    )
    if not sized_props:
        print("All prop bets vetoed by sizing.")
        return

    # 7. Save and journal
    _save_and_journal_props(sized_props, date)
