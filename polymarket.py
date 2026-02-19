"""Place bets on Polymarket."""

import os

from dotenv import load_dotenv
from typing import Optional

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import AssetType, BalanceAllowanceParams, MarketOrderArgs
from py_clob_client.constants import POLYGON

from polymarket_helpers.gamma import fetch_nba_events, find_market, find_prop_market
from polymarket_helpers.matching import (
    parse_matchup,
    event_matches_matchup,
    pick_matches_outcome,
    prop_pick_to_outcome,
)
from polymarket_helpers.odds import format_price_comparison
from workflow.io import get_active_bets, save_active_bets

POLYMARKET_HOST = "https://clob.polymarket.com"
PRICE_DRIFT_TOLERANCE = 0.05


def resolve_token_id(bet: dict, events: list[dict]) -> tuple[str, float] | None:
    """Find the CLOB token ID and price for a bet from Polymarket events."""
    try:
        away, home = parse_matchup(bet["matchup"])
    except ValueError:
        return None

    for event in events:
        if not event_matches_matchup(event.get("title", ""), away, home):
            continue

        # Player prop bets use a different market lookup
        if bet.get("bet_type") == "player_prop":
            market = find_prop_market(
                event, bet.get("prop_type", ""), bet.get("player_name", ""), bet.get("line")
            )
            if not market:
                continue
            outcomes = market["outcomes"]
            prices = [float(p) for p in market["outcomePrices"]]
            token_ids = market["clobTokenIds"]
            # Map over/under to Yes/No for Polymarket props
            target = prop_pick_to_outcome(bet["pick"])
            for i, outcome in enumerate(outcomes):
                if outcome.lower() == target.lower():
                    return token_ids[i], prices[i]
            continue

        market = find_market(event, bet["bet_type"], bet.get("line"))
        if not market:
            continue

        outcomes = market["outcomes"]
        prices = [float(p) for p in market["outcomePrices"]]
        token_ids = market["clobTokenIds"]

        for i, outcome in enumerate(outcomes):
            if pick_matches_outcome(bet["pick"], outcome):
                return token_ids[i], prices[i]

    return None


def create_clob_client(private_key: str, funder: str) -> ClobClient:
    """Create an authenticated ClobClient."""
    client = ClobClient(
        host=POLYMARKET_HOST,
        chain_id=POLYGON,
        key=private_key,
        signature_type=1,
        funder=funder,
    )
    client.set_api_creds(client.create_or_derive_api_creds())
    return client


def place_bet(client: ClobClient, token_id: str, amount: float) -> dict:
    """Place a market buy order on Polymarket."""
    order_args = MarketOrderArgs(token_id=token_id, amount=amount, side="BUY")
    signed_order = client.create_market_order(order_args)
    return client.post_order(signed_order, orderType="FOK")


def sell_position(client: ClobClient, token_id: str, shares: float) -> dict:
    """Sell shares of a position on Polymarket."""
    order_args = MarketOrderArgs(token_id=token_id, amount=shares, side="SELL")
    signed_order = client.create_market_order(order_args)
    return client.post_order(signed_order, orderType="FOK")


def get_polymarket_balance() -> Optional[float]:
    """Query USDC balance from Polymarket. Returns None if creds missing or API fails."""
    load_dotenv()
    private_key = os.environ.get("POLYMARKET_PRIVATE_KEY")
    funder = os.environ.get("POLYMARKET_FUNDER")
    if not private_key or not funder:
        return None
    try:
        client = create_clob_client(private_key, funder)
        result = client.get_balance_allowance(
            BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
        )
        return float(result.get("balance", 0))
    except Exception:
        return None


def run() -> None:
    """Load unplaced active bets, resolve markets, and place orders."""
    load_dotenv()

    private_key = os.environ.get("POLYMARKET_PRIVATE_KEY")
    funder = os.environ.get("POLYMARKET_FUNDER")
    if not private_key or not funder:
        print("Error: POLYMARKET_PRIVATE_KEY and POLYMARKET_FUNDER must be set")
        return

    all_active = get_active_bets()
    bets = [b for b in all_active if not b.get("placed_polymarket")]
    if not bets:
        print("No unplaced active bets")
        return

    # Group bets by date for event fetching
    dates = sorted({b["date"] for b in bets})
    print(f"Found {len(bets)} unplaced bet(s) across {len(dates)} date(s)")

    client = create_clob_client(private_key, funder)

    placed = 0
    skipped = 0

    for date in dates:
        date_bets = [b for b in bets if b["date"] == date]
        events = fetch_nba_events(date)
        if not events:
            print(f"\n{date}: no Polymarket events found, skipping {len(date_bets)} bet(s)")
            skipped += len(date_bets)
            continue

        print(f"\n{date}: {len(events)} event(s), {len(date_bets)} bet(s)")

        for bet in date_bets:
            if bet.get("bet_type") == "player_prop":
                label = f"{bet['matchup']} | {bet.get('player_name', '?')} {bet.get('prop_type', '?')} {bet['pick']} {bet.get('line', '?')}"
            else:
                label = f"{bet['matchup']} | {bet['bet_type']} {bet['pick']}"
            result = resolve_token_id(bet, events)

            if not result:
                print(f"  SKIP: {label} -> no matching market")
                skipped += 1
                continue

            token_id, poly_price = result
            odds_price = bet.get("odds_price")
            if odds_price:
                print(f"  {format_price_comparison(odds_price, poly_price)}")

            # Price drift gate: skip if live price moved too far from analysis price
            analysis_price = bet.get("poly_price")
            if analysis_price is not None:
                drift = abs(poly_price - analysis_price)
                if drift > PRICE_DRIFT_TOLERANCE:
                    print(f"  SKIP: {label} -> price drifted {drift:.2f} "
                          f"(was {analysis_price:.2f}, now {poly_price:.2f})")
                    skipped += 1
                    continue

            amount = bet.get("amount", 0)
            if amount <= 0:
                print(f"  SKIP: {label} -> no amount set")
                skipped += 1
                continue

            try:
                resp = place_bet(client, token_id, amount)
                print(f"  OK:   {label} -> ${amount:.2f} placed")
                print(f"        Response: {resp}")
                bet["placed_polymarket"] = True
                placed += 1
            except Exception as e:
                print(f"  FAIL: {label} -> {e}")
                skipped += 1

    save_active_bets(all_active)
    print(f"\nDone: {placed} placed, {skipped} skipped")


def main():
    run()


if __name__ == "__main__":
    main()
