"""Bridge between polymarket_helpers and workflow layer."""

from typing import Any, Dict, List, Optional

from polymarket_helpers.gamma import (
    extract_player_props,
    extract_polymarket_odds,
    fetch_nba_events,
)
from polymarket_helpers.matching import event_matches_matchup, pick_matches_outcome
from .names import names_match


def fetch_polymarket_prices(
    games: List[Dict[str, Any]], date: str, events: list[dict] | None = None
) -> None:
    """Fetch Polymarket events and attach pricing data to each game.

    Mutates each game dict in-place, adding game["polymarket_odds"] with
    home/away structured pricing when a matching event is found.

    Args:
        events: Optional pre-fetched events to avoid duplicate API call.
    """
    if events is None:
        events = fetch_nba_events(date)
    if not events:
        return

    for game in games:
        matchup = game.get("matchup", {})
        home_team = matchup.get("home_team", "")
        team1 = matchup.get("team1", "")
        team2 = matchup.get("team2", "")

        if not home_team or not team1 or not team2:
            continue

        away_team = team2 if team1 == home_team else team1

        for event in events:
            title = event.get("title", "")
            if event_matches_matchup(title, away_team, home_team):
                odds = extract_polymarket_odds(event)
                if odds:
                    game["polymarket_odds"] = odds
                break


def extract_poly_price_for_bet(
    game: Dict[str, Any],
    bet_type: str,
    pick: str,
    line: Optional[float],
) -> Optional[float]:
    """Look up a specific bet's Polymarket price from attached data.

    Returns the probability (0-1) or None if not found.
    """
    poly_odds = game.get("polymarket_odds")
    if not poly_odds:
        return None

    if bet_type == "moneyline":
        ml = poly_odds.get("moneyline")
        if not ml:
            return None
        for i, outcome in enumerate(ml.get("outcomes", [])):
            if pick_matches_outcome(pick, outcome):
                return ml["prices"][i]
        return None

    if bet_type == "spread":
        for spread in poly_odds.get("available_spreads", []):
            if line is not None and float(spread["line"]) == float(line):
                for i, outcome in enumerate(spread.get("outcomes", [])):
                    if pick_matches_outcome(pick, outcome):
                        return spread["prices"][i]
        return None

    if bet_type == "total":
        for total in poly_odds.get("available_totals", []):
            if line is not None and float(total["line"]) == float(line):
                for i, outcome in enumerate(total.get("outcomes", [])):
                    if pick_matches_outcome(pick, outcome):
                        return total["prices"][i]
        return None

    return None


def fetch_polymarket_player_props(
    games: List[Dict[str, Any]],
    date: str,
    events: list[dict] | None = None,
) -> Dict[str, list[dict]]:
    """Fetch player prop markets from Polymarket events.

    Returns dict keyed by game_id (str) -> list of prop market dicts.

    Args:
        events: Optional pre-fetched events to avoid duplicate API call.
    """
    if events is None:
        events = fetch_nba_events(date)
    if not events:
        return {}

    result: Dict[str, list[dict]] = {}

    for game in games:
        matchup = game.get("matchup", {})
        home_team = matchup.get("home_team", "")
        team1 = matchup.get("team1", "")
        team2 = matchup.get("team2", "")

        if not home_team or not team1 or not team2:
            continue

        away_team = team2 if team1 == home_team else team1
        game_id = str(game["api_game_id"]) if game.get("api_game_id") else game.get("_file", "")

        for event in events:
            title = event.get("title", "")
            if event_matches_matchup(title, away_team, home_team):
                props = extract_player_props(event)
                if props:
                    result[game_id] = props
                break

    return result


def extract_poly_price_for_prop(
    prop_markets: list[dict],
    prop_type: str,
    player_name: str,
    line: float | None,
    pick: str,
) -> Optional[float]:
    """Look up a player prop's Polymarket price.

    Maps pick "over" -> "Yes", "under" -> "No" (Polymarket convention).
    Uses fuzzy name matching for player names.

    Returns probability (0-1) or None if not found.
    """
    # Map over/under to Polymarket Yes/No
    target_outcome = "Yes" if pick.lower() == "over" else "No"

    for prop in prop_markets:
        if prop.get("prop_type") != prop_type:
            continue

        if not names_match(player_name, prop.get("player_name", "")):
            continue

        if line is not None:
            if prop.get("line") is None:
                continue
            try:
                if float(prop["line"]) != float(line):
                    continue
            except (ValueError, TypeError):
                continue

        # Find matching outcome
        for i, outcome in enumerate(prop.get("outcomes", [])):
            if outcome.lower() == target_outcome.lower():
                prices = prop.get("prices", [])
                if i < len(prices):
                    return prices[i]

    return None
