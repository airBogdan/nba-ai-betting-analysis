"""Type definitions for NBA analytics."""

from typing import Dict, List, Optional, Union
from typing_extensions import TypedDict


# GameStatistics is a dict with string keys and string/number values
GameStatistics = Dict[str, Union[str, int, float]]


class Game(TypedDict, total=False):
    """Represents a single game result."""
    id: int
    home_team: str
    visitor_team: str
    home_points: int
    visitor_points: int
    winner: str
    point_diff: int
    home_statistics: Optional[GameStatistics]
    visitor_statistics: Optional[GameStatistics]
    home_linescore: Optional[List[int]]
    visitor_linescore: Optional[List[int]]


class QuarterAnalysis(TypedDict):
    """Quarter-by-quarter analysis of games."""
    avg_q1_total: float
    avg_q2_total: float
    avg_q3_total: float
    avg_q4_total: float
    avg_first_half: float
    avg_second_half: float
    team1_q1_avg: float
    team2_q1_avg: float
    team1_q4_avg: float
    team2_q4_avg: float
    halftime_leader_wins_pct: float


class TeamGameStats(TypedDict):
    """Team statistics from a single game."""
    team: Dict[str, str]  # { name: string }
    statistics: List[GameStatistics]


# H2HResults maps season year (int) to list of games
H2HResults = Dict[int, List[Game]]


class H2HSummary(TypedDict):
    """Head-to-head summary between two teams."""
    team1: str
    team2: str
    total_games: int
    team1_wins_all_time: int
    team2_wins_all_time: int
    team1_win_pct: float
    team1_home_wins: int
    team1_home_losses: int
    team1_away_wins: int
    team1_away_losses: int
    avg_point_diff: float
    avg_total_points: float
    team1_avg_points: float
    team2_avg_points: float
    last_5_games: List[str]
    recent_trend: str
    close_games: int
    blowouts: int
