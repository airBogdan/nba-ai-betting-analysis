"""Game file I/O, shared constants, and format helpers."""

import json
from pathlib import Path
from typing import Any, Dict, List

# Limit concurrent LLM calls to avoid rate limiting
MAX_CONCURRENT_LLM_CALLS = 4

OUTPUT_DIR = Path(__file__).parent.parent.parent / "output"

HAIKU_MODEL = "anthropic/claude-haiku-4.5"


def load_games_for_date(date: str) -> List[Dict[str, Any]]:
    """Load matchup files for a specific date (excludes props_ files)."""
    games = []
    pattern = f"*_{date}.json"
    for path in OUTPUT_DIR.glob(pattern):
        if path.name.startswith("props_"):
            continue
        try:
            data = json.loads(path.read_text())
            data["_file"] = path.name
            games.append(data)
        except (json.JSONDecodeError, OSError) as e:
            print(f"Error loading {path}: {e}")
    return games


def load_props_for_date(date: str) -> List[Dict[str, Any]]:
    """Load props files for a specific date."""
    props = []
    pattern = f"props_*_{date}.json"
    for path in OUTPUT_DIR.glob(pattern):
        try:
            data = json.loads(path.read_text())
            props.append(data)
        except (json.JSONDecodeError, OSError) as e:
            print(f"Error loading props {path}: {e}")
    return props


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
