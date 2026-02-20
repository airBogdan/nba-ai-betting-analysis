"""Matchup analysis type definitions and constants."""

from typing import Any, Dict, List, Optional

from typing_extensions import TypedDict

from .api import Injury, ProcessedPlayerStats, ProcessedTeamStats, RecentGame
from .teams import SeasonStanding
from .types import H2HResults, H2HSummary, QuarterAnalysis


# === Constants ===
# TODO: for user, test and tweak these variables based on betting results

# Rest/schedule thresholds
BACK_TO_BACK_THRESHOLD = 1
REST_ADVANTAGE_THRESHOLD = 2

# Player impact thresholds
STAR_DEPENDENCY_THRESHOLD = 22
AVAILABILITY_THRESHOLD = 0.7

# Form thresholds (last 10 win%)
FORM_HOT_THRESHOLD = 0.7
FORM_COLD_THRESHOLD = 0.3

# Home/away performance thresholds
HOME_STRONG_THRESHOLD = 0.6
HOME_WEAK_THRESHOLD = 0.4
AWAY_STRONG_THRESHOLD = 0.55
AWAY_WEAK_THRESHOLD = 0.35

# Scoring/rating edge thresholds
PPG_EDGE_THRESHOLD = 3.0
NET_RATING_EDGE_THRESHOLD = 3.0

# Pace thresholds
FAST_PACE_THRESHOLD = 105
SLOW_PACE_THRESHOLD = 98

# Totals signal thresholds
SCORING_TREND_THRESHOLD = 5
H2H_VARIANCE_THRESHOLD = 15

# H2H quarter/half tendency thresholds
QUARTER_DIFF_THRESHOLD = 2
HALFTIME_LEADER_THRESHOLD = 0.65
HALF_SCORING_DIFF_THRESHOLD = 3

# H2H vs season comparison thresholds
FGP_DIFF_THRESHOLD = 3
TPP_DIFF_THRESHOLD = 4
TOV_DIFF_THRESHOLD = 2
REB_DIFF_THRESHOLD = 3

# League average defaults
DEFAULT_LEAGUE_AVG_EFFICIENCY = 113.5
DEFAULT_LEAGUE_AVG_TOTAL = 225.0
LEAGUE_AVG_TOTAL_MIN = 180
LEAGUE_AVG_TOTAL_MAX = 240

# Regression factor for expected total
REGRESSION_FACTOR = 0.15

# Scoring regression threshold (recent PPG vs season PPG)
SCORING_REGRESSION_THRESHOLD = 5


# === TypedDict definitions ===


class TeamSnapshot(TypedDict):
    """Current season team state with computed metrics."""
    name: str
    record: str
    conf_rank: int
    games: int
    ppg: float
    opp_ppg: float  # Points allowed (estimated)
    ortg: float  # Offensive rating estimate
    drtg: float  # Defensive rating estimate
    apg: float
    rpg: float
    topg: float
    net_rating: float
    fgp: float
    tpp: float
    last_ten: str
    last_ten_pct: float
    home_record: str
    away_record: str
    home_win_pct: float
    away_win_pct: float
    pace: float
    recent_ppg: float
    recent_margin: float
    sos: float
    sos_adjusted_net_rating: float


class MatchupEdges(TypedDict):
    """Comparison edges between two teams."""
    ppg: float
    net_rating: float
    form: float
    turnovers: float
    rebounds: float
    fgp: float
    three_pt_pct: float
    pace: float
    combined_pace: float
    weighted_form: float
    adjusted_net_rating: float


class H2HSummaryData(TypedDict):
    """H2H summary data."""
    total_games: int
    team1_wins_all_time: int
    team2_wins_all_time: int
    team1_win_pct: float
    team1_home_wins: int
    team1_home_losses: int
    team1_away_wins: int
    team1_away_losses: int
    avg_point_diff: float
    team1_avg_points: float
    team2_avg_points: float
    last_5_games: List[str]
    recent_trend: str
    close_games: int
    blowouts: int


class H2HPatterns(TypedDict):
    """H2H patterns analysis."""
    avg_total: float  # Single source of truth for avg combined score
    home_win_pct: float
    high_scoring_pct: float
    close_game_pct: float


class H2HTeamStats(TypedDict):
    """Aggregated team stats from H2H box scores."""
    avg_fgp: float
    avg_tpp: float
    avg_rebounds: float
    avg_assists: float
    avg_turnovers: float
    avg_disruption: float  # steals + blocks


class H2HMatchupStats(TypedDict):
    """Matchup-specific stats from H2H games."""
    team1: H2HTeamStats
    team2: H2HTeamStats


class H2HRecent(TypedDict):
    """Recent H2H data (last 2 seasons only)."""
    team1_wins_last_2_seasons: int
    team2_wins_last_2_seasons: int
    last_winner: str
    home_team_home_record: str
    games_last_2_seasons: int


class H2H(TypedDict):
    """Combined H2H analysis."""
    summary: H2HSummaryData
    patterns: H2HPatterns
    recent: H2HRecent
    quarters: Optional[QuarterAnalysis]
    matchup_stats: Optional[H2HMatchupStats]


class TeamSchedule(TypedDict):
    """Schedule/situational context for a team."""
    days_rest: Optional[int]
    streak: str  # e.g., "W3", "L2"
    games_last_7_days: int
    # Opponent strength context
    recent_opponent_avg_win_pct: float  # Avg win% of recent opponents
    quality_wins: int  # Wins vs .500+ teams in recent games
    quality_losses: int  # Losses vs .500+ teams in recent games


class TotalsAnalysis(TypedDict):
    """Totals/Over-Under analysis.

    Note: `injury_adjusted_total` may be added post-generation by the betting
    workflow (workflow/analyze.py) when injury data is available.
    """
    expected_total: float
    total_diff_from_h2h: float
    team1_h2h_scoring_diff: float
    team2_h2h_scoring_diff: float
    margin_volatility: float
    h2h_total_variance: float
    pace_adjusted_total: float
    defense_factor: float
    recent_scoring_trend: float


class RotationPlayer(TypedDict):
    """Rotation player data."""
    name: str
    ppg: float
    plus_minus: float
    games: int


class TeamPlayers(TypedDict, total=False):
    """Team player analysis."""
    rotation: List[RotationPlayer]
    availability_concerns: List[str]
    full_strength: bool
    top_scorers: str
    playmaker: str
    hot_hand: str
    star_dependency: float
    depth_rating: str
    bench_scoring: float
    injuries: List[Injury]  # Added post-generation from injuries API


class MatchupAnalysis(TypedDict):
    """Complete matchup analysis output."""
    matchup: Dict[str, str]
    current_season: Dict[str, TeamSnapshot]
    schedule: Dict[str, TeamSchedule]
    recent_games: Dict[str, List[RecentGame]]
    players: Dict[str, Optional[TeamPlayers]]
    h2h: Optional[H2H]
    totals_analysis: TotalsAnalysis
    comparison: MatchupEdges
    signals: List[str]


class BuildMatchupInput(TypedDict):
    """Input for build_matchup_analysis."""
    team1_name: str
    team2_name: str
    home_team: str
    team1_standings: List[SeasonStanding]
    team2_standings: List[SeasonStanding]
    team1_stats: Optional[Dict[int, ProcessedTeamStats]]
    team2_stats: Optional[Dict[int, ProcessedTeamStats]]
    team1_players: List[ProcessedPlayerStats]
    team2_players: List[ProcessedPlayerStats]
    team1_recent_games: List[RecentGame]
    team2_recent_games: List[RecentGame]
    h2h_summary: Optional[H2HSummary]
    h2h_results: Optional[H2HResults]
    game_date: Optional[str]  # YYYY-MM-DD or ISO datetime for rest calculations
