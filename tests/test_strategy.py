"""Tests for workflow.strategy module."""

import pytest

from workflow.prompts import MIN_ACTIONABLE_SAMPLE, format_history_summary
from workflow.strategy import (
    MAX_CHANGE_LOG_ENTRIES,
    _compute_summary,
    _parse_sections,
    _rebuild_strategy,
    aggregate_reflections,
    append_change_log,
    apply_adjustments,
    format_recent_bets,
    format_recent_prop_bets,
)

SAMPLE_STRATEGY = """# NBA Betting Strategy

## Core Principles
- Rule 1
- Rule 2

## Confidence Guidelines
- High: 5+ point edge
- Medium: 3-4 points

## What to Avoid
- Chasing losses
"""


class TestParseSections:
    def test_parses_preamble_and_sections(self):
        sections = _parse_sections(SAMPLE_STRATEGY)
        assert sections[0][0] is None  # preamble
        assert "# NBA Betting Strategy" in sections[0][1]
        headers = [h for h, _ in sections if h is not None]
        assert headers == ["Core Principles", "Confidence Guidelines", "What to Avoid"]

    def test_section_content_preserved(self):
        sections = _parse_sections(SAMPLE_STRATEGY)
        # Core Principles is index 1
        assert "- Rule 1" in sections[1][1]
        assert "- Rule 2" in sections[1][1]

    def test_roundtrip(self):
        """parse then rebuild should produce identical text."""
        sections = _parse_sections(SAMPLE_STRATEGY)
        rebuilt = _rebuild_strategy(sections)
        assert rebuilt == SAMPLE_STRATEGY


class TestApplyAdjustments:
    def test_modify_existing_section(self):
        adjustments = [
            {
                "section": "Confidence Guidelines",
                "updated_content": "- High: 6+ point edge\n- Medium: 3-5 points",
                "change_description": "test",
                "reasoning": "test",
            }
        ]
        result = apply_adjustments(SAMPLE_STRATEGY, adjustments)
        assert "- High: 6+ point edge" in result
        assert "- High: 5+ point edge" not in result
        # Other sections untouched
        assert "- Rule 1" in result
        assert "- Chasing losses" in result

    def test_add_new_section(self):
        adjustments = [
            {
                "section": "Performance Notes",
                "updated_content": "Record: 10-5",
                "change_description": "test",
                "reasoning": "test",
            }
        ]
        result = apply_adjustments(SAMPLE_STRATEGY, adjustments)
        assert "## Performance Notes" in result
        assert "Record: 10-5" in result
        # Original sections still there
        assert "## Core Principles" in result

    def test_new_section_inserted_before_change_log(self):
        strategy_with_log = SAMPLE_STRATEGY + "\n## Change Log\nold entry\n"
        adjustments = [
            {
                "section": "New Rules",
                "updated_content": "- New rule",
                "change_description": "test",
                "reasoning": "test",
            }
        ]
        result = apply_adjustments(strategy_with_log, adjustments)
        new_rules_pos = result.index("## New Rules")
        change_log_pos = result.index("## Change Log")
        assert new_rules_pos < change_log_pos

    def test_strips_duplicate_header_from_content(self):
        adjustments = [
            {
                "section": "Confidence Guidelines",
                "updated_content": "## Confidence Guidelines\n- High: 6+ point edge",
                "change_description": "test",
                "reasoning": "test",
            }
        ]
        result = apply_adjustments(SAMPLE_STRATEGY, adjustments)
        assert result.count("## Confidence Guidelines") == 1
        assert "- High: 6+ point edge" in result

    def test_empty_adjustments_returns_unchanged(self):
        result = apply_adjustments(SAMPLE_STRATEGY, [])
        assert result == SAMPLE_STRATEGY


class TestAppendChangeLog:
    def test_creates_change_log_section(self):
        adjustments = [
            {
                "section": "Core Principles",
                "change_description": "Added rule 3",
                "reasoning": "Data shows it works",
                "updated_content": "",
            }
        ]
        result = append_change_log(SAMPLE_STRATEGY, adjustments, "2026-02-09")
        assert "## Change Log" in result
        assert "### 2026-02-09" in result
        assert "**Core Principles**: Added rule 3" in result
        assert "_Data shows it works_" in result

    def test_prepends_to_existing_log(self):
        strategy_with_log = (
            SAMPLE_STRATEGY + "\n## Change Log\n### 2026-02-08\n- old change\n"
        )
        adjustments = [
            {
                "section": "X",
                "change_description": "new change",
                "reasoning": "reason",
                "updated_content": "",
            }
        ]
        result = append_change_log(strategy_with_log, adjustments, "2026-02-09")
        # New entry comes before old
        pos_new = result.index("### 2026-02-09")
        pos_old = result.index("### 2026-02-08")
        assert pos_new < pos_old

    def test_trims_old_entries(self):
        # Build strategy with MAX entries already
        log_entries = []
        for i in range(MAX_CHANGE_LOG_ENTRIES + 2):
            log_entries.append(f"### 2026-01-{i+1:02d}\n- change {i}")
        strategy_with_full_log = (
            SAMPLE_STRATEGY + "\n## Change Log\n" + "\n\n".join(log_entries) + "\n"
        )
        adjustments = [
            {
                "section": "X",
                "change_description": "newest",
                "reasoning": "r",
                "updated_content": "",
            }
        ]
        result = append_change_log(
            strategy_with_full_log, adjustments, "2026-02-09"
        )
        # Should have MAX entries total (1 new + MAX-1 old)
        assert result.count("### ") == MAX_CHANGE_LOG_ENTRIES


class TestFormatHistorySummaryAnnotations:
    def _make_summary(self, total, wins, by_conf=None):
        return {
            "total_bets": total,
            "wins": wins,
            "losses": total - wins,
            "pushes": 0,
            "win_rate": wins / total if total else 0,
            "total_units_wagered": float(total),
            "net_units": 0.0,
            "roi": 0.0,
            "current_streak": "W1",
            "by_confidence": by_conf or {},
            "by_bet_type": {},
            "by_primary_edge": {},
        }

    def test_small_sample_tagged(self):
        summary = self._make_summary(
            20,
            12,
            by_conf={
                "high": {"wins": 2, "losses": 1, "win_rate": 0.667},
                "medium": {"wins": 10, "losses": 7, "win_rate": 0.588},
            },
        )
        result = format_history_summary(summary)
        assert "high: 2-1 (66.7%) (small sample" in result
        assert "medium: 10-7 (58.8%)" in result
        assert "small sample" not in result.split("medium")[1]

    def test_large_sample_not_tagged(self):
        summary = self._make_summary(
            30,
            18,
            by_conf={
                "high": {
                    "wins": MIN_ACTIONABLE_SAMPLE,
                    "losses": 0,
                    "win_rate": 1.0,
                }
            },
        )
        result = format_history_summary(summary)
        assert "small sample" not in result


class TestAggregateReflections:
    def _make_bets(self, n):
        return [
            {
                "structured_reflection": {
                    "edge_valid": True,
                    "missed_factors": [],
                    "process_assessment": "sound",
                    "key_lesson": f"lesson {i}",
                }
            }
            for i in range(n)
        ]

    def test_small_sample_warning(self):
        bets = self._make_bets(5)
        result = aggregate_reflections(bets)
        assert "not yet actionable" in result
        assert f"need {MIN_ACTIONABLE_SAMPLE}+" in result

    def test_large_sample_no_warning(self):
        bets = self._make_bets(MIN_ACTIONABLE_SAMPLE)
        result = aggregate_reflections(bets)
        assert "not yet actionable" not in result


# --- Helpers for bet fixtures ---


def _make_bet(result="win", bet_type="moneyline", confidence="high",
              primary_edge="ratings_edge", units=1.0, profit_loss=1.0,
              date="2026-02-10", **extra):
    bet = {
        "result": result,
        "bet_type": bet_type,
        "confidence": confidence,
        "primary_edge": primary_edge,
        "units": units,
        "profit_loss": profit_loss,
        "date": date,
        "matchup": "NYK @ BOS",
        "pick": "NYK",
    }
    bet.update(extra)
    return bet


def _make_prop_bet(result="win", prop_type="points", confidence="medium",
                   primary_edge="matchup_defense", units=1.0, profit_loss=0.8,
                   date="2026-02-10", **extra):
    return _make_bet(
        result=result,
        bet_type="player_prop",
        confidence=confidence,
        primary_edge=primary_edge,
        units=units,
        profit_loss=profit_loss,
        date=date,
        player_name="Jalen Brunson",
        prop_type=prop_type,
        line=25.5,
        **extra,
    )


class TestComputeSummary:
    def test_empty_bets(self):
        s = _compute_summary([])
        assert s["total_bets"] == 0
        assert s["wins"] == 0
        assert s["losses"] == 0
        assert s["win_rate"] == 0.0
        assert s["roi"] == 0.0
        assert s["current_streak"] == "—"

    def test_basic_record(self):
        bets = [
            _make_bet(result="win", units=1.0, profit_loss=0.9),
            _make_bet(result="win", units=1.0, profit_loss=0.9),
            _make_bet(result="loss", units=1.0, profit_loss=-1.0),
        ]
        s = _compute_summary(bets)
        assert s["total_bets"] == 3
        assert s["wins"] == 2
        assert s["losses"] == 1
        assert s["pushes"] == 0
        assert s["win_rate"] == pytest.approx(2 / 3)

    def test_win_rate_excludes_pushes_from_denominator(self):
        """Win rate = wins / (wins + losses), pushes don't dilute it."""
        bets = [
            _make_bet(result="win"),
            _make_bet(result="loss"),
            _make_bet(result="push"),
            _make_bet(result="push"),
        ]
        s = _compute_summary(bets)
        assert s["total_bets"] == 4
        assert s["pushes"] == 2
        # win_rate should be 1/2, not 1/4
        assert s["win_rate"] == pytest.approx(0.5)

    def test_net_units_and_roi(self):
        bets = [
            _make_bet(result="win", units=2.0, profit_loss=1.8),
            _make_bet(result="loss", units=1.0, profit_loss=-1.0),
        ]
        s = _compute_summary(bets)
        assert s["net_units"] == pytest.approx(0.8)
        # ROI = net_units / total_wagered (wins + losses only)
        assert s["roi"] == pytest.approx(0.8 / 3.0)

    def test_roi_excludes_push_wager_from_denominator(self):
        """ROI denominator only includes bets that resolved (win/loss)."""
        bets = [
            _make_bet(result="win", units=1.0, profit_loss=1.0),
            _make_bet(result="push", units=5.0, profit_loss=0.0),
        ]
        s = _compute_summary(bets)
        # ROI = 1.0 / 1.0 = 100%, not 1.0 / 6.0
        assert s["roi"] == pytest.approx(1.0)

    def test_missing_profit_loss_defaults_to_zero(self):
        """Bets missing profit_loss field don't break ROI calculation."""
        bet = _make_bet(result="win", units=1.0)
        del bet["profit_loss"]
        s = _compute_summary([bet])
        assert s["net_units"] == 0.0
        assert s["roi"] == 0.0

    def test_missing_units_defaults_to_zero(self):
        """Bets missing units field don't break ROI calculation."""
        bet = _make_bet(result="win", profit_loss=1.0)
        del bet["units"]
        s = _compute_summary([bet])
        assert s["net_units"] == pytest.approx(1.0)
        assert s["roi"] == 0.0  # no wagered units → 0 ROI, not division error

    def test_streak_win(self):
        bets = [
            _make_bet(result="loss"),
            _make_bet(result="win"),
            _make_bet(result="win"),
            _make_bet(result="win"),
        ]
        s = _compute_summary(bets)
        assert s["current_streak"] == "WWW"

    def test_streak_loss(self):
        bets = [
            _make_bet(result="win"),
            _make_bet(result="loss"),
            _make_bet(result="loss"),
        ]
        s = _compute_summary(bets)
        assert s["current_streak"] == "LL"

    def test_streak_ignores_trailing_pushes(self):
        """Pushes at the end don't reset or appear in the streak."""
        bets = [
            _make_bet(result="loss"),
            _make_bet(result="win"),
            _make_bet(result="win"),
            _make_bet(result="push"),
        ]
        s = _compute_summary(bets)
        assert s["current_streak"] == "WW"

    def test_by_confidence_groups_wins_and_losses_separately(self):
        bets = [
            _make_bet(result="win", confidence="high"),
            _make_bet(result="win", confidence="high"),
            _make_bet(result="loss", confidence="high"),
            _make_bet(result="loss", confidence="low"),
        ]
        s = _compute_summary(bets)
        assert s["by_confidence"]["high"] == {
            "wins": 2, "losses": 1, "pushes": 0, "win_rate": pytest.approx(2 / 3),
        }
        assert s["by_confidence"]["low"] == {
            "wins": 0, "losses": 1, "pushes": 0, "win_rate": pytest.approx(0.0),
        }

    def test_by_bet_type_groups_correctly(self):
        bets = [
            _make_bet(result="win", bet_type="moneyline"),
            _make_bet(result="loss", bet_type="moneyline"),
            _make_bet(result="win", bet_type="spread"),
        ]
        s = _compute_summary(bets)
        assert s["by_bet_type"]["moneyline"]["wins"] == 1
        assert s["by_bet_type"]["moneyline"]["losses"] == 1
        assert s["by_bet_type"]["spread"]["wins"] == 1
        assert s["by_bet_type"]["spread"]["losses"] == 0

    def test_compatible_with_format_history_summary(self):
        """_compute_summary output can be rendered by format_history_summary without errors."""
        bets = [
            _make_bet(result="win", confidence="high", units=2.0, profit_loss=1.8),
            _make_bet(result="loss", confidence="medium", units=1.0, profit_loss=-1.0),
            _make_bet(result="win", confidence="high", units=2.0, profit_loss=1.8),
        ]
        s = _compute_summary(bets)
        text = format_history_summary(s)
        assert "Record: 2-1" in text
        assert "By Confidence:" in text
        assert "high: 2-0" in text
        assert "medium: 0-1" in text


class TestBetTypeIsolation:
    """Core intention: game-level and props strategies see only their own bets."""

    def _mixed_history(self):
        """5 game bets (3W 2L) + 4 prop bets (1W 3L) — different records."""
        return [
            _make_bet(result="win", bet_type="moneyline", confidence="high",
                      units=2.0, profit_loss=1.8, date="2026-02-01"),
            _make_bet(result="win", bet_type="moneyline", confidence="high",
                      units=2.0, profit_loss=1.8, date="2026-02-02"),
            _make_bet(result="win", bet_type="spread", confidence="medium",
                      units=1.0, profit_loss=0.9, date="2026-02-03"),
            _make_bet(result="loss", bet_type="moneyline", confidence="medium",
                      units=1.0, profit_loss=-1.0, date="2026-02-04"),
            _make_bet(result="loss", bet_type="spread", confidence="low",
                      units=0.5, profit_loss=-0.5, date="2026-02-05"),
            _make_prop_bet(result="win", date="2026-02-01"),
            _make_prop_bet(result="loss", date="2026-02-02"),
            _make_prop_bet(result="loss", date="2026-02-03"),
            _make_prop_bet(result="loss", date="2026-02-04"),
        ]

    def test_game_filter_excludes_all_prop_bets(self):
        bets = self._mixed_history()
        game_bets = [b for b in bets if b.get("bet_type") != "player_prop"]
        assert len(game_bets) == 5
        assert all(b["bet_type"] != "player_prop" for b in game_bets)

    def test_prop_filter_excludes_all_game_bets(self):
        bets = self._mixed_history()
        prop_bets = [b for b in bets if b.get("bet_type") == "player_prop"]
        assert len(prop_bets) == 4
        assert all(b["bet_type"] == "player_prop" for b in prop_bets)

    def test_game_summary_reflects_only_game_bets(self):
        bets = self._mixed_history()
        game_bets = [b for b in bets if b.get("bet_type") != "player_prop"]
        s = _compute_summary(game_bets)
        # Game bets: 3W 2L
        assert s["wins"] == 3
        assert s["losses"] == 2
        assert s["win_rate"] == pytest.approx(0.6)
        assert "player_prop" not in s["by_bet_type"]

    def test_prop_summary_reflects_only_prop_bets(self):
        bets = self._mixed_history()
        prop_bets = [b for b in bets if b.get("bet_type") == "player_prop"]
        s = _compute_summary(prop_bets)
        # Prop bets: 1W 3L
        assert s["wins"] == 1
        assert s["losses"] == 3
        assert s["win_rate"] == pytest.approx(0.25)
        assert "moneyline" not in s["by_bet_type"]
        assert "spread" not in s["by_bet_type"]

    def test_game_summary_formatted_text_has_no_prop_references(self):
        """The rendered summary string for game strategy should never mention player_prop."""
        bets = self._mixed_history()
        game_bets = [b for b in bets if b.get("bet_type") != "player_prop"]
        s = _compute_summary(game_bets)
        text = format_history_summary(s)
        assert "player_prop" not in text
        assert "Record: 3-2" in text

    def test_prop_summary_formatted_text_has_no_game_bet_types(self):
        """The rendered summary for props strategy should not mention moneyline/spread."""
        bets = self._mixed_history()
        prop_bets = [b for b in bets if b.get("bet_type") == "player_prop"]
        s = _compute_summary(prop_bets)
        text = format_history_summary(s)
        assert "moneyline" not in text
        assert "spread" not in text
        assert "Record: 1-3" in text

    def test_recent_bets_formatting_excludes_other_type(self):
        """format_recent_bets on game bets should not show prop bet details."""
        bets = self._mixed_history()
        game_bets = [b for b in bets if b.get("bet_type") != "player_prop"]
        text = format_recent_bets(game_bets)
        assert "Jalen Brunson" not in text
        assert "player_prop" not in text

    def test_recent_prop_bets_formatting_excludes_game_bets(self):
        """format_recent_prop_bets on prop bets should not show game bet details."""
        bets = self._mixed_history()
        prop_bets = [b for b in bets if b.get("bet_type") == "player_prop"]
        text = format_recent_prop_bets(prop_bets)
        assert "moneyline" not in text
        assert "spread" not in text

    def test_filtered_summaries_add_up_to_total(self):
        bets = self._mixed_history()
        game_s = _compute_summary([b for b in bets if b.get("bet_type") != "player_prop"])
        prop_s = _compute_summary([b for b in bets if b.get("bet_type") == "player_prop"])
        total_s = _compute_summary(bets)
        assert game_s["wins"] + prop_s["wins"] == total_s["wins"]
        assert game_s["losses"] + prop_s["losses"] == total_s["losses"]
        assert game_s["total_bets"] + prop_s["total_bets"] == total_s["total_bets"]

    def test_legacy_bets_without_bet_type_included_in_game_filter(self):
        """Old bets that predate prop support have no bet_type field.
        They should be treated as game-level bets, not filtered out."""
        legacy_bet = {"result": "win", "date": "2026-01-01", "matchup": "NYK @ BOS",
                      "pick": "NYK", "confidence": "high", "units": 1.0,
                      "profit_loss": 0.9, "primary_edge": "ratings_edge"}
        # No "bet_type" key at all
        assert "bet_type" not in legacy_bet
        bets = [legacy_bet, _make_prop_bet(result="loss")]
        game_bets = [b for b in bets if b.get("bet_type") != "player_prop"]
        # Legacy bet should be included in game bets
        assert len(game_bets) == 1
        assert game_bets[0] is legacy_bet


class TestFormatRecentPropBets:
    def test_empty(self):
        assert format_recent_prop_bets([]) == "No completed prop bets yet."

    def test_formats_prop_fields(self):
        bets = [_make_prop_bet(result="win", prop_type="points")]
        text = format_recent_prop_bets(bets)
        assert "[W]" in text
        assert "Jalen Brunson" in text
        assert "points" in text
        assert "25.5" in text

    def test_includes_reflection(self):
        bet = _make_prop_bet(result="loss")
        bet["reflection"] = "Line was sharp"
        text = format_recent_prop_bets([bet])
        assert "[L]" in text
        assert "Reflection: Line was sharp" in text

    def test_missing_fields_show_placeholder(self):
        bet = {"result": "win"}
        text = format_recent_prop_bets([bet])
        assert "?" in text