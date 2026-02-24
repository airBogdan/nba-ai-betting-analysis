import json
from unittest.mock import MagicMock, patch, call

import pytest

from polymarket_helpers.matching import (
    parse_matchup,
    event_matches_matchup,
    pick_matches_outcome,
    prop_pick_to_outcome,
    _extract_short_name,
)


class TestParseMatchup:
    """parse_matchup splits 'Away @ Home' into the two team names."""

    def test_standard_matchup(self):
        away, home = parse_matchup("Phoenix Suns @ Boston Celtics")
        assert away == "Phoenix Suns"
        assert home == "Boston Celtics"

    def test_rejects_missing_at_sign(self):
        with pytest.raises(ValueError):
            parse_matchup("Phoenix Suns vs Boston Celtics")

    def test_rejects_empty_string(self):
        with pytest.raises(ValueError):
            parse_matchup("")

    def test_preserves_whitespace_within_names(self):
        away, home = parse_matchup("Portland Trail Blazers @ Golden State Warriors")
        assert away == "Portland Trail Blazers"
        assert home == "Golden State Warriors"


class TestExtractShortName:
    """Short name extraction turns full team names into their last word (or two for Trail Blazers)."""

    def test_single_word_team(self):
        assert _extract_short_name("Boston Celtics") == "celtics"

    def test_two_word_suffix_trail_blazers(self):
        assert _extract_short_name("Portland Trail Blazers") == "trail blazers"

    def test_76ers(self):
        assert _extract_short_name("Philadelphia 76ers") == "76ers"

    def test_just_team_name(self):
        # Even a bare name should work
        assert _extract_short_name("Celtics") == "celtics"


class TestEventMatchesMatchup:
    """Event titles from Polymarket (like 'Suns vs. Celtics') must match our 'Away @ Home' format."""

    def test_standard_match(self):
        assert event_matches_matchup("Suns vs. Celtics", "Phoenix Suns", "Boston Celtics")

    def test_order_irrelevant_in_title(self):
        # Polymarket title order might differ from away/home
        assert event_matches_matchup("Celtics vs. Suns", "Phoenix Suns", "Boston Celtics")

    def test_no_match_wrong_teams(self):
        assert not event_matches_matchup("Lakers vs. Knicks", "Phoenix Suns", "Boston Celtics")

    def test_partial_match_fails(self):
        # Both teams must appear
        assert not event_matches_matchup("Suns vs. Lakers", "Phoenix Suns", "Boston Celtics")

    def test_trail_blazers_in_title(self):
        assert event_matches_matchup(
            "Trail Blazers vs. Lakers",
            "Portland Trail Blazers",
            "Los Angeles Lakers",
        )

    def test_case_insensitive(self):
        assert event_matches_matchup("SUNS VS. CELTICS", "Phoenix Suns", "Boston Celtics")


class TestPickMatchesOutcome:
    """A bet pick (our format) must match a Polymarket outcome."""

    def test_exact_match(self):
        assert pick_matches_outcome("Over", "Over")

    def test_case_insensitive(self):
        assert pick_matches_outcome("over", "Over")

    def test_full_team_name_matches_short_outcome(self):
        # Our pick is "Phoenix Suns", Polymarket outcome is "Suns"
        assert pick_matches_outcome("Phoenix Suns", "suns")

    def test_no_match(self):
        assert not pick_matches_outcome("Phoenix Suns", "Celtics")


class TestPropPickToOutcome:
    """Player prop bets use over/under; Polymarket uses Yes/No."""

    def test_over_maps_to_yes(self):
        assert prop_pick_to_outcome("over") == "Yes"

    def test_under_maps_to_no(self):
        assert prop_pick_to_outcome("under") == "No"

    def test_case_insensitive_over(self):
        assert prop_pick_to_outcome("Over") == "Yes"

    def test_case_insensitive_under(self):
        assert prop_pick_to_outcome("Under") == "No"

    def test_anything_else_maps_to_no(self):
        # The function treats non-"over" as "No" — this is the actual behavior
        assert prop_pick_to_outcome("push") == "No"
