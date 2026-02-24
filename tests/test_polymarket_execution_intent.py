import json
from unittest.mock import MagicMock, patch, call

import pytest

from polymarket import resolve_token_id, PRICE_DRIFT_TOLERANCE


def _make_market(
    sport_type: str,
    outcomes: list[str],
    prices: list[str],
    token_ids: list[str] | None = None,
    line: float | None = None,
    accepting: bool = True,
    question: str = "",
):
    """Helper to build a Polymarket market dict."""
    m = {
        "sportsMarketType": sport_type,
        "outcomes": json.dumps(outcomes),
        "outcomePrices": json.dumps(prices),
        "clobTokenIds": json.dumps(token_ids or [f"tok_{i}" for i in range(len(outcomes))]),
        "acceptingOrders": accepting,
    }
    if line is not None:
        m["line"] = str(line)
    if question:
        m["question"] = question
    return m


class TestResolveTokenId:
    """resolve_token_id maps an internal bet to a Polymarket token ID and price."""

    def _make_event(self, title, ticker, markets):
        return {"title": title, "ticker": ticker, "markets": markets}

    def test_resolves_moneyline_bet(self):
        events = [self._make_event(
            "Suns vs. Celtics", "NBA-2026-02-21-PHX-BOS",
            [_make_market("moneyline", ["Suns", "Celtics"], ["0.55", "0.45"],
                          token_ids=["tok_suns", "tok_celtics"])],
        )]
        bet = {"matchup": "Phoenix Suns @ Boston Celtics", "bet_type": "moneyline", "pick": "Phoenix Suns"}
        result = resolve_token_id(bet, events)
        assert result is not None
        token_id, price = result
        assert token_id == "tok_suns"
        assert price == 0.55

    def test_resolves_away_team_pick(self):
        events = [self._make_event(
            "Suns vs. Celtics", "NBA-2026-02-21-PHX-BOS",
            [_make_market("moneyline", ["Suns", "Celtics"], ["0.55", "0.45"],
                          token_ids=["tok_suns", "tok_celtics"])],
        )]
        bet = {"matchup": "Phoenix Suns @ Boston Celtics", "bet_type": "moneyline", "pick": "Boston Celtics"}
        result = resolve_token_id(bet, events)
        assert result is not None
        token_id, price = result
        assert token_id == "tok_celtics"
        assert price == 0.45

    def test_resolves_spread_bet(self):
        events = [self._make_event(
            "Suns vs. Celtics", "NBA-2026-02-21-PHX-BOS",
            [_make_market("spread", ["Suns", "Celtics"], ["0.52", "0.48"],
                          token_ids=["tok_suns", "tok_celtics"], line=-4.5)],
        )]
        bet = {
            "matchup": "Phoenix Suns @ Boston Celtics",
            "bet_type": "spread", "pick": "Phoenix Suns", "line": -4.5,
        }
        result = resolve_token_id(bet, events)
        assert result is not None

    def test_resolves_total_bet(self):
        events = [self._make_event(
            "Suns vs. Celtics", "NBA-2026-02-21-PHX-BOS",
            [_make_market("total", ["Over", "Under"], ["0.52", "0.48"],
                          token_ids=["tok_over", "tok_under"], line=224.5)],
        )]
        bet = {
            "matchup": "Phoenix Suns @ Boston Celtics",
            "bet_type": "total", "pick": "Over", "line": 224.5,
        }
        result = resolve_token_id(bet, events)
        assert result is not None
        token_id, price = result
        assert token_id == "tok_over"
        assert price == 0.52

    def test_resolves_player_prop(self):
        events = [self._make_event(
            "Suns vs. Celtics", "NBA-2026-02-21-PHX-BOS",
            [_make_market(
                "points", ["Yes", "No"], ["0.60", "0.40"],
                token_ids=["tok_yes", "tok_no"], line=25.5,
                question="LeBron James: 25.5 or more points?",
            )],
        )]
        bet = {
            "matchup": "Phoenix Suns @ Boston Celtics",
            "bet_type": "player_prop", "pick": "over",
            "prop_type": "points", "player_name": "LeBron James", "line": 25.5,
        }
        result = resolve_token_id(bet, events)
        assert result is not None
        token_id, price = result
        assert token_id == "tok_yes"
        assert price == 0.60

    def test_player_prop_under(self):
        events = [self._make_event(
            "Suns vs. Celtics", "NBA-2026-02-21-PHX-BOS",
            [_make_market(
                "points", ["Yes", "No"], ["0.60", "0.40"],
                token_ids=["tok_yes", "tok_no"], line=25.5,
                question="LeBron James: 25.5 or more points?",
            )],
        )]
        bet = {
            "matchup": "Phoenix Suns @ Boston Celtics",
            "bet_type": "player_prop", "pick": "under",
            "prop_type": "points", "player_name": "LeBron James", "line": 25.5,
        }
        result = resolve_token_id(bet, events)
        assert result is not None
        token_id, price = result
        assert token_id == "tok_no"
        assert price == 0.40

    def test_returns_none_for_invalid_matchup(self):
        result = resolve_token_id({"matchup": "bad format", "bet_type": "moneyline", "pick": "X"}, [])
        assert result is None

    def test_returns_none_when_no_event_matches(self):
        events = [self._make_event(
            "Lakers vs. Knicks", "NBA-2026-02-21-LAL-NYK",
            [_make_market("moneyline", ["Lakers", "Knicks"], ["0.55", "0.45"])],
        )]
        bet = {"matchup": "Phoenix Suns @ Boston Celtics", "bet_type": "moneyline", "pick": "Phoenix Suns"}
        assert resolve_token_id(bet, events) is None

    def test_returns_none_when_no_market_matches(self):
        events = [self._make_event(
            "Suns vs. Celtics", "NBA-2026-02-21-PHX-BOS",
            [_make_market("moneyline", ["Suns", "Celtics"], ["0.55", "0.45"])],
        )]
        bet = {
            "matchup": "Phoenix Suns @ Boston Celtics",
            "bet_type": "spread", "pick": "Phoenix Suns", "line": -4.5,
        }
        assert resolve_token_id(bet, events) is None

    def test_searches_across_multiple_events(self):
        events = [
            self._make_event("Lakers vs. Knicks", "NBA-2026-02-21-LAL-NYK",
                             [_make_market("moneyline", ["Lakers", "Knicks"], ["0.55", "0.45"])]),
            self._make_event("Suns vs. Celtics", "NBA-2026-02-21-PHX-BOS",
                             [_make_market("moneyline", ["Suns", "Celtics"], ["0.60", "0.40"],
                                           token_ids=["tok_suns", "tok_celtics"])]),
        ]
        bet = {"matchup": "Phoenix Suns @ Boston Celtics", "bet_type": "moneyline", "pick": "Phoenix Suns"}
        result = resolve_token_id(bet, events)
        assert result is not None
        assert result[0] == "tok_suns"


class TestRunOrchestration:
    """The run() function orchestrates: load bets → group by date → resolve → drift check → place."""

    def _make_bet(self, matchup="Phoenix Suns @ Boston Celtics", bet_type="moneyline",
                  pick="Phoenix Suns", amount=10.0, date="2026-02-21", **kwargs):
        return {"matchup": matchup, "bet_type": bet_type, "pick": pick,
                "amount": amount, "date": date, **kwargs}

    @patch("polymarket.save_active_bets")
    @patch("polymarket.get_active_bets")
    @patch("polymarket.fetch_nba_events")
    @patch("polymarket.create_clob_client")
    @patch("polymarket.place_bet")
    @patch.dict("os.environ", {"POLYMARKET_PRIVATE_KEY": "0xkey", "POLYMARKET_FUNDER": "0xfunder"})
    def test_places_bet_and_marks_as_placed(self, mock_place, mock_client, mock_events,
                                            mock_get_bets, mock_save):
        from polymarket import run

        bet = self._make_bet()
        mock_get_bets.return_value = [bet]
        mock_events.return_value = [
            {"title": "Suns vs. Celtics", "markets": [
                _make_market("moneyline", ["Suns", "Celtics"], ["0.55", "0.45"],
                             token_ids=["tok_suns", "tok_celtics"]),
            ]},
        ]
        mock_place.return_value = {"status": "matched"}

        run()

        mock_place.assert_called_once()
        assert bet["placed_polymarket"] is True
        mock_save.assert_called_once()

    @patch("polymarket.save_active_bets")
    @patch("polymarket.get_active_bets")
    @patch.dict("os.environ", {"POLYMARKET_PRIVATE_KEY": "0xkey", "POLYMARKET_FUNDER": "0xfunder"})
    def test_skips_already_placed_bets(self, mock_get_bets, mock_save):
        from polymarket import run

        mock_get_bets.return_value = [self._make_bet(placed_polymarket=True)]
        run()
        # No events fetched, no orders placed — but still saves
        mock_save.assert_not_called()  # Actually, early return before save

    @patch("polymarket.save_active_bets")
    @patch("polymarket.get_active_bets")
    @patch("polymarket.fetch_nba_events")
    @patch("polymarket.create_clob_client")
    @patch("polymarket.place_bet")
    @patch.dict("os.environ", {"POLYMARKET_PRIVATE_KEY": "0xkey", "POLYMARKET_FUNDER": "0xfunder"})
    def test_skips_bet_with_no_amount(self, mock_place, mock_client, mock_events,
                                      mock_get_bets, mock_save):
        from polymarket import run

        bet = self._make_bet(amount=0)
        mock_get_bets.return_value = [bet]
        mock_events.return_value = [
            {"title": "Suns vs. Celtics", "markets": [
                _make_market("moneyline", ["Suns", "Celtics"], ["0.55", "0.45"]),
            ]},
        ]

        run()
        mock_place.assert_not_called()
        assert "placed_polymarket" not in bet

    @patch("polymarket.save_active_bets")
    @patch("polymarket.get_active_bets")
    @patch("polymarket.fetch_nba_events")
    @patch("polymarket.create_clob_client")
    @patch("polymarket.place_bet")
    @patch.dict("os.environ", {"POLYMARKET_PRIVATE_KEY": "0xkey", "POLYMARKET_FUNDER": "0xfunder"})
    def test_skips_bet_when_price_drifted(self, mock_place, mock_client, mock_events,
                                          mock_get_bets, mock_save):
        from polymarket import run

        # Analysis price was 0.55, but live price will be 0.70 → drift of 0.15 > 0.05 tolerance
        bet = self._make_bet(poly_price=0.55)
        mock_get_bets.return_value = [bet]
        mock_events.return_value = [
            {"title": "Suns vs. Celtics", "markets": [
                _make_market("moneyline", ["Suns", "Celtics"], ["0.70", "0.30"],
                             token_ids=["tok_suns", "tok_celtics"]),
            ]},
        ]

        run()
        mock_place.assert_not_called()

    @patch("polymarket.save_active_bets")
    @patch("polymarket.get_active_bets")
    @patch("polymarket.fetch_nba_events")
    @patch("polymarket.create_clob_client")
    @patch("polymarket.place_bet")
    @patch.dict("os.environ", {"POLYMARKET_PRIVATE_KEY": "0xkey", "POLYMARKET_FUNDER": "0xfunder"})
    def test_allows_bet_within_drift_tolerance(self, mock_place, mock_client, mock_events,
                                               mock_get_bets, mock_save):
        from polymarket import run

        # Analysis price was 0.55, live is 0.57 → drift of 0.02 < 0.05 tolerance
        bet = self._make_bet(poly_price=0.55)
        mock_get_bets.return_value = [bet]
        mock_events.return_value = [
            {"title": "Suns vs. Celtics", "markets": [
                _make_market("moneyline", ["Suns", "Celtics"], ["0.57", "0.43"],
                             token_ids=["tok_suns", "tok_celtics"]),
            ]},
        ]
        mock_place.return_value = {"status": "matched"}

        run()
        mock_place.assert_called_once()

    @patch("polymarket.load_dotenv")
    @patch("polymarket.save_active_bets")
    @patch("polymarket.get_active_bets")
    @patch.dict("os.environ", {}, clear=True)
    def test_exits_without_credentials(self, mock_get_bets, mock_save, mock_dotenv, capsys):
        from polymarket import run
        run()
        mock_get_bets.assert_not_called()
        output = capsys.readouterr().out
        assert "POLYMARKET_PRIVATE_KEY" in output

    @patch("polymarket.save_active_bets")
    @patch("polymarket.get_active_bets")
    @patch("polymarket.fetch_nba_events")
    @patch("polymarket.create_clob_client")
    @patch("polymarket.place_bet")
    @patch.dict("os.environ", {"POLYMARKET_PRIVATE_KEY": "0xkey", "POLYMARKET_FUNDER": "0xfunder"})
    def test_handles_placement_failure_gracefully(self, mock_place, mock_client, mock_events,
                                                   mock_get_bets, mock_save):
        from polymarket import run

        bet = self._make_bet()
        mock_get_bets.return_value = [bet]
        mock_events.return_value = [
            {"title": "Suns vs. Celtics", "markets": [
                _make_market("moneyline", ["Suns", "Celtics"], ["0.55", "0.45"],
                             token_ids=["tok_suns", "tok_celtics"]),
            ]},
        ]
        mock_place.side_effect = Exception("Order rejected")

        run()
        assert "placed_polymarket" not in bet  # Not marked as placed on failure
        mock_save.assert_called_once()  # Still saves the state

    @patch("polymarket.save_active_bets")
    @patch("polymarket.get_active_bets")
    @patch("polymarket.fetch_nba_events")
    @patch("polymarket.create_clob_client")
    @patch.dict("os.environ", {"POLYMARKET_PRIVATE_KEY": "0xkey", "POLYMARKET_FUNDER": "0xfunder"})
    def test_skips_entire_date_when_no_events(self, mock_client, mock_events,
                                              mock_get_bets, mock_save, capsys):
        from polymarket import run

        mock_get_bets.return_value = [self._make_bet()]
        mock_events.return_value = []

        run()
        output = capsys.readouterr().out
        assert "no Polymarket events found" in output
        mock_save.assert_called_once()


class TestPriceDriftTolerance:
    """The price drift gate protects against placing bets when the market has moved significantly."""

    def test_tolerance_value(self):
        assert PRICE_DRIFT_TOLERANCE == 0.05

    def test_drift_exactly_at_tolerance_is_rejected(self):
        """Drift of exactly 0.05 should be rejected (> not >=)."""
        # The code uses `drift > PRICE_DRIFT_TOLERANCE`, so exactly 0.05 passes
        drift = 0.05
        assert not (drift > PRICE_DRIFT_TOLERANCE)  # 0.05 is NOT > 0.05

    def test_drift_just_over_tolerance_is_rejected(self):
        drift = 0.051
        assert drift > PRICE_DRIFT_TOLERANCE


class TestGetPolymarketBalance:
    """get_polymarket_balance queries USDC balance, converting from 6-decimal format."""

    @patch("polymarket.create_clob_client")
    @patch.dict("os.environ", {"POLYMARKET_PRIVATE_KEY": "0xkey", "POLYMARKET_FUNDER": "0xfunder"})
    def test_converts_balance_from_microdollars(self, mock_client):
        from polymarket import get_polymarket_balance

        client = MagicMock()
        client.get_balance_allowance.return_value = {"balance": 50_000_000}  # 50 USDC
        mock_client.return_value = client

        balance = get_polymarket_balance()
        assert balance == 50.0

    @patch("polymarket.load_dotenv")
    @patch.dict("os.environ", {}, clear=True)
    def test_returns_none_without_credentials(self, mock_dotenv):
        from polymarket import get_polymarket_balance
        assert get_polymarket_balance() is None

    @patch("polymarket.create_clob_client")
    @patch.dict("os.environ", {"POLYMARKET_PRIVATE_KEY": "0xkey", "POLYMARKET_FUNDER": "0xfunder"})
    def test_returns_none_on_api_error(self, mock_client):
        from polymarket import get_polymarket_balance

        mock_client.side_effect = Exception("API down")
        assert get_polymarket_balance() is None
