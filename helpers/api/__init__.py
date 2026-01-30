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
)
from .processors import (
    parse_minutes,
    process_player_statistics,
    process_team_stats,
    get_all_standings,
    get_team_statistics_for_seasons,
    get_team_recent_games,
    get_scheduled_games,
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
    # Processors
    "parse_minutes",
    "process_player_statistics",
    "process_team_stats",
    "get_all_standings",
    "get_team_statistics_for_seasons",
    "get_team_recent_games",
    "get_scheduled_games",
]
