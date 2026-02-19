_NBA_SHORT_NAMES = {
    "hawks", "celtics", "nets", "hornets", "bulls", "cavaliers",
    "mavericks", "nuggets", "pistons", "warriors", "rockets", "pacers",
    "clippers", "lakers", "grizzlies", "heat", "bucks", "timberwolves",
    "pelicans", "knicks", "thunder", "magic", "76ers", "suns",
    "trail blazers", "kings", "spurs", "raptors", "jazz", "wizards",
}


def _extract_short_name(full_name: str) -> str:
    """Extract the short team name (e.g. 'Phoenix Suns' -> 'suns')."""
    words = full_name.strip().split()
    # Try two-word suffix first (Trail Blazers)
    if len(words) >= 3:
        two_word = " ".join(words[-2:]).lower()
        if two_word in _NBA_SHORT_NAMES:
            return two_word
    # Last word
    return words[-1].lower()


def parse_matchup(matchup: str) -> tuple[str, str]:
    """Split 'Away Team @ Home Team' into (away, home)."""
    if " @ " not in matchup:
        raise ValueError(f"Invalid matchup format: {matchup}")
    parts = matchup.split(" @ ", 1)
    return parts[0].strip(), parts[1].strip()


def _title_words(title: str) -> set[str]:
    """Split title into lowercase word tokens."""
    # "Hornets vs. Suns" -> {"hornets", "vs.", "suns"}
    return set(title.lower().split())


def event_matches_matchup(title: str, away: str, home: str) -> bool:
    """Check if a Polymarket event title matches a given matchup."""
    words = _title_words(title)
    away_short = _extract_short_name(away)
    home_short = _extract_short_name(home)
    # Multi-word names (trail blazers) check substring; single-word check exact token
    away_match = away_short in words if " " not in away_short else away_short in title.lower()
    home_match = home_short in words if " " not in home_short else home_short in title.lower()
    return away_match and home_match


def pick_matches_outcome(pick: str, outcome: str) -> bool:
    """Check if a bet pick matches a market outcome."""
    if pick.lower() == outcome.lower():
        return True
    pick_short = _extract_short_name(pick)
    return pick_short == outcome.lower()


def prop_pick_to_outcome(pick: str) -> str:
    """Map over/under pick to Polymarket Yes/No outcome.

    Polymarket player props use Yes/No instead of Over/Under.
    "over" -> "Yes", "under" -> "No".
    """
    return "Yes" if pick.lower() == "over" else "No"
