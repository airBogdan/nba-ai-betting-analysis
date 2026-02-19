"""Kelly criterion, odds math, and LLM-driven bet sizing."""

import json
from typing import Any, Dict, List, Optional, Tuple

from ..io import get_dollar_pnl, get_open_exposure
from ..llm import complete_json
from ..polymarket_prices import extract_poly_price_for_bet
from ..prompts import SIZING_PROMPT, SYSTEM_SIZING, format_history_summary
from ..types import ActiveBet
from polymarket_helpers.odds import poly_price_to_american

# Kelly Criterion parameters
CONFIDENCE_WIN_PROB = {"high": 0.65, "medium": 0.57, "low": 0.54}
KELLY_FRACTION = 0.5


def _american_odds_to_decimal(odds: int) -> float:
    """Convert American odds to decimal odds (payout per $1 wagered)."""
    if odds < 0:
        return 1 + 100 / abs(odds)
    return 1 + odds / 100


def _half_kelly_amount(odds_price: int, confidence: str, available: float) -> float:
    """Compute Half Kelly bet amount. Returns 0 if no edge."""
    p = CONFIDENCE_WIN_PROB.get(confidence, 0.54)
    decimal_odds = _american_odds_to_decimal(odds_price)
    b = decimal_odds - 1
    if b <= 0:
        return 0.0
    kelly = (b * p - (1 - p)) / b
    if kelly <= 0:
        return 0.0
    fraction = kelly * KELLY_FRACTION
    return round(fraction * available, 2)


def _extract_sizing_strategy(strategy: Optional[str]) -> str:
    """Extract Position Sizing section from strategy.md."""
    if not strategy:
        return "No sizing strategy defined yet."
    # Find the Position Sizing section
    if "## Position Sizing" in strategy:
        start = strategy.index("## Position Sizing")
        # Find next ## or end of file
        rest = strategy[start + len("## Position Sizing") :]
        if "\n## " in rest:
            end = rest.index("\n## ")
            return strategy[start : start + len("## Position Sizing") + end]
        return strategy[start:]
    return "No sizing strategy defined yet."


def _extract_poly_and_odds_price(
    game_data: Dict[str, Any], bet: ActiveBet
) -> tuple:
    """Get Polymarket price for a bet, derive odds_price from it.

    Returns (poly_price, odds_price). poly_price is None if the bet's
    market isn't available on Polymarket.
    """
    poly_price = extract_poly_price_for_bet(
        game_data, bet["bet_type"], bet["pick"], bet.get("line")
    )
    if poly_price is not None:
        return poly_price, poly_price_to_american(poly_price)
    return None, -110


def _fallback_sizing(bets: List[ActiveBet], available: float) -> List[ActiveBet]:
    """Fallback sizing using Half Kelly Criterion."""
    sized = []
    for bet in bets:
        amount = _half_kelly_amount(
            bet.get("odds_price", -110), bet["confidence"], available
        )
        if amount > 0:
            bet["amount"] = amount
            sized.append(bet)
    return sized


async def size_bets(
    proposed_bets: List[ActiveBet],
    balance: float,
    strategy: Optional[str],
    history_summary: Dict[str, Any],
) -> Tuple[List[ActiveBet], List[Dict[str, str]]]:
    """Size bets using LLM. Returns (sized_bets, sizing_skipped)."""
    exposure = get_open_exposure()
    available = balance - exposure
    dollar_pnl = get_dollar_pnl()

    prompt = SIZING_PROMPT.format(
        balance=balance,
        exposure=exposure,
        available=available,
        dollar_pnl=dollar_pnl,
        proposed_bets_json=json.dumps(
            [
                {
                    "id": b["id"],
                    "matchup": b["matchup"],
                    "bet_type": b["bet_type"],
                    "pick": b["pick"],
                    "line": b.get("line"),
                    "confidence": b["confidence"],
                    "units": b["units"],
                    "reasoning": b["reasoning"],
                    "primary_edge": b["primary_edge"],
                    "odds_price": b.get("odds_price", -110),
                    "kelly_recommended": _half_kelly_amount(
                        b.get("odds_price", -110), b["confidence"], available
                    ),
                }
                for b in proposed_bets
            ],
            indent=2,
        ),
        sizing_strategy=_extract_sizing_strategy(strategy),
        history_summary=format_history_summary(history_summary),
    )

    result = await complete_json(prompt, system=SYSTEM_SIZING)
    if not result:
        # Fallback: use Half Kelly sizing
        return _fallback_sizing(proposed_bets, available), []

    # Apply sizing decisions
    sized_bets = []
    skipped = []
    decisions = {d["bet_id"]: d for d in result.get("sizing_decisions", [])}

    for bet in proposed_bets:
        decision = decisions.get(bet["id"])
        if decision and decision.get("action") == "place" and decision.get("amount", 0) > 0:
            kelly_max = _half_kelly_amount(
                bet.get("odds_price", -110), bet["confidence"], available
            )
            if kelly_max <= 0:
                skipped.append({"matchup": bet["matchup"], "reason": "Kelly: no edge at these odds", "game_id": bet["game_id"]})
                continue
            bet["amount"] = min(round(decision["amount"], 2), round(kelly_max * 1.2, 2))
            sized_bets.append(bet)
        else:
            reason = decision.get("reasoning", "No reasoning") if decision else "No sizing decision"
            skipped.append({"matchup": bet["matchup"], "reason": f"Vetoed: {reason}", "game_id": bet["game_id"]})

    return sized_bets, skipped
