"""Bet evaluation logic — payout calculation, outcome determination."""

from typing import Optional

from .game_results import _teams_match
from .names import names_match
from .types import ActiveBet, GameResult


def calculate_payout(amount: float, odds_price: int, result: str) -> float:
    """Calculate payout based on American odds.

    American odds:
    - Negative (e.g., -150): Bet $150 to win $100 → payout = stake * (1 + 100/150)
    - Positive (e.g., +130): Bet $100 to win $130 → payout = stake * (1 + 130/100)
    """
    if result == "push":
        return amount  # Stake returned
    if result == "loss":
        return 0.0  # Already deducted when placed

    # Win: return stake + profit
    if odds_price == 0:
        # Fallback to -110 if odds_price is invalid
        odds_price = -110
    if odds_price < 0:
        # Favorite: profit = stake * (100 / abs(odds))
        profit = amount * (100 / abs(odds_price))
    else:
        # Underdog: profit = stake * (odds / 100)
        profit = amount * (odds_price / 100)

    return amount + profit  # Stake back + profit


def _evaluate_bet(bet: ActiveBet, result: GameResult) -> tuple:
    """
    Evaluate bet outcome based on bet type.
    Returns (outcome, profit_loss) tuple.
    """
    bet_type = bet.get("bet_type", "moneyline")
    units = bet["units"]

    if bet_type == "moneyline":
        # Did the picked team win?
        if _teams_match(bet["pick"], result["winner"]):
            return "win", units
        return "loss", -units

    elif bet_type == "spread":
        # Did the picked team cover the spread?
        line = bet.get("line", 0)
        # Calculate margin from perspective of picked team
        if _teams_match(bet["pick"], result["home_team"]):
            # We picked home team
            margin = result["home_score"] - result["away_score"]
        else:
            # We picked away team
            margin = result["away_score"] - result["home_score"]

        # For spread, negative line means favorite (needs to win by more than line)
        # Positive line means underdog (can lose by less than line)
        adjusted_margin = margin + line  # line is already signed correctly

        if adjusted_margin > 0:
            return "win", units
        elif adjusted_margin < 0:
            return "loss", -units
        else:
            return "push", 0.0

    elif bet_type == "player_prop":
        raise ValueError("player_prop bets must be evaluated via _evaluate_prop_bet")

    elif bet_type == "total":
        # Was the actual total over/under the line?
        line = bet.get("line", 0)
        actual_total = result["home_score"] + result["away_score"]
        pick = bet["pick"].lower()

        if pick == "over":
            if actual_total > line:
                return "win", units
            elif actual_total < line:
                return "loss", -units
            else:
                return "push", 0.0
        else:  # under
            if actual_total < line:
                return "win", units
            elif actual_total > line:
                return "loss", -units
            else:
                return "push", 0.0

    # Default to moneyline logic
    if _teams_match(bet["pick"], result["winner"]):
        return "win", units
    return "loss", -units


# --- Player prop evaluation ---

PROP_TYPE_TO_STAT_KEY = {
    "points": "points",
    "rebounds": "totReb",
    "assists": "assists",
}


def _find_player_stat(
    box_score: list[dict], player_name: str, prop_type: str
) -> Optional[float]:
    """Find a player's stat from box score data.

    Returns the stat value or None if player not found.
    """
    stat_key = PROP_TYPE_TO_STAT_KEY.get(prop_type)
    if not stat_key:
        return None

    for entry in box_score:
        player = entry.get("player", {})
        full_name = f"{player.get('firstname', '')} {player.get('lastname', '')}".strip()
        if not full_name:
            continue
        if names_match(player_name, full_name):
            val = entry.get(stat_key)
            if val is not None:
                try:
                    return float(val)
                except (ValueError, TypeError):
                    return None
    return None


def _evaluate_prop_bet(
    bet: ActiveBet, actual_stat: float
) -> tuple[str, float]:
    """Evaluate a player prop bet.

    Returns (outcome, profit_loss).
    Caller must resolve actual_stat before calling (DNP = void, handled upstream).
    """
    units = bet["units"]
    line = bet.get("line", 0)
    pick = bet["pick"].lower()

    if pick == "over":
        if actual_stat > line:
            return "win", units
        elif actual_stat < line:
            return "loss", -units
        else:
            return "push", 0.0
    else:  # under
        if actual_stat < line:
            return "win", units
        elif actual_stat > line:
            return "loss", -units
        else:
            return "push", 0.0
