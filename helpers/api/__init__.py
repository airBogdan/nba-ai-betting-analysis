"""NBA API client and data processors."""

from .types import (
    TeamPlayerStatistics,
    ProcessedPlayerStats,
    RawTeamStats,
    ProcessedTeamStats,
    RecentGame,
    GameStatus,
    GameTeam,
    GameTeams,
    ScheduledGame,
    Injury,
    OddsLine,
    OddsSpread,
    OddsTotal,
    OddsMoneyline,
    GameOdds,
)
from .client import (
    fetch_nba_api,
    get_teams,
    get_game_statistics,
    get_team_id_by_name,
    get_head_to_head_games,
    get_team_standings,
    get_team_statistics,
    get_team_players_statistics,
    get_games_by_date,
    get_game_by_id,
    get_game_player_stats,
)
from .processors import (
    parse_minutes,
    process_player_statistics,
    process_team_stats,
    get_all_standings,
    get_team_statistics_for_seasons,
    compute_league_avg_efficiency,
    get_team_recent_games,
    get_scheduled_games,
)
from .injuries import (
    fetch_injuries,
    filter_injuries_by_teams,
)
from .odds import (
    fetch_nba_odds,
    fetch_event_alternates,
    find_game_odds,
    extract_odds,
)

__all__ = [
    # Types
    "TeamPlayerStatistics",
    "ProcessedPlayerStats",
    "RawTeamStats",
    "ProcessedTeamStats",
    "RecentGame",
    "GameStatus",
    "GameTeam",
    "GameTeams",
    "ScheduledGame",
    "Injury",
    "OddsLine",
    "OddsSpread",
    "OddsTotal",
    "OddsMoneyline",
    "GameOdds",
    # Client
    "fetch_nba_api",
    "get_teams",
    "get_game_statistics",
    "get_team_id_by_name",
    "get_head_to_head_games",
    "get_team_standings",
    "get_team_statistics",
    "get_team_players_statistics",
    "get_games_by_date",
    "get_game_by_id",
    "get_game_player_stats",
    # Processors
    "parse_minutes",
    "process_player_statistics",
    "process_team_stats",
    "get_all_standings",
    "get_team_statistics_for_seasons",
    "compute_league_avg_efficiency",
    "get_team_recent_games",
    "get_scheduled_games",
    # Injuries
    "fetch_injuries",
    "filter_injuries_by_teams",
    # Odds
    "fetch_nba_odds",
    "fetch_event_alternates",
    "find_game_odds",
    "extract_odds",
]
