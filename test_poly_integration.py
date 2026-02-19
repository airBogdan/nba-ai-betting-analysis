"""Temporary integration test — real Polymarket API calls.

Run:  python test_poly_integration.py [YYYY-MM-DD]
Default date: today.
"""

import json
import sys
from datetime import date

from polymarket_helpers.gamma import extract_polymarket_odds, fetch_nba_events
from polymarket_helpers.matching import event_matches_matchup
from polymarket_helpers.odds import poly_price_to_american, american_to_implied_probability
from workflow.analyze.sizing import _extract_poly_and_odds_price
from workflow.analyze.gamedata import load_games_for_date
from workflow.polymarket_prices import extract_poly_price_for_bet, fetch_polymarket_prices

# Team name mapping from Polymarket short names to full names
SHORT_TO_FULL = {
    "hawks": ("Atlanta Hawks", "ATL"), "celtics": ("Boston Celtics", "BOS"),
    "nets": ("Brooklyn Nets", "BKN"), "hornets": ("Charlotte Hornets", "CHA"),
    "bulls": ("Chicago Bulls", "CHI"), "cavaliers": ("Cleveland Cavaliers", "CLE"),
    "mavericks": ("Dallas Mavericks", "DAL"), "nuggets": ("Denver Nuggets", "DEN"),
    "pistons": ("Detroit Pistons", "DET"), "warriors": ("Golden State Warriors", "GSW"),
    "rockets": ("Houston Rockets", "HOU"), "pacers": ("Indiana Pacers", "IND"),
    "clippers": ("LA Clippers", "LAC"), "lakers": ("Los Angeles Lakers", "LAL"),
    "grizzlies": ("Memphis Grizzlies", "MEM"), "heat": ("Miami Heat", "MIA"),
    "bucks": ("Milwaukee Bucks", "MIL"), "timberwolves": ("Minnesota Timberwolves", "MIN"),
    "pelicans": ("New Orleans Pelicans", "NOP"), "knicks": ("New York Knicks", "NYK"),
    "thunder": ("Oklahoma City Thunder", "OKC"), "magic": ("Orlando Magic", "ORL"),
    "76ers": ("Philadelphia 76ers", "PHI"), "suns": ("Phoenix Suns", "PHX"),
    "trail blazers": ("Portland Trail Blazers", "POR"), "kings": ("Sacramento Kings", "SAC"),
    "spurs": ("San Antonio Spurs", "SAS"), "raptors": ("Toronto Raptors", "TOR"),
    "jazz": ("Utah Jazz", "UTA"), "wizards": ("Washington Wizards", "WAS"),
}


def _teams_from_event(event: dict) -> tuple[str, str] | None:
    """Extract full team names from a Polymarket event title like 'Bucks vs. Thunder'."""
    title = event.get("title", "")
    # Remove "vs." and split
    parts = title.replace("vs.", "").replace("vs", "").split()
    parts = [p.strip().lower() for p in parts if p.strip()]

    found = []
    # Check two-word names first
    for i in range(len(parts) - 1):
        two = f"{parts[i]} {parts[i+1]}"
        if two in SHORT_TO_FULL:
            found.append(SHORT_TO_FULL[two][0])
    # Then single words
    for p in parts:
        if p in SHORT_TO_FULL and SHORT_TO_FULL[p][0] not in found:
            found.append(SHORT_TO_FULL[p][0])

    if len(found) == 2:
        return found[0], found[1]
    return None


def _make_fake_game(away: str, home: str) -> dict:
    """Create a minimal game dict for testing."""
    return {
        "matchup": {"team1": home, "team2": away, "home_team": home},
    }


def main():
    target_date = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
    print(f"=== Polymarket Integration Test — {target_date} ===\n")

    # --- 1. fetch_nba_events (real API) ---
    print("1. fetch_nba_events()")
    events = fetch_nba_events(target_date)
    print(f"   Found {len(events)} event(s)")
    if not events:
        print("   No events found. Try a date with NBA games.")
        return

    for ev in events:
        print(f"   - {ev.get('title')}  (ticker: {ev.get('ticker')})")
        n_markets = len(ev.get("markets", []))
        print(f"     {n_markets} market(s)")

    # --- 2. extract_polymarket_odds on each event ---
    print("\n2. extract_polymarket_odds()")
    for ev in events:
        odds = extract_polymarket_odds(ev)
        print(f"   {ev.get('title')}:")
        if odds.get("moneyline"):
            ml = odds["moneyline"]
            print(f"     ML: {list(zip(ml['outcomes'], ml['prices']))}")
        for sp in odds.get("available_spreads", []):
            print(f"     Spread {sp['line']}: {list(zip(sp['outcomes'], sp['prices']))}")
        for tot in odds.get("available_totals", []):
            print(f"     Total {tot['line']}: {list(zip(tot['outcomes'], tot['prices']))}")
        if not odds:
            print("     (no active markets)")

    # --- 3. poly_price_to_american on real prices ---
    print("\n3. poly_price_to_american() on real prices")
    first_odds = extract_polymarket_odds(events[0])
    if first_odds.get("moneyline"):
        ml = first_odds["moneyline"]
        for outcome, price in zip(ml["outcomes"], ml["prices"]):
            american = poly_price_to_american(price)
            roundtrip = american_to_implied_probability(american)
            print(f"   {outcome}: price={price:.3f} -> american={american:+d} -> roundtrip={roundtrip:.3f}")

    # --- 4. fetch_polymarket_prices with real or fake game data ---
    print("\n4. fetch_polymarket_prices()")

    # Try real matchup files first
    games = load_games_for_date(target_date)
    if games:
        print(f"   Using {len(games)} real matchup file(s)")
    else:
        # Build fake game dicts from the Polymarket events
        print(f"   No matchup files for {target_date}. Building fake games from events.")
        games = []
        for ev in events:
            teams = _teams_from_event(ev)
            if teams:
                # Ticker format: nba-AWAY-HOME-date → second team is home
                away, home = teams[0], teams[1]
                ticker = ev.get("ticker", "")
                # Use ticker hint: last team in ticker is home
                parts = ticker.split("-")
                if len(parts) >= 4:
                    home_abbr = parts[2].upper()
                    # If second found team's short name matches home_abbr, keep order
                    # Otherwise swap (best effort)
                    for short, (full, abbr) in SHORT_TO_FULL.items():
                        if abbr == home_abbr and full == away:
                            away, home = home, away
                            break
                games.append(_make_fake_game(away, home))
                print(f"   Built: {away} @ {home}")

    fetch_polymarket_prices(games, target_date)

    matched = [g for g in games if g.get("polymarket_odds")]
    unmatched = [g for g in games if not g.get("polymarket_odds")]
    print(f"   Matched: {len(matched)}, Unmatched: {len(unmatched)}")

    for g in unmatched:
        m = g.get("matchup", {})
        print(f"   UNMATCHED: {m.get('team2', '?')} @ {m.get('team1', '?')}")

    if not matched:
        print("   No matched games — can't test further.")
        return

    # --- 5. extract_poly_price_for_bet on real data ---
    print("\n5. extract_poly_price_for_bet() on matched games")
    for g in matched[:3]:
        m = g.get("matchup", {})
        home = m.get("home_team", "")
        away = m.get("team2") if m.get("team1") == home else m.get("team1", "")
        print(f"\n   {away} @ {home}:")

        # Moneyline
        for team in [home, away]:
            price = extract_poly_price_for_bet(g, "moneyline", team, None)
            if price is not None:
                american = poly_price_to_american(price)
                print(f"     ML {team}: {price:.3f} (≈ {american:+d})")
            else:
                print(f"     ML {team}: not found")

        # Spreads
        for sp in g.get("polymarket_odds", {}).get("available_spreads", []):
            for outcome in sp["outcomes"]:
                price = extract_poly_price_for_bet(g, "spread", outcome, sp["line"])
                label = f"{outcome} {sp['line']:+.1f}"
                print(f"     Spread {label}: {price:.3f}" if price else f"     Spread {label}: not found")

        # Totals
        for tot in g.get("polymarket_odds", {}).get("available_totals", []):
            for pick in ["over", "under"]:
                price = extract_poly_price_for_bet(g, "total", pick, tot["line"])
                label = f"{pick} {tot['line']:.1f}"
                print(f"     Total {label}: {price:.3f}" if price else f"     Total {label}: not found")

    # --- 6. _extract_poly_and_odds_price end-to-end ---
    print("\n6. _extract_poly_and_odds_price() end-to-end")
    for g in matched[:2]:
        m = g.get("matchup", {})
        home = m.get("home_team", "")
        away = m.get("team2") if m.get("team1") == home else m.get("team1", "")
        matchup_str = f"{away} @ {home}"
        print(f"\n   {matchup_str}:")

        # Moneyline bet
        fake_bet = {"bet_type": "moneyline", "pick": home, "matchup": matchup_str}
        poly_p, odds_p = _extract_poly_and_odds_price(g, fake_bet)
        print(f"     ML {home}: poly={poly_p}, odds_price={odds_p}")
        assert poly_p is not None, "Expected poly_price for moneyline"
        assert odds_p != -110 or poly_p == american_to_implied_probability(-110), \
            "odds_price should be derived from poly_price"

        # Bet on a line that doesn't exist on Polymarket — should fallback
        fake_bet2 = {"bet_type": "spread", "pick": home, "line": -99.5, "matchup": matchup_str}
        poly_p2, odds_p2 = _extract_poly_and_odds_price(g, fake_bet2)
        print(f"     Spread {home} -99.5 (should fallback): poly={poly_p2}, odds_price={odds_p2}")
        assert poly_p2 is None, "Expected None poly_price for nonexistent line"

    print("\n=== All checks passed ===")


if __name__ == "__main__":
    main()
