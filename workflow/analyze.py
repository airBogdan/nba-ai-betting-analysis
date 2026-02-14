"""Pre-game analysis workflow."""

import asyncio
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .io import (
    BETS_DIR,
    JOURNAL_DIR,
    get_active_bets,
    get_history,
    read_text,
    save_active_bets,
    write_text,
)
from .llm import complete_json
from .polymarket_prices import extract_poly_price_for_bet, fetch_polymarket_prices
from .prompts import (
    ANALYZE_GAME_PROMPT,
    EXTRACT_INJURIES_PROMPT,
    POLYMARKET_ODDS_SECTION,
    SIZING_PROMPT,
    SYNTHESIZE_BETS_PROMPT,
    SYSTEM_ANALYST,
    SYSTEM_SIZING,
    compact_json,
    format_analyses_for_synthesis,
    format_history_summary,
)
from polymarket import get_polymarket_balance
from polymarket_helpers.odds import poly_price_to_american
from .db import get_dollar_pnl, get_open_exposure
from .types import ActiveBet, BetRecommendation, SelectedBet

# Kelly Criterion parameters
CONFIDENCE_WIN_PROB = {"high": 0.65, "medium": 0.57, "low": 0.54}
KELLY_FRACTION = 0.5
KELLY_MAX_BET_FRACTION = 0.03  # 3% of available balance per bet

# Injury impact parameters
INJURY_REPLACEMENT_FACTOR = 0.55  # Replacement players recover ~55% of missing PPG
HAIKU_MODEL = "anthropic/claude-haiku-4.5"

# Name normalization
_SUFFIXES = re.compile(r"\s+(jr\.?|sr\.?|ii|iii|iv)$", re.IGNORECASE)


def _normalize_name(name: str) -> str:
    """Normalize a player name for comparison."""
    name = name.strip().lower()
    name = _SUFFIXES.sub("", name)
    # Remove periods (e.g., "P.J." → "pj")
    name = name.replace(".", "")
    return name


def _names_match(name_a: str, name_b: str) -> bool:
    """Check if two player names refer to the same person.

    Handles: exact match, suffix stripping, initial matching (e.g., "C. Coward" → "Cedric Coward").
    """
    a = _normalize_name(name_a)
    b = _normalize_name(name_b)
    if a == b:
        return True

    # Initial matching: "k knueppel" matches "kyle knueppel"
    parts_a = a.split()
    parts_b = b.split()
    if len(parts_a) >= 2 and len(parts_b) >= 2 and parts_a[-1] == parts_b[-1]:
        # Last names match — check if first name is an initial
        if len(parts_a[0]) == 1 and parts_b[0].startswith(parts_a[0]):
            return True
        if len(parts_b[0]) == 1 and parts_a[0].startswith(parts_b[0]):
            return True
    return False


async def _extract_injuries_from_search(
    search_context: str, team1: str, team2: str
) -> List[Dict[str, str]]:
    """Extract structured injury data from search context using Haiku."""
    prompt = EXTRACT_INJURIES_PROMPT.format(
        team1=team1, team2=team2, search_context=search_context
    )
    result = await complete_json(prompt, model=HAIKU_MODEL, temperature=0.0)
    if not isinstance(result, list):
        return []
    # Validate entries
    valid = []
    for entry in result:
        if (
            isinstance(entry, dict)
            and entry.get("player")
            and entry.get("team")
            and entry.get("status") in ("Out", "Doubtful")
        ):
            valid.append(entry)
    return valid


def compute_injury_impact(
    extracted_injuries: List[Dict[str, str]],
    team1_name: str,
    team2_name: str,
    team1_rotation: List[Dict[str, Any]],
    team2_rotation: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Compute injury impact by cross-referencing extracted injuries with rotation.

    Returns None if no matched out players.
    """
    def _team_matches(inj_team: str, team_name: str) -> bool:
        a = inj_team.lower().strip()
        b = team_name.lower().strip()
        return a == b or a in b or b in a

    def _match_team(injuries, team_name, rotation):
        out_players = []
        for inj in injuries:
            if not _team_matches(inj["team"], team_name):
                continue
            for player in rotation:
                if _names_match(inj["player"], player["name"]):
                    out_players.append({
                        "name": player["name"],
                        "ppg": player["ppg"],
                        "status": inj["status"],
                    })
                    break
        return out_players

    t1_out = _match_team(extracted_injuries, team1_name, team1_rotation)
    t2_out = _match_team(extracted_injuries, team2_name, team2_rotation)

    if not t1_out and not t2_out:
        return None

    t1_missing = sum(p["ppg"] for p in t1_out)
    t2_missing = sum(p["ppg"] for p in t2_out)
    t1_adj_loss = round(t1_missing * (1 - INJURY_REPLACEMENT_FACTOR), 1)
    t2_adj_loss = round(t2_missing * (1 - INJURY_REPLACEMENT_FACTOR), 1)

    return {
        "team1": {
            "out_players": t1_out,
            "missing_ppg": round(t1_missing, 1),
            "adjusted_ppg_loss": t1_adj_loss,
        },
        "team2": {
            "out_players": t2_out,
            "missing_ppg": round(t2_missing, 1),
            "adjusted_ppg_loss": t2_adj_loss,
        },
        "total_reduction": round(t1_adj_loss + t2_adj_loss, 1),
        "missing_ppg_diff": round(t2_adj_loss - t1_adj_loss, 1),
    }


def _american_odds_to_decimal(odds: int) -> float:
    """Convert American odds to decimal odds (payout per $1 wagered)."""
    if odds < 0:
        return 1 + 100 / abs(odds)
    return 1 + odds / 100


def _half_kelly_amount(odds_price: int, confidence: str, available: float) -> float:
    """Compute Half Kelly bet amount. Returns 0 if no edge."""
    p = CONFIDENCE_WIN_PROB.get(confidence, 0.54)
    decimal_odds = _american_odds_to_decimal(odds_price)
    b = decimal_odds - 1
    if b <= 0:
        return 0.0
    kelly = (b * p - (1 - p)) / b
    if kelly <= 0:
        return 0.0
    fraction = min(kelly * KELLY_FRACTION, KELLY_MAX_BET_FRACTION)
    return round(fraction * available, 2)

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
    from .search import sanitize_label, search_enrich, search_player_news

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


async def _extract_and_compute_injuries(games: List[Dict[str, Any]]) -> None:
    """Extract injuries from search context and compute impact for each game."""
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_LLM_CALLS)

    async def process_one(game: Dict[str, Any]) -> None:
        matchup = game.get("matchup", {})
        team1 = matchup.get("team1", "")
        team2 = matchup.get("team2", "")
        if not team1 or not team2:
            return

        # Extract from search context via Haiku
        search_context = game.get("search_context")
        extracted: List[Dict[str, str]] = []
        if search_context:
            async with semaphore:
                extracted = await _extract_injuries_from_search(search_context, team1, team2)

        # Merge with API injuries data (deduplicate by player name)
        seen_players = {_normalize_name(e["player"]) for e in extracted}
        for team_key, team_name in [("team1", team1), ("team2", team2)]:
            api_injuries = game.get("players", {}).get(team_key, {}).get("injuries", [])
            for inj in api_injuries:
                if inj.get("status") not in ("Out", "Doubtful"):
                    continue
                norm = _normalize_name(inj.get("player", ""))
                if norm and norm not in seen_players:
                    extracted.append({
                        "team": team_name,
                        "player": inj["player"],
                        "status": inj["status"],
                    })
                    seen_players.add(norm)

        if not extracted:
            return

        team1_rotation = game.get("players", {}).get("team1", {}).get("rotation", [])
        team2_rotation = game.get("players", {}).get("team2", {}).get("rotation", [])

        impact = compute_injury_impact(extracted, team1, team2, team1_rotation, team2_rotation)
        if impact:
            game["injury_impact"] = impact
            # Add injury_adjusted_total to totals_analysis
            totals = game.get("totals_analysis", {})
            expected_total = totals.get("expected_total")
            if expected_total is not None:
                game.setdefault("totals_analysis", {})["injury_adjusted_total"] = round(
                    expected_total - impact["total_reduction"], 1
                )
            _save_game_file(game)
            t1_loss = impact["team1"]["adjusted_ppg_loss"]
            t2_loss = impact["team2"]["adjusted_ppg_loss"]
            matchup_str = format_matchup_string(matchup)
            print(f"  {matchup_str}: injury impact -{impact['total_reduction']} pts "
                  f"({team1} -{t1_loss}, {team2} -{t2_loss})")

    tasks = [process_one(game) for game in games]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for r in results:
        if isinstance(r, Exception):
            print(f"Injury extraction error: {r}")


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


def _extract_poly_and_odds_price(
    game_data: Dict[str, Any], bet: ActiveBet
) -> tuple:
    """Get Polymarket price for a bet, derive odds_price from it.

    Returns (poly_price, odds_price). poly_price is None if the bet's
    market isn't available on Polymarket.
    """
    poly_price = extract_poly_price_for_bet(
        game_data, bet["bet_type"], bet["pick"], bet.get("line")
    )
    if poly_price is not None:
        return poly_price, poly_price_to_american(poly_price)
    return None, -110


def _fallback_sizing(bets: List[ActiveBet], available: float) -> List[ActiveBet]:
    """Fallback sizing using Half Kelly Criterion."""
    sized = []
    for bet in bets:
        amount = _half_kelly_amount(
            bet.get("odds_price", -110), bet["confidence"], available
        )
        if amount > 0:
            bet["amount"] = amount
            sized.append(bet)
    return sized


async def size_bets(
    proposed_bets: List[ActiveBet],
    balance: float,
    strategy: Optional[str],
    history_summary: Dict[str, Any],
) -> Tuple[List[ActiveBet], List[Dict[str, str]]]:
    """Size bets using LLM. Returns (sized_bets, sizing_skipped)."""
    exposure = get_open_exposure()
    available = balance - exposure
    dollar_pnl = get_dollar_pnl()

    prompt = SIZING_PROMPT.format(
        balance=balance,
        exposure=exposure,
        available=available,
        dollar_pnl=dollar_pnl,
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
                    "odds_price": b.get("odds_price", -110),
                    "kelly_recommended": _half_kelly_amount(
                        b.get("odds_price", -110), b["confidence"], available
                    ),
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
        # Fallback: use Half Kelly sizing
        return _fallback_sizing(proposed_bets, available), []

    # Apply sizing decisions
    sized_bets = []
    skipped = []
    decisions = {d["bet_id"]: d for d in result.get("sizing_decisions", [])}

    for bet in proposed_bets:
        decision = decisions.get(bet["id"])
        if decision and decision.get("action") == "place" and decision.get("amount", 0) > 0:
            kelly_max = _half_kelly_amount(
                bet.get("odds_price", -110), bet["confidence"], available
            )
            if kelly_max <= 0:
                skipped.append({"matchup": bet["matchup"], "reason": "Kelly: no edge at these odds"})
                continue
            bet["amount"] = min(round(decision["amount"], 2), round(kelly_max * 1.2, 2))
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

    # Phase 1.7: Fetch Polymarket prices
    print("Fetching Polymarket prices...")
    await asyncio.to_thread(fetch_polymarket_prices, games, date)
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

    if not new_bets:
        print("No bets selected by analysis.")
        write_journal_pre_game(date, [], synthesis.get("skipped", []), synthesis.get("summary", ""))
        return

    # Get Polymarket balance for sizing
    print("Querying Polymarket balance...")
    balance = get_polymarket_balance()
    if balance is None:
        print("Error: Could not get Polymarket balance. Set POLYMARKET_PRIVATE_KEY and POLYMARKET_FUNDER.")
        return

    # Size bets
    print("Sizing bets...")
    sized_bets, sizing_skipped = await size_bets(
        new_bets, balance, strategy, history["summary"]
    )

    # Combine skipped lists for journal
    all_skipped = synthesis.get("skipped", []) + sizing_skipped

    if not sized_bets:
        print("All bets were vetoed by sizing.")
        write_journal_pre_game(date, [], all_skipped, synthesis.get("summary", ""))
        return

    # Save active bets
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

    dollar_pnl = get_dollar_pnl()
    print(f"\nBalance: ${balance:.2f} | Dollar P&L: ${dollar_pnl:+.2f}")
    print(f"See bets/journal/{date}.md for details")
