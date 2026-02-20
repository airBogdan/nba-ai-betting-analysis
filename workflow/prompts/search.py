"""Search and research prompts."""

EXTRACT_INJURIES_PROMPT = """Extract injured/out players from this pre-game report.

## Teams
Team 1: {team1}
Team 2: {team2}

## Report
{search_context}

## Instructions
Return a JSON array of players who are **Out** or **Doubtful** only. Skip Questionable/Probable/Available.
Each entry: {{"team": "Full Team Name", "player": "Player Name", "status": "Out" or "Doubtful"}}
If no players are out/doubtful, return an empty array: []

Respond with only the JSON array, no other text."""


SEARCH_QUERY_SYSTEM = (
    "You identify research angles for NBA game betting analysis. "
    "When generating a research directive, use 1-2 clear sentences describing what to investigate and why. "
    "Not keywords. Be specific. Follow the user's instructions exactly."
)

SEARCH_PERPLEXITY_WRAPPER = """Research the following for an NBA betting analysis.

Game: {matchup}

**Research focus:** {directive}

Report your findings organized under clear headers. Include:
- Specific facts, statuses, and numbers (not speculation)
- Sources or timeframes for injury/news items when available
- Any context that explains *why* something matters for this game

Keep it factual and concise. Do not make predictions or betting recommendations."""

SEARCH_TEMPLATE_PROMPT = """I need a pre-game research report for an NBA game today.

**Game: {matchup}**

Research and report on the following, organized under these exact headers:

### Injury Report
Current injury/availability statuses for both teams. List each player with their status (out, doubtful, questionable, probable) and injury type.

### Betting Lines
Current consensus spread, moneyline odds, and over/under total.

### Line Movement
Notable moves from opening lines. What drove the movement if known.

### Recent News
Relevant team news from the last 48 hours — roster moves, rotation changes, notable performances, rest decisions.

Facts only. If a section has no relevant information, state that briefly."""

SEARCH_PLAYER_NEWS_PROMPT = """I need a player-focused news report for an NBA game today.

**Game: {matchup}**

**Key players to research:**
{player_list}

Research and report on the following, organized under these exact headers:

### Player Form & Streaks
Notable hot/cold streaks, recent scoring runs, shooting slumps, or usage changes for any of the listed players.

### Rotation & Role Changes
Any recent rotation adjustments, minute increases/decreases, or role changes (e.g., moved to bench, new starting lineup).

### Returning Players & Ramp-Ups
Players recently back from injury who may be on minute restrictions or still ramping up.

### Trade & Roster Buzz
Recent trade rumors, buyout candidates, or roster moves affecting either team.

### Matchup Storylines
Notable individual matchups, revenge games, or storylines between these specific players.

### Rest & Load Management
Any known rest plans, back-to-back management, or load management decisions.

Skip injury statuses (already covered), skip betting lines and odds (already covered), skip box-score stats. Focus on narrative context and recent developments only. Facts only — if a section has nothing relevant, skip it entirely."""

SEARCH_FOLLOWUP_GENERATION_PROMPT = """Review the initial search results below and identify any important gaps for betting analysis.

Matchup: {matchup}

{search_summary}

### Initial Search Results
{search_results}

If the results adequately cover injuries, betting lines, line movement, and recent news, respond with exactly: "No follow-up needed"

Otherwise, describe in 1-2 sentences what additional information would be most valuable for betting analysis on this game and why. Be specific — not keywords, but a clear research directive."""


SEARCH_POSITION_CONTEXT_PROMPT = """I need a quick update on injury and lineup changes for an NBA game today.

**Game: {matchup}**

Focus ONLY on:
1. **Injury updates** — any changes to player availability since this morning
2. **Lineup changes** — confirmed starters, late scratches
3. **Status upgrades/downgrades** — players whose status changed (e.g., questionable → out, doubtful → available)

Skip betting lines, odds, analysis, and general team news. Just injury/lineup facts.
Keep it brief and factual."""


SEARCH_PLAYER_PROPS_PROMPT = """I need player-specific statistical research for NBA player prop betting.

**Game: {matchup}**

**Players with prop markets:**
{players_with_props}

For each player listed above, research:

### Recent Performance (Last 5 Games)
- Points, rebounds, assists in each of the last 5 games
- Any notable trends (hot streak, cold streak, increasing/decreasing usage)

### Matchup Tendencies
- How does each player typically perform against today's opponent?
- Does the opposing team's defense rank particularly well or poorly against this player's primary stat?

### Usage & Role Context
- Any recent changes in minutes, usage rate, or role?
- Teammate injuries that could increase/decrease this player's workload?

Focus on facts and numbers. Skip general team analysis (already covered elsewhere).
Cap your research to the players listed — do not add others."""
