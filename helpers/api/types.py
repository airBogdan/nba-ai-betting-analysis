"""TypedDict definitions for NBA API responses and processed data."""

from typing import Any, Dict, Literal, Optional
from typing_extensions import TypedDict


class TeamPlayerStatistics(TypedDict, total=False):
    """Raw player statistics from API."""
    player: Dict[str, Any]  # { id, firstname, lastname }
    team: Dict[str, Any]  # { id, name, nickname, code, logo }
    game: Dict[str, int]  # { id }
    points: int
    pos: Optional[Any]
    min: str
    fgm: int
    fga: int
    fgp: str
    ftm: int
    fta: int
    ftp: str
    tpm: int
    tpa: int
    tpp: str
    offReb: int
    defReb: int
    totReb: int
    assists: int
    pFouls: int
    steals: int
    turnovers: int
    blocks: int
    plusMinus: str
    comment: Optional[Any]


class ProcessedPlayerStats(TypedDict):
    """Aggregated player statistics."""
    id: int
    name: str
    games: int
    mpg: float
    ppg: float
    rpg: float
    apg: float
    disruption: float  # steals + blocks per game
    fgp: float
    tpp: float
    plus_minus: float


class RawTeamStats(TypedDict, total=False):
    """Raw team statistics from API."""
    games: int
    points: int
    fgm: int
    fga: int
    fgp: str
    ftm: int
    fta: int
    ftp: str
    tpm: int
    tpa: int
    tpp: str
    offReb: int
    defReb: int
    totReb: int
    assists: int
    steals: int
    turnovers: int
    blocks: int
    plusMinus: int


class ProcessedTeamStats(TypedDict):
    """Processed team statistics."""
    games: int
    ppg: float
    apg: float
    rpg: float
    topg: float
    disruption: float  # steals + blocks per game
    net_rating: float
    tpp: float
    fgp: float
    pace: float


class RecentGame(TypedDict):
    """Recent game result."""
    vs: str
    vs_record: str  # Opponent's current record (e.g., "18-3")
    vs_win_pct: float  # Opponent's win percentage
    result: Literal["W", "L"]
    score: str
    home: bool
    margin: int
    date: str


class GameStatus(TypedDict):
    """Game status info."""
    clock: Optional[str]
    halftime: bool
    long: str


class GameTeam(TypedDict):
    """Simplified team info for a game."""
    id: int
    name: str


class GameTeams(TypedDict):
    """Teams in a game."""
    visitors: GameTeam
    home: GameTeam


class ScheduledGame(TypedDict):
    """Filtered game from schedule."""
    id: int
    date_start: str
    status: GameStatus
    teams: GameTeams


class Injury(TypedDict):
    """Player injury report."""
    player: str
    status: str  # "Out", "Questionable", "Probable", "Day-to-day"
    reason: str
    report_time: str
