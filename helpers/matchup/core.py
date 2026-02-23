"""Core matchup analysis engine."""

import math
from typing import Dict, List, Optional

from ..api import ProcessedPlayerStats, ProcessedTeamStats, RecentGame
from ..games import compute_quarter_analysis
from ..teams import SeasonStanding
from ..types import H2HResults, H2HSummary
from ..utils import get_current_nba_season_year
from .types import (
    DEFAULT_LEAGUE_AVG_EFFICIENCY,
    BuildMatchupInput,
    H2H,
    MatchupAnalysis,
    MatchupEdges,
    TeamSnapshot,
)
from .h2h import compute_h2h_matchup_stats, compute_h2h_patterns, compute_recent_h2h
from .schedule import compute_schedule_context
from .signals import generate_signals
from .totals import compute_totals_analysis
from .players import build_team_players


# === Helper functions ===


def _exponential_decay_weights(n: int, half_life: float = 3.0) -> List[float]:
    """Generate normalized exponential decay weights (most recent first)."""
    if n == 0:
        return []
    raw = [math.exp(-math.log(2) * i / half_life) for i in range(n)]
    total = sum(raw)
    return [w / total for w in raw]


def get_current_season_standing(standings: List[SeasonStanding]) -> Optional[SeasonStanding]:
    """Get standing for current season."""
    current_year = get_current_nba_season_year()
    if not current_year:
        return None
    return next((s for s in standings if s["season"] == current_year), None)


def get_current_season_stats(stats: Optional[Dict[int, ProcessedTeamStats]]) -> Optional[ProcessedTeamStats]:
    """Get stats for current season."""
    if not stats:
        return None
    current_year = get_current_nba_season_year()
    if not current_year:
        return None
    return stats.get(current_year)


def build_team_snapshot(
    name: str,
    standing: Optional[SeasonStanding],
    stats: Optional[ProcessedTeamStats],
    league_avg_efficiency: float = DEFAULT_LEAGUE_AVG_EFFICIENCY,
    recent_games: Optional[List[RecentGame]] = None,
) -> TeamSnapshot:
    """Build team snapshot with computed metrics."""
    last_ten_pct = standing.get("last_ten_pct", 0.0) if standing else 0.0

    ppg = stats.get("ppg", 0.0) if stats else 0.0
    net_rating = stats.get("net_rating", 0.0) if stats else 0.0
    pace = stats.get("pace", 100.0) if stats else 100.0

    # Estimate ORTG/DRTG from net rating and pace
    ortg = round(league_avg_efficiency + net_rating / 2, 1)
    drtg = round(league_avg_efficiency - net_rating / 2, 1)
    # Points allowed estimate: DRTG * pace / 100
    opp_ppg = round(drtg * pace / 100, 1)

    # Recency-weighted metrics
    recent_ppg = ppg
    recent_margin = 0.0
    sos = 0.5
    if recent_games:
        weights = _exponential_decay_weights(len(recent_games))
        recent_ppg = round(sum(int(g["score"].split("-")[0]) * w for g, w in zip(recent_games, weights)), 1)
        recent_margin = round(sum(g["margin"] * w for g, w in zip(recent_games, weights)), 1)
        opp_pcts = [g["vs_win_pct"] for g in recent_games if g.get("vs_win_pct", 0) > 0]
        if opp_pcts:
            sos = round(sum(opp_pcts) / len(opp_pcts), 3)

    # SOS-adjusted net rating (additive — handles negative ratings correctly)
    sos_adjustment = (sos - 0.5) * 10
    sos_adjusted_net_rating = round(net_rating + sos_adjustment, 2)

    return {
        "name": name,
        "record": f"{standing['wins']}-{standing['losses']}" if standing else "N/A",
        "conf_rank": standing.get("conference_rank", 0) if standing else 0,
        "games": stats.get("games", 0) if stats else 0,
        "ppg": ppg,
        "opp_ppg": opp_ppg,
        "ortg": ortg,
        "drtg": drtg,
        "apg": stats.get("apg", 0.0) if stats else 0.0,
        "rpg": stats.get("rpg", 0.0) if stats else 0.0,
        "topg": stats.get("topg", 0.0) if stats else 0.0,
        "net_rating": net_rating,
        "fgp": stats.get("fgp", 0.0) if stats else 0.0,
        "tpp": stats.get("tpp", 0.0) if stats else 0.0,
        "last_ten": f"{standing['last_ten_wins']}-{standing['last_ten_losses']}" if standing else "N/A",
        "last_ten_pct": last_ten_pct,
        "home_record": f"{standing['home_wins']}-{standing['home_losses']}" if standing else "N/A",
        "away_record": f"{standing['away_wins']}-{standing['away_losses']}" if standing else "N/A",
        "home_win_pct": standing.get("home_win_pct", 0.0) if standing else 0.0,
        "away_win_pct": standing.get("away_win_pct", 0.0) if standing else 0.0,
        "pace": pace,
        "recent_ppg": recent_ppg,
        "recent_margin": recent_margin,
        "sos": sos,
        "sos_adjusted_net_rating": sos_adjusted_net_rating,
    }


def compute_edges(team1: TeamSnapshot, team2: TeamSnapshot) -> MatchupEdges:
    """Compute comparison edges between two teams."""
    return {
        "ppg": round(team1["ppg"] - team2["ppg"], 1),
        "net_rating": round(team1["net_rating"] - team2["net_rating"], 2),
        "form": round(team1["last_ten_pct"] - team2["last_ten_pct"], 2),
        "turnovers": round(team2["topg"] - team1["topg"], 1),  # positive = team1 turns it over less
        "rebounds": round(team1["rpg"] - team2["rpg"], 1),
        "fgp": round(team1["fgp"] - team2["fgp"], 1),
        "three_pt_pct": round(team1["tpp"] - team2["tpp"], 1),
        "pace": round(team1["pace"] - team2["pace"], 1),
        "combined_pace": round((team1["pace"] + team2["pace"]) / 2, 1),
        "weighted_form": round(team1.get("recent_margin", 0) - team2.get("recent_margin", 0), 1),
        "adjusted_net_rating": round(team1.get("sos_adjusted_net_rating", 0) - team2.get("sos_adjusted_net_rating", 0), 2),
    }


def build_matchup_analysis(input_data: BuildMatchupInput) -> MatchupAnalysis:
    """Build complete matchup analysis."""
    team1_name = input_data["team1_name"]
    team2_name = input_data["team2_name"]
    home_team = input_data["home_team"]
    team1_standings = input_data["team1_standings"]
    team2_standings = input_data["team2_standings"]
    team1_stats = input_data["team1_stats"]
    team2_stats = input_data["team2_stats"]
    team1_players = input_data["team1_players"]
    team2_players = input_data["team2_players"]
    team1_recent_games = input_data["team1_recent_games"]
    team2_recent_games = input_data["team2_recent_games"]
    h2h_summary = input_data["h2h_summary"]
    h2h_results = input_data["h2h_results"]
    game_date = input_data.get("game_date")

    # Get current season data only
    team1_standing = get_current_season_standing(team1_standings)
    team2_standing = get_current_season_standing(team2_standings)
    team1_current_stats = get_current_season_stats(team1_stats)
    team2_current_stats = get_current_season_stats(team2_stats)

    # Build snapshots
    league_avg_efficiency = input_data.get("league_avg_efficiency", DEFAULT_LEAGUE_AVG_EFFICIENCY)
    team1_snapshot = build_team_snapshot(
        team1_name, team1_standing, team1_current_stats,
        league_avg_efficiency=league_avg_efficiency,
        recent_games=team1_recent_games,
    )
    team2_snapshot = build_team_snapshot(
        team2_name, team2_standing, team2_current_stats,
        league_avg_efficiency=league_avg_efficiency,
        recent_games=team2_recent_games,
    )

    # Compute comparison edges
    comparison = compute_edges(team1_snapshot, team2_snapshot)

    # Build merged H2H object
    h2h: Optional[H2H] = None
    if h2h_summary and h2h_results:
        patterns = compute_h2h_patterns(h2h_results)
        recent = compute_recent_h2h(h2h_results, team1_name, home_team)
        quarters = compute_quarter_analysis(h2h_results, team1_name, team2_name)
        matchup_stats = compute_h2h_matchup_stats(h2h_results, team1_name, team2_name)

        if patterns and recent:
            h2h = {
                "summary": {
                    "total_games": h2h_summary["total_games"],
                    "team1_wins_all_time": h2h_summary["team1_wins_all_time"],
                    "team2_wins_all_time": h2h_summary["team2_wins_all_time"],
                    "team1_win_pct": h2h_summary["team1_win_pct"],
                    "team1_home_wins": h2h_summary["team1_home_wins"],
                    "team1_home_losses": h2h_summary["team1_home_losses"],
                    "team1_away_wins": h2h_summary["team1_away_wins"],
                    "team1_away_losses": h2h_summary["team1_away_losses"],
                    "avg_point_diff": h2h_summary["avg_point_diff"],
                    "team1_avg_points": h2h_summary["team1_avg_points"],
                    "team2_avg_points": h2h_summary["team2_avg_points"],
                    "last_5_games": h2h_summary["last_5_games"],
                    "recent_trend": h2h_summary["recent_trend"],
                    "close_games": h2h_summary["close_games"],
                    "blowouts": h2h_summary["blowouts"],
                },
                "patterns": patterns,
                "recent": recent,
                "quarters": quarters,
                "matchup_stats": matchup_stats,
            }

    # Build merged player data
    team1_player_data = build_team_players(team1_players, team1_snapshot["games"], team1_snapshot["ppg"])
    team2_player_data = build_team_players(team2_players, team2_snapshot["games"], team2_snapshot["ppg"])

    # Compute totals analysis
    totals_analysis = compute_totals_analysis(
        team1_snapshot,
        team2_snapshot,
        h2h_summary,
        h2h_results,
        team1_recent_games,
        team2_recent_games
    )

    # Compute schedule context
    team1_schedule = compute_schedule_context(team1_recent_games, game_date)
    team2_schedule = compute_schedule_context(team2_recent_games, game_date)

    # Generate signals
    signals = generate_signals(
        team1_snapshot,
        team2_snapshot,
        home_team,
        comparison,
        h2h,
        team1_player_data,
        team2_player_data,
        totals_analysis,
        team1_recent_games,
        team2_recent_games,
        game_date,
    )

    return {
        "matchup": {
            "team1": team1_name,
            "team2": team2_name,
            "home_team": home_team,
        },
        "current_season": {
            "team1": team1_snapshot,
            "team2": team2_snapshot,
        },
        "schedule": {
            "team1": team1_schedule,
            "team2": team2_schedule,
        },
        "recent_games": {
            "team1": team1_recent_games,
            "team2": team2_recent_games,
        },
        "players": {
            "team1": team1_player_data,
            "team2": team2_player_data,
        },
        "h2h": h2h,
        "totals_analysis": totals_analysis,
        "comparison": comparison,
        "signals": signals,
    }
