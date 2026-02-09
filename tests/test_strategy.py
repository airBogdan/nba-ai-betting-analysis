"""Tests for workflow.strategy module."""

import pytest

from workflow.prompts import MIN_ACTIONABLE_SAMPLE, format_history_summary
from workflow.strategy import (
    MAX_CHANGE_LOG_ENTRIES,
    _parse_sections,
    _rebuild_strategy,
    aggregate_reflections,
    append_change_log,
    apply_adjustments,
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