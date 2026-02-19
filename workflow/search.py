"""Web search enrichment for betting workflow."""

import os
from typing import Any, Dict, List, Optional

from .llm import complete
from .prompts import (
    SEARCH_FOLLOWUP_GENERATION_PROMPT,
    SEARCH_PERPLEXITY_WRAPPER,
    SEARCH_PLAYER_NEWS_PROMPT,
    SEARCH_PLAYER_PROPS_PROMPT,
    SEARCH_QUERY_SYSTEM,
    SEARCH_TEMPLATE_PROMPT,
)

DEFAULT_PERPLEXITY_MODEL = "perplexity/sonar-pro"
QUERY_GENERATION_MODEL = "anthropic/claude-haiku-4.5"


def sanitize_label(matchup_str: str) -> str:
    """Turn 'Celtics @ Lakers' into 'celtics_at_lakers'."""
    return matchup_str.lower().replace(" @ ", "_at_").replace(" ", "_")


def _get_perplexity_model() -> str:
    return os.environ.get("PERPLEXITY_MODEL", DEFAULT_PERPLEXITY_MODEL)


def _get_query_model() -> str:
    return os.environ.get("SEARCH_QUERY_MODEL", QUERY_GENERATION_MODEL)


def _build_search_summary(game_data: Dict[str, Any], matchup_str: str) -> str:
    """Build a lightweight text summary from raw game data for search context."""
    season = game_data.get("current_season", {})
    schedule = game_data.get("schedule", {})
    players = game_data.get("players", {})

    t1 = season.get("team1", {})
    t2 = season.get("team2", {})
    s1 = schedule.get("team1", {})
    s2 = schedule.get("team2", {})
    p1 = players.get("team1") or {}
    p2 = players.get("team2") or {}

    parts = [
        f"Matchup: {matchup_str}",
        f"{t1.get('name', '?')} ({t1.get('record', '?')}, #{t1.get('conf_rank', '?')}) vs {t2.get('name', '?')} ({t2.get('record', '?')}, #{t2.get('conf_rank', '?')})",
    ]

    # Recent form
    form_parts = []
    if s1.get("streak"):
        form_parts.append(f"{t1.get('name', '?')}: {s1['streak']} streak, {s1.get('days_rest', '?')}d rest")
    if s2.get("streak"):
        form_parts.append(f"{t2.get('name', '?')}: {s2['streak']} streak, {s2.get('days_rest', '?')}d rest")
    if form_parts:
        parts.append("Form: " + "; ".join(form_parts))

    # Availability concerns
    concerns = []
    for label, p in [(t1.get("name", "?"), p1), (t2.get("name", "?"), p2)]:
        ac = p.get("availability_concerns", [])
        if ac:
            names = [c.get("name", "?") if isinstance(c, dict) else str(c) for c in ac[:3]]
            concerns.append(f"{label}: {', '.join(names)}")
    if concerns:
        parts.append("Availability: " + "; ".join(concerns))

    return "\n".join(parts)


async def search_enrich(
    game_data: Dict[str, Any], matchup_str: str, game_label: str = ""
) -> Optional[str]:
    """Run web search enrichment: template search + conditional follow-up (2-3 calls).

    Returns search context text or None on failure.
    """
    query_model = _get_query_model()
    perplexity_model = _get_perplexity_model()
    summary = _build_search_summary(game_data, matchup_str)

    try:
        # Step 1: Template search with Perplexity
        template_prompt = SEARCH_TEMPLATE_PROMPT.format(matchup=matchup_str)
        baseline = await complete(template_prompt, model=perplexity_model)
        if not baseline:
            print(f"    search: no results")
            return None

        # Step 2: Cheap model identifies gaps and generates follow-up directive
        followup_prompt = SEARCH_FOLLOWUP_GENERATION_PROMPT.format(
            matchup=matchup_str,
            search_summary=summary,
            search_results=baseline,
        )
        followup_directive = await complete(followup_prompt, system=SEARCH_QUERY_SYSTEM, model=query_model)

        # Check if follow-up is needed
        if not followup_directive or len(followup_directive.strip()) < 40:
            print(f"    search: {len(baseline)} chars")
            return baseline
        followup_lower = followup_directive.strip().lower()
        if "no follow" in followup_lower or "no additional" in followup_lower:
            print(f"    search: {len(baseline)} chars")
            return baseline

        # Step 3: Wrap follow-up directive in Perplexity prompt and search
        perplexity_prompt = SEARCH_PERPLEXITY_WRAPPER.format(
            matchup=matchup_str,
            directive=followup_directive.strip(),
        )
        followup_result = await complete(perplexity_prompt, model=perplexity_model)
        if not followup_result:
            print(f"    search: {len(baseline)} chars")
            return baseline

        combined = baseline + "\n\n### Additional Context\n" + followup_result
        print(f"    search: {len(combined)} chars (with follow-up)")
        return combined

    except Exception as e:
        print(f"    search failed: {e}")
        return None


def _get_available_players(
    game_data: Dict[str, Any], team_key: str, max_players: int = 5
) -> List[Dict[str, Any]]:
    """Get top available (non-Out/Doubtful) players from rotation.

    Args:
        game_data: Full game data dict.
        team_key: "team1" or "team2".
        max_players: Maximum players to return.

    Returns:
        List of rotation dicts (name, ppg, etc.) for available players.
    """
    team_data = game_data.get("players", {}).get(team_key, {})
    rotation = team_data.get("rotation", [])
    injuries = team_data.get("injuries", [])

    # Build set of out/doubtful player names (lowercased)
    out_names = set()
    for inj in injuries:
        status = (inj.get("status") or "").strip()
        if status in ("Out", "Doubtful"):
            name = (inj.get("player") or inj.get("name") or "").strip().lower()
            if name:
                out_names.add(name)

    available = []
    for player in rotation:
        name = (player.get("name") or "").strip().lower()
        if name and name not in out_names:
            available.append(player)
        if len(available) >= max_players:
            break

    return available


async def search_player_news(
    game_data: Dict[str, Any], matchup_str: str
) -> Optional[str]:
    """Search for player-focused news via Perplexity.

    Returns markdown text or None on failure.
    """
    perplexity_model = _get_perplexity_model()

    team1_players = _get_available_players(game_data, "team1")
    team2_players = _get_available_players(game_data, "team2")

    if not team1_players and not team2_players:
        return None

    # Build player list string
    team1_name = game_data.get("current_season", {}).get("team1", {}).get("name", "Team 1")
    team2_name = game_data.get("current_season", {}).get("team2", {}).get("name", "Team 2")

    lines = []
    if team1_players:
        names = [f"{p['name']} ({p.get('ppg', '?')} PPG)" for p in team1_players]
        lines.append(f"**{team1_name}:** {', '.join(names)}")
    if team2_players:
        names = [f"{p['name']} ({p.get('ppg', '?')} PPG)" for p in team2_players]
        lines.append(f"**{team2_name}:** {', '.join(names)}")

    player_list = "\n".join(lines)
    prompt = SEARCH_PLAYER_NEWS_PROMPT.format(matchup=matchup_str, player_list=player_list)

    try:
        result = await complete(prompt, model=perplexity_model)
        if result:
            print(f"    player news: {len(result)} chars")
        return result or None
    except Exception as e:
        print(f"    player news failed: {e}")
        return None


MAX_PROP_SEARCH_PLAYERS = 10


async def search_player_props(
    matchup_str: str, players_with_props: list[dict]
) -> Optional[str]:
    """Search for player prop-specific context via Perplexity.

    One call per game covering all players with available prop markets.
    Returns markdown text or None on failure.
    """
    if not players_with_props:
        return None

    perplexity_model = _get_perplexity_model()

    # Build player list (capped at MAX_PROP_SEARCH_PLAYERS)
    lines = []
    seen = set()
    for prop in players_with_props[:MAX_PROP_SEARCH_PLAYERS]:
        name = prop.get("player_name", "")
        if name and name not in seen:
            line_val = prop.get("line", "?")
            lines.append(f"- {name} ({prop.get('prop_type', '?')} line: {line_val})")
            seen.add(name)

    if not lines:
        return None

    player_list_str = "\n".join(lines)
    prompt = SEARCH_PLAYER_PROPS_PROMPT.format(
        matchup=matchup_str, players_with_props=player_list_str
    )

    try:
        result = await complete(prompt, model=perplexity_model)
        if result:
            print(f"    props search: {len(result)} chars")
        return result or None
    except Exception as e:
        print(f"    props search failed: {e}")
        return None
