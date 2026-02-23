"""Matchup analysis package — re-exports all public names."""

# Types and constants
from .types import (  # noqa: F401
    AVAILABILITY_THRESHOLD,
    AWAY_STRONG_THRESHOLD,
    AWAY_WEAK_THRESHOLD,
    BACK_TO_BACK_THRESHOLD,
    DEFAULT_LEAGUE_AVG_EFFICIENCY,
    DEFAULT_LEAGUE_AVG_TOTAL,
    FAST_PACE_THRESHOLD,
    FGP_DIFF_THRESHOLD,
    FORM_COLD_THRESHOLD,
    FORM_HOT_THRESHOLD,
    H2H_VARIANCE_THRESHOLD,
    HALF_SCORING_DIFF_THRESHOLD,
    HALFTIME_LEADER_THRESHOLD,
    HOME_STRONG_THRESHOLD,
    HOME_WEAK_THRESHOLD,
    LEAGUE_AVG_TOTAL_MAX,
    LEAGUE_AVG_TOTAL_MIN,
    NET_RATING_EDGE_THRESHOLD,
    PPG_EDGE_THRESHOLD,
    QUARTER_DIFF_THRESHOLD,
    REB_DIFF_THRESHOLD,
    REGRESSION_FACTOR,
    REST_ADVANTAGE_THRESHOLD,
    SCORING_REGRESSION_THRESHOLD,
    SCORING_TREND_THRESHOLD,
    SLOW_PACE_THRESHOLD,
    STAR_DEPENDENCY_THRESHOLD,
    TOV_DIFF_THRESHOLD,
    TPP_DIFF_THRESHOLD,
    BuildMatchupInput,
    H2H,
    H2HMatchupStats,
    H2HPatterns,
    H2HRecent,
    H2HSummaryData,
    H2HTeamStats,
    MatchupAnalysis,
    MatchupEdges,
    RotationPlayer,
    TeamPlayers,
    TeamSchedule,
    TeamSnapshot,
    TotalsAnalysis,
)

# H2H
from .h2h import (  # noqa: F401
    compute_h2h_matchup_stats,
    compute_h2h_patterns,
    compute_recent_h2h,
)

# Core
from .core import (  # noqa: F401
    _exponential_decay_weights,
    build_matchup_analysis,
    build_team_snapshot,
    compute_edges,
    get_current_season_standing,
    get_current_season_stats,
)

# Schedule
from .schedule import (  # noqa: F401
    compute_days_rest,
    compute_games_last_n_days,
    compute_schedule_context,
    compute_streak,
)

# Signals
from .signals import generate_signals  # noqa: F401

# Totals
from .totals import compute_totals_analysis  # noqa: F401

# Players
from .players import build_team_players  # noqa: F401
