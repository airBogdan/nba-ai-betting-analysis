"""Bridge between polymarket_helpers and workflow layer."""

from typing import Any, Dict, List, Optional

from polymarket_helpers.gamma import extract_polymarket_odds, fetch_nba_events
from polymarket_helpers.matching import event_matches_matchup, pick_matches_outcome


def fetch_polymarket_prices(games: List[Dict[str, Any]], date: str) -> None:
    """Fetch Polymarket events and attach pricing data to each game.

    Mutates each game dict in-place, adding game["polymarket_odds"] with
    home/away structured pricing when a matching event is found.
    """
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
