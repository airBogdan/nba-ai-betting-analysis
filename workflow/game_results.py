"""Game result parsing and bet-to-result matching."""

from typing import Any, Dict, List, Optional

from .types import ActiveBet, GameResult


def _teams_match(name1: str, name2: str) -> bool:
    """Check if two team names match (case-insensitive, word-based matching)."""
    n1 = name1.lower().strip()
    n2 = name2.lower().strip()
    if not n1 or not n2:
        return False
    if n1 == n2:
        return True
    # Word-subset matching: "Lakers" matches "Los Angeles Lakers"
    # but "Nets" does NOT match "Hornets"
    w1 = set(n1.split())
    w2 = set(n2.split())
    if w1 <= w2 or w2 <= w1:
        return True
    # Handle LA/Los Angeles variations
    n1_norm = n1.replace("los angeles", "la").replace("l.a.", "la")
    n2_norm = n2.replace("los angeles", "la").replace("l.a.", "la")
    if n1_norm == n2_norm:
        return True
    w1n = set(n1_norm.split())
    w2n = set(n2_norm.split())
    return w1n <= w2n or w2n <= w1n


def _format_score(result: GameResult) -> str:
    """Format score as 'Away 110 @ Home 105' style."""
    return f"{result['away_team']} {result['away_score']} @ {result['home_team']} {result['home_score']}"


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
