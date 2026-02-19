"""Injury extraction and impact computation."""

import asyncio
from typing import Any, Dict, List, Optional

from ..llm import complete_json
from ..names import names_match, normalize_name
from ..prompts import EXTRACT_INJURIES_PROMPT
from .gamedata import HAIKU_MODEL, MAX_CONCURRENT_LLM_CALLS, format_matchup_string, _save_game_file

# Injury impact parameters
INJURY_REPLACEMENT_FACTOR = 0.55  # Replacement players recover ~55% of missing PPG


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
                if names_match(inj["player"], player["name"]):
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
        seen_players = {normalize_name(e["player"]) for e in extracted}
        for team_key, team_name in [("team1", team1), ("team2", team2)]:
            api_injuries = game.get("players", {}).get(team_key, {}).get("injuries", [])
            for inj in api_injuries:
                if inj.get("status") not in ("Out", "Doubtful"):
                    continue
                norm = normalize_name(inj.get("player", ""))
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
