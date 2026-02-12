"""TypedDict definitions for betting workflow."""

from typing import Dict, List, Literal, Optional, TypedDict


class BankrollTransaction(TypedDict):
    """Single bankroll transaction."""

    date: str
    type: Literal["bet", "result", "adjustment", "early_exit"]
    amount: float  # Negative for bets placed, positive for payouts
    bet_id: Optional[str]
    description: str


class Bankroll(TypedDict):
    """Bankroll state."""

    starting: float
    current: float
    transactions: List[BankrollTransaction]


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

    bet_type: Literal["moneyline", "spread", "total"]
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
    bet_type: Literal["moneyline", "spread", "total"]
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
    bet_type: Literal["moneyline", "spread", "total"]
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


class _CompletedBetRequired(TypedDict):
    """Required fields for CompletedBet."""

    id: str
    game_id: str
    matchup: str
    bet_type: Literal["moneyline", "spread", "total"]
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


class BetHistory(TypedDict):
    """Full bet history structure."""

    bets: List[CompletedBet]
    summary: BetHistorySummary
