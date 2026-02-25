"""APIFootball data parsing for live match events."""


def was_tied(home: int, away: int) -> bool:
    """Check if a score represents a tied game."""
    return home == away


def parse_goal_event(match: dict) -> dict | None:
    """Parse an APIFootball match dict into a structured goal event.

    Returns None if the match has no goalscorer data.

    Returns:
        {
            "match_id": str,
            "home_team": str,
            "away_team": str,
            "home_score": int,
            "away_score": int,
            "goals": [
                {
                    "time": str,
                    "player": str,
                    "home_score": int,
                    "away_score": int,
                },
                ...
            ],
        }
    """
    scorers = match.get("goalscorer")
    if not scorers:
        return None

    match_id = match.get("match_id", "")
    home_team = match.get("match_hometeam_name", "")
    away_team = match.get("match_awayteam_name", "")

    try:
        home_score = int(match.get("match_hometeam_score", 0))
        away_score = int(match.get("match_awayteam_score", 0))
    except (ValueError, TypeError):
        return None

    goals = []
    for scorer in scorers:
        score_str = scorer.get("score", "")
        parts = score_str.split(" - ")
        if len(parts) != 2:
            continue
        try:
            g_home = int(parts[0].strip())
            g_away = int(parts[1].strip())
        except (ValueError, TypeError):
            continue

        goals.append({
            "time": scorer.get("time", ""),
            "player": scorer.get("scorer", ""),
            "home_score": g_home,
            "away_score": g_away,
        })

    return {
        "match_id": match_id,
        "home_team": home_team,
        "away_team": away_team,
        "home_score": home_score,
        "away_score": away_score,
        "goals": goals,
    }
