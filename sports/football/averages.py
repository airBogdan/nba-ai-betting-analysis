"""League average goals computation and caching."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from .client import LEAGUES, fetch_matches_for_date
from .stats import DEFAULT_LEAGUE_AVG

logger = logging.getLogger(__name__)

DOMESTIC_LEAGUES = ["epl", "la_liga", "bundesliga", "serie_a", "ligue_1", "eredivisie"]
AVERAGES_PATH = Path(__file__).parent / "league_averages.json"
MAX_AGE_DAYS = 30
SEASON_START = "2025-08-01"


def compute_league_average(matches: list[dict]) -> tuple[float, int, float, float]:
    """Compute average goals per game from finished matches.

    Returns (goals_per_game, match_count, home_goals_per_game, away_goals_per_game).
    """
    home_goals = 0
    away_goals = 0
    count = 0
    for m in matches:
        if m.get("match_status", "").strip() != "Finished":
            continue
        try:
            h = int(m.get("match_hometeam_score", 0))
            a = int(m.get("match_awayteam_score", 0))
        except (ValueError, TypeError):
            continue
        home_goals += h
        away_goals += a
        count += 1

    if count == 0:
        return (0.0, 0, 0.0, 0.0)
    return (home_goals + away_goals) / count, count, home_goals / count, away_goals / count


def load_averages() -> dict | None:
    """Read cached league averages from disk."""
    if not AVERAGES_PATH.exists():
        return None
    try:
        return json.loads(AVERAGES_PATH.read_text())
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Could not read league averages: %s", e)
        return None


def save_averages(data: dict) -> None:
    """Write league averages to disk."""
    AVERAGES_PATH.write_text(json.dumps(data, indent=2) + "\n")


def is_stale(data: dict, max_age_days: int = MAX_AGE_DAYS) -> bool:
    """Check if cached averages are older than max_age_days."""
    updated = data.get("updated")
    if not updated:
        return True
    try:
        ts = datetime.fromisoformat(updated)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age = datetime.now(timezone.utc) - ts
        return age.total_seconds() > max_age_days * 86400
    except (ValueError, TypeError):
        return True


def get_league_avg(league: str, averages: dict | None) -> float:
    """Get league average goals per game.

    Domestic leagues get their own average. UCL/UEL get european_avg
    (mean of all domestic leagues). Falls back to DEFAULT_LEAGUE_AVG.
    """
    if averages is None:
        return DEFAULT_LEAGUE_AVG

    leagues_data = averages.get("leagues", {})

    if league in DOMESTIC_LEAGUES:
        entry = leagues_data.get(league)
        if entry and entry.get("matches", 0) > 0:
            return entry["goals_per_game"]
        return DEFAULT_LEAGUE_AVG

    if league in ("ucl", "uel"):
        avg = averages.get("european_avg")
        if avg is not None:
            return avg
        return DEFAULT_LEAGUE_AVG

    return DEFAULT_LEAGUE_AVG


def get_league_home_away_avg(league: str, averages: dict | None) -> tuple[float, float]:
    """Get league home and away goal averages.

    Returns (home_goals_per_game, away_goals_per_game).
    Falls back to league_avg/2 if splits not available.
    """
    total = get_league_avg(league, averages)
    half = total / 2

    if averages is None:
        return (half, half)

    leagues_data = averages.get("leagues", {})

    if league in DOMESTIC_LEAGUES:
        entry = leagues_data.get(league)
        if entry and entry.get("matches", 0) > 0:
            return (
                entry.get("home_goals_per_game", half),
                entry.get("away_goals_per_game", half),
            )
        return (half, half)

    if league in ("ucl", "uel"):
        return (
            averages.get("european_home_avg", half),
            averages.get("european_away_avg", half),
        )

    return (half, half)


async def compute_all_averages() -> dict:
    """Fetch current season matches for all domestic leagues and compute averages.

    Fetches sequentially to avoid API rate limiting.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    leagues_data = {}

    for name in DOMESTIC_LEAGUES:
        league_id = LEAGUES[name]
        matches = await fetch_matches_for_date(
            SEASON_START, league_id, to_date=today
        )
        gpg, count, home_gpg, away_gpg = compute_league_average(matches)
        leagues_data[name] = {
            "goals_per_game": gpg,
            "matches": count,
            "home_goals_per_game": home_gpg,
            "away_goals_per_game": away_gpg,
        }
        logger.info(
            "  %s: %.2f goals/game (H:%.2f A:%.2f, %d matches)",
            name, gpg, home_gpg, away_gpg, count,
        )

    active = [d for d in leagues_data.values() if d["matches"] > 0]
    european_avg = sum(d["goals_per_game"] for d in active) / len(active) if active else DEFAULT_LEAGUE_AVG
    european_home = sum(d["home_goals_per_game"] for d in active) / len(active) if active else DEFAULT_LEAGUE_AVG / 2
    european_away = sum(d["away_goals_per_game"] for d in active) / len(active) if active else DEFAULT_LEAGUE_AVG / 2

    return {
        "updated": datetime.now(timezone.utc).isoformat(),
        "leagues": leagues_data,
        "european_avg": round(european_avg, 3),
        "european_home_avg": round(european_home, 3),
        "european_away_avg": round(european_away, 3),
    }


async def ensure_averages(force: bool = False) -> dict | None:
    """Load cached averages, recomputing if stale or forced.

    On failure, returns existing cached data or None (never crashes).
    """
    cached = load_averages()

    if not force and cached and not is_stale(cached):
        return cached

    try:
        logger.info("Computing league averages...")
        data = await compute_all_averages()
        save_averages(data)
        logger.info("League averages saved (european avg: %.3f)", data["european_avg"])
        return data
    except Exception as e:
        logger.error("Failed to compute league averages: %s", e)
        return cached
