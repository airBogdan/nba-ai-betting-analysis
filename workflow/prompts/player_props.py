"""Player props analysis and synthesis prompts."""

SYSTEM_PROPS_ANALYST = """You are an expert NBA player props analyst. You evaluate individual player
statistical lines (points, rebounds, assists) against their season averages, recent form,
matchup tendencies, and market prices. Be data-driven and specific. Only recommend props
where you see genuine statistical edge — the line is meaningfully off from your projection."""


ANALYZE_PLAYER_PROPS_PROMPT = """Analyze player prop betting value for this NBA game.

## Game: {matchup}

## Home Team Players — {home_team} (Season Averages)
{home_players_json}

## Away Team Players — {away_team} (Season Averages)
{away_players_json}

## Available Prop Markets (with Polymarket prices)
{prop_markets_json}

## Game-Level Search Context
{search_context}

## Props-Specific Search Context
{props_search_context}

## Current Strategy
{strategy}

## Instructions
For each player with prop markets, evaluate:
1. **Season average** vs the prop line — how far off is it?
2. **Recent form** — trending up or down from their average?
3. **Matchup factor** — does opponent's defense favor or hinder this stat?
4. **Price check** — is the Polymarket price fair given your projection?

Only recommend props where you see a genuine edge (projection differs meaningfully from line).

Recommend 0-3 player props for this game.

Respond with JSON:
{{
  "game_id": "{game_id}",
  "matchup": "{matchup}",
  "prop_recommendations": [
    {{
      "player_name": "Player Name",
      "prop_type": "points" | "rebounds" | "assists",
      "line": 25.5,
      "pick": "over" | "under",
      "confidence": "low" | "medium" | "high",
      "projection": 28.0,
      "edge": "Why this prop has value",
      "primary_edge": "Key factor"
    }}
  ],
  "analysis_summary": "1-2 sentence summary"
}}"""


SYNTHESIZE_PLAYER_PROPS_PROMPT = """Select the best player prop bets across all games today.

## Game-by-Game Prop Recommendations
{recommendations_json}

## Current Strategy
{strategy}

## Betting History Summary
{history_summary}

## Instructions
1. Review all prop recommendations across games
2. Select up to {max_props} props (0 is acceptable if edges are thin)
3. Prioritize: larger projection-vs-line gaps, higher confidence, better prices
4. Diversify across players and prop types when possible
5. Assign units: high=2.0, medium=1.0, low=0.5

Respond with JSON:
{{
  "selected_props": [
    {{
      "game_id": "...",
      "matchup": "Away @ Home",
      "player_name": "Player Name",
      "prop_type": "points" | "rebounds" | "assists",
      "line": 25.5,
      "pick": "over" | "under",
      "confidence": "low" | "medium" | "high",
      "units": 0.5 | 1.0 | 2.0,
      "reasoning": "Why this prop",
      "primary_edge": "Key factor"
    }}
  ],
  "summary": "1-2 sentence summary of prop selections"
}}"""
