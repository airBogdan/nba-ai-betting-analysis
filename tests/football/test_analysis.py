"""Tests for sports.football.analysis."""

from unittest.mock import AsyncMock, patch

import pytest

from sports.football.analysis import (
    _avg_or_default,
    render_match_section,
    render_report,
)


SAMPLE_ANALYSIS = {
    "home": "Arsenal",
    "away": "Chelsea",
    "league": "EPL",
    "league_avg": 2.75,
    "venue": "Emirates Stadium",
    "time": "20:00",
    "home_avg": {
        "goals_for_avg": 1.82,
        "goals_against_avg": 0.95,
        "home_gf_avg": 2.10,
        "home_ga_avg": 0.75,
        "away_gf_avg": 1.50,
        "away_ga_avg": 1.20,
        "matches": 10,
        "home_matches": 5,
        "away_matches": 5,
    },
    "away_avg": {
        "goals_for_avg": 1.45,
        "goals_against_avg": 1.20,
        "home_gf_avg": 1.80,
        "home_ga_avg": 0.90,
        "away_gf_avg": 1.10,
        "away_ga_avg": 1.50,
        "matches": 10,
        "home_matches": 5,
        "away_matches": 5,
    },
    "home_xg": 1.52,
    "away_xg": 0.98,
    "probabilities": {
        "over_1_5": 0.782,
        "under_1_5": 0.218,
        "over_2_5": 0.55,
        "under_2_5": 0.45,
        "under_3_5": 0.621,
        "over_3_5": 0.379,
        "under_4_5": 0.843,
        "over_4_5": 0.157,
    },
}


class TestRenderMatchSection:
    def test_contains_team_names(self):
        result = render_match_section(SAMPLE_ANALYSIS)
        assert "Arsenal" in result
        assert "Chelsea" in result

    def test_contains_probabilities(self):
        result = render_match_section(SAMPLE_ANALYSIS)
        assert "Over 1.5" in result
        assert "Under 3.5" in result

    def test_contains_expected_goals(self):
        result = render_match_section(SAMPLE_ANALYSIS)
        assert "1.52" in result
        assert "0.98" in result

    def test_shows_season_stats(self):
        result = render_match_section(SAMPLE_ANALYSIS)
        assert "1.82" in result
        assert "GF/G" in result

    def test_shows_league_average(self):
        result = render_match_section(SAMPLE_ANALYSIS)
        assert "League avg" in result
        assert "2.75" in result

    def test_shows_standings_when_present(self):
        analysis = {
            **SAMPLE_ANALYSIS,
            "home_standing": {"position": 1, "played": 28, "won": 18, "drawn": 7, "lost": 3, "gf": 56, "ga": 20, "pts": 61},
            "away_standing": {"position": 4, "played": 28, "won": 14, "drawn": 5, "lost": 9, "gf": 40, "ga": 30, "pts": 47},
        }
        result = render_match_section(analysis)
        assert "61" in result
        assert "1st" in result
        assert "standings" in result

    def test_no_standings_when_absent(self):
        result = render_match_section(SAMPLE_ANALYSIS)
        assert "standings" not in result

    def test_hides_stats_when_no_data(self):
        analysis = {
            **SAMPLE_ANALYSIS,
            "home_avg": {"matches": 0, "goals_for_avg": 0.0, "goals_against_avg": 0.0},
            "away_avg": {"matches": 0, "goals_for_avg": 0.0, "goals_against_avg": 0.0},
        }
        result = render_match_section(analysis)
        assert "GF/G" not in result

    def test_outputs_html(self):
        result = render_match_section(SAMPLE_ANALYSIS)
        assert "match-card" in result
        assert "<div" in result


class TestRenderReport:
    def test_includes_date_header(self):
        result = render_report([SAMPLE_ANALYSIS], "2026-02-27")
        assert "2026-02-27" in result

    def test_includes_all_matches(self):
        analysis2 = {**SAMPLE_ANALYSIS, "home": "Liverpool", "away": "Man City"}
        result = render_report([SAMPLE_ANALYSIS, analysis2], "2026-02-27")
        assert "Arsenal" in result
        assert "Liverpool" in result

    def test_is_valid_html(self):
        result = render_report([SAMPLE_ANALYSIS], "2026-02-27")
        assert result.startswith("<!DOCTYPE html>")
        assert "</html>" in result
        assert "<style>" in result


class TestAvgOrDefault:
    def _avg(self, **kwargs):
        base = {
            "goals_for_avg": 1.5, "goals_against_avg": 1.0,
            "home_gf_avg": 1.8, "home_ga_avg": 0.7,
            "away_gf_avg": 1.2, "away_ga_avg": 1.3,
            "matches": 10, "home_matches": 5, "away_matches": 5,
        }
        base.update(kwargs)
        return base

    def test_returns_blended_venue_avg(self):
        avg = self._avg()
        # (1.8 * 5 + 1.5 * 6) / (5 + 6) = 1.636...
        result = _avg_or_default(avg, "home_gf_avg", "goals_for_avg", 1.34)
        assert round(result, 2) == 1.64

    def test_falls_back_to_overall_when_no_venue_matches(self):
        avg = self._avg(home_matches=0)
        assert _avg_or_default(avg, "home_gf_avg", "goals_for_avg", 1.34) == 1.5

    def test_returns_default_when_no_matches(self):
        avg = self._avg(matches=0)
        assert _avg_or_default(avg, "home_gf_avg", "goals_for_avg", 1.34) == 1.34

    def test_falls_back_to_overall_when_venue_key_missing(self):
        avg = self._avg()
        del avg["home_gf_avg"]
        result = _avg_or_default(avg, "home_gf_avg", "goals_for_avg", 1.34)
        assert result == 1.5

    def test_blends_zero_venue_toward_overall(self):
        avg = self._avg(home_gf_avg=0.0, home_matches=5)
        # (0.0 * 5 + 1.5 * 6) / (5 + 6) = 0.818...
        result = _avg_or_default(avg, "home_gf_avg", "goals_for_avg", 1.34)
        assert round(result, 2) == 0.82

    def test_falls_back_to_overall_when_too_few_venue_matches(self):
        avg = self._avg(home_gf_avg=0.0, home_matches=2)
        result = _avg_or_default(avg, "home_gf_avg", "goals_for_avg", 1.34)
        assert result == 1.5


class TestRunAnalysis:
    @pytest.mark.asyncio
    async def test_unknown_league_returns_early(self, capsys):
        from sports.football.analysis import run_analysis

        await run_analysis("fake_league", "2026-02-27")
        # Should not crash — just logs and returns

    @pytest.mark.asyncio
    async def test_no_matches_returns_early(self):
        from sports.football.analysis import run_analysis

        with patch(
            "sports.football.analysis.fetch_matches_for_date",
            new_callable=AsyncMock,
            return_value=[],
        ), patch(
            "sports.football.analysis.close_session",
            new_callable=AsyncMock,
        ), patch(
            "sports.football.analysis.ensure_averages",
            new_callable=AsyncMock,
            return_value=None,
        ):
            await run_analysis("epl", "2026-02-27")

    @pytest.mark.asyncio
    async def test_skips_match_with_no_team_names(self):
        from sports.football.analysis import analyze_match

        result = await analyze_match({"match_hometeam_name": "", "match_awayteam_name": ""}, "2026-02-27")
        assert result is None


class TestAnalyzeMatchIntegration:
    @pytest.mark.asyncio
    async def test_pipeline_with_mocked_data(self):
        from sports.football.analysis import analyze_match

        match = {
            "match_hometeam_name": "Arsenal",
            "match_awayteam_name": "Chelsea",
            "match_hometeam_id": "10",
            "match_awayteam_id": "20",
            "league_name": "EPL",
            "match_stadium": "Emirates",
            "match_time": "20:00",
        }

        def _make_match(home_id, away_id, h_score, a_score):
            return {
                "match_hometeam_id": str(home_id),
                "match_awayteam_id": str(away_id),
                "match_hometeam_score": str(h_score),
                "match_awayteam_score": str(a_score),
            }

        home_hist = [
            _make_match("10", "99", 2, 1),
            _make_match("10", "98", 1, 0),
            _make_match("97", "10", 0, 3),
        ]
        away_hist = [
            _make_match("20", "88", 1, 1),
            _make_match("77", "20", 2, 2),
            _make_match("20", "66", 0, 1),
        ]

        mock_fetch = AsyncMock(side_effect=[home_hist, away_hist])

        with patch(
            "sports.football.analysis._fetch_team_history",
            mock_fetch,
        ):
            result = await analyze_match(match, "2026-02-27")

        assert result is not None
        assert result["home"] == "Arsenal"
        assert result["away"] == "Chelsea"
        assert "over_1_5" in result["probabilities"]
        assert result["home_xg"] > 0
        assert result["away_xg"] > 0
        assert result["home_avg"]["matches"] == 3
        assert result["away_avg"]["matches"] == 3
