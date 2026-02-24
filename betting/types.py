"""TypedDict definitions for betting workflow."""

from typing import Dict, List, Literal, Optional, TypedDict


class MoneylineAnalysis(TypedDict):
    """Moneyline bet analysis from LLM."""

    pick: Optional[str]  # Team name or None if skip
    confidence: Literal["low", "medium", "high", "skip"]
    edge: str


class SpreadAnalysis(TypedDict):
    """Spread bet analysis from LLM."""

    pick: str  # Team name
    line: float  # Negative = favorite, positive = underdog
    confidence: Literal["low", "medium", "high", "skip"]
    edge: str


class TotalAnalysis(TypedDict):
    """Totals bet analysis from LLM."""

    pick: Literal["over", "under"]
    line: float  # The total line (e.g., 224.5)
    confidence: Literal["low", "medium", "high", "skip"]
    edge: str


class RecommendedBet(TypedDict):
    """Single bet recommendation from analysis."""

    bet_type: Literal["moneyline", "spread", "total", "player_prop"]
    pick: str  # Team name or "over"/"under"
    line: Optional[float]  # null for moneyline
    confidence: Literal["low", "medium", "high"]
    edge: str


class BetRecommendation(TypedDict):
    """LLM output per game - matches ANALYZE_GAME_PROMPT response."""

    game_id: str
    matchup: str
    expected_margin: float  # Positive = home favored, negative = away favored
    expected_total: float  # Projected combined score
    moneyline: MoneylineAnalysis
    spread: SpreadAnalysis
    total: TotalAnalysis
    recommended_bets: List[RecommendedBet]  # 0-3 bets from this game
    primary_edge: str
    case_for: List[str]
    case_against: List[str]
    analysis_summary: str


class SelectedBet(TypedDict):
    """Final bet after synthesis."""

    game_id: str
    matchup: str
    bet_type: Literal["moneyline", "spread", "total", "player_prop"]
    pick: str  # Team name for ML/spread, "over"/"under" for totals
    line: Optional[float]  # Spread number or total number (e.g., -4.5 or 224.5)
    confidence: Literal["low", "medium", "high"]
    units: float
    reasoning: str
    primary_edge: str


class _ActiveBetRequired(TypedDict):
    """Required fields for ActiveBet."""

    id: str
    game_id: str
    matchup: str
    bet_type: Literal["moneyline", "spread", "total", "player_prop"]
    pick: str  # Team name for ML/spread, "over"/"under" for totals
    line: Optional[float]  # Spread number or total number
    confidence: Literal["low", "medium", "high"]
    units: float
    reasoning: str
    primary_edge: str
    date: str
    created_at: str


class ActiveBet(_ActiveBetRequired, total=False):
    """Bet awaiting results."""

    amount: float  # Dollar amount to wager
    odds_price: int  # American odds price for payout calc (e.g., -150, +130)
    poly_price: float  # Polymarket price (0-1) at analysis time
    placed_polymarket: bool  # Whether bet was placed on Polymarket
    prop_type: str  # "points", "rebounds", or "assists" (player_prop only)
    player_name: str  # Player name (player_prop only)


class _CompletedBetRequired(TypedDict):
    """Required fields for CompletedBet."""

    id: str
    game_id: str
    matchup: str
    bet_type: Literal["moneyline", "spread", "total", "player_prop"]
    pick: str
    line: Optional[float]
    confidence: Literal["low", "medium", "high"]
    units: float
    reasoning: str
    primary_edge: str
    date: str
    created_at: str
    result: Literal["win", "loss", "push", "early_exit"]
    winner: str
    final_score: str
    actual_total: Optional[int]  # For totals bets
    actual_margin: Optional[int]  # For spread bets (positive = home win margin)
    profit_loss: float
    reflection: str


class StructuredReflection(TypedDict):
    """Structured reflection on a completed bet."""

    edge_valid: bool
    missed_factors: List[str]
    process_assessment: Literal["sound", "flawed", "unlucky", "lucky"]
    key_lesson: str
    summary: str


class CompletedBet(_CompletedBetRequired, total=False):
    """Bet with result."""

    amount: float  # Dollar amount wagered
    odds_price: int  # American odds used
    poly_price: float  # Polymarket price (0-1) at analysis time
    structured_reflection: StructuredReflection
    dollar_pnl: float  # Dollar profit/loss (positive=win, negative=loss)
    prop_type: str  # "points", "rebounds", or "assists" (player_prop only)
    player_name: str  # Player name (player_prop only)
    actual_stat: float  # Actual stat value (player_prop only)


class GameResult(TypedDict):
    """From API."""

    game_id: str
    home_team: str
    away_team: str
    home_score: int
    away_score: int
    winner: str
    status: str


class ConfidenceStats(TypedDict):
    """Stats by confidence level."""

    wins: int
    losses: int
    win_rate: float


class BetHistorySummary(TypedDict):
    """Summary statistics for bet history."""

    total_bets: int
    wins: int
    losses: int
    pushes: int
    win_rate: float
    total_units_wagered: float
    net_units: float
    roi: float
    by_confidence: Dict[str, ConfidenceStats]
    by_primary_edge: Dict[str, ConfidenceStats]
    by_bet_type: Dict[str, ConfidenceStats]
    current_streak: str
    net_dollar_pnl: float


class _SkippedGameRequired(TypedDict):
    """Required fields for SkippedGame."""

    matchup: str  # "Away @ Home"
    reason: str  # Why skipped
    date: str  # "YYYY-MM-DD"


class SkippedGame(_SkippedGameRequired, total=False):
    """Skipped game with optional outcome data."""

    game_id: str  # API game ID for outcome lookup
    source: str  # "synthesis" | "sizing"
    winner: str  # Filled by results workflow
    final_score: str  # "Away X @ Home Y"
    actual_total: int
    actual_margin: int
    outcome_resolved: bool


class BetHistory(TypedDict):
    """Full bet history structure."""

    bets: List[CompletedBet]
    summary: BetHistorySummary


class _PaperTradeRequired(TypedDict):
    """Required fields for PaperTrade."""

    matchup: str
    date: str
    bet_type: Literal["moneyline", "spread", "total", "player_prop"]
    pick: str
    line: Optional[float]
    confidence: Literal["low", "medium", "high"]
    reasoning: str
    primary_edge: str
    skip_reason: str


class PaperTrade(_PaperTradeRequired, total=False):
    """Paper trade on a skipped game."""

    game_id: str
    result: Literal["win", "loss", "push"]
    winner: str
    final_score: str
    actual_total: int
    actual_margin: int
    profit_loss: float
    units: float


class PaperHistorySummary(TypedDict):
    """Summary statistics for paper trade history."""

    total_trades: int
    wins: int
    losses: int
    pushes: int
    win_rate: float
    net_units: float
    by_confidence: Dict[str, ConfidenceStats]
    by_bet_type: Dict[str, ConfidenceStats]
    by_skip_reason_category: Dict[str, ConfidenceStats]


class PaperHistory(TypedDict):
    """Full paper trade history structure."""

    trades: List[PaperTrade]
    summary: PaperHistorySummary
