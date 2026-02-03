"""Core matchup analysis engine."""

import math
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from typing_extensions import TypedDict

from .api import ProcessedPlayerStats, ProcessedTeamStats, RecentGame, Injury
from .games import compute_quarter_analysis
from .teams import SeasonStanding
from .types import H2HResults, H2HSummary, QuarterAnalysis
from .utils import get_current_nba_season_year


# === TypedDict definitions ===


class TeamSnapshot(TypedDict):
    """Current season team state with computed metrics."""
    name: str
    record: str
    conf_rank: int
    games: int
    ppg: float
    opp_ppg: float  # Points allowed (estimated)
    ortg: float  # Offensive rating estimate
    drtg: float  # Defensive rating estimate
    apg: float
    rpg: float
    topg: float
    net_rating: float
    fgp: float
    tpp: float
    last_ten: str
    last_ten_pct: float
    home_record: str
    away_record: str
    home_win_pct: float
    away_win_pct: float
    pace: float


class MatchupEdges(TypedDict):
    """Comparison edges between two teams."""
    ppg: float
    net_rating: float
    form: float
    turnovers: float
    rebounds: float
    fgp: float
    three_pt_pct: float
    pace: float
    combined_pace: float


class H2HSummaryData(TypedDict):
    """H2H summary data."""
    total_games: int
    team1_wins_all_time: int
    team2_wins_all_time: int
    team1_win_pct: float
    team1_home_wins: int
    team1_home_losses: int
    team1_away_wins: int
    team1_away_losses: int
    avg_point_diff: float
    team1_avg_points: float
    team2_avg_points: float
    last_5_games: List[str]
    recent_trend: str
    close_games: int
    blowouts: int


class H2HPatterns(TypedDict):
    """H2H patterns analysis."""
    avg_total: float  # Single source of truth for avg combined score
    home_win_pct: float
    high_scoring_pct: float
    close_game_pct: float


class H2HTeamStats(TypedDict):
    """Aggregated team stats from H2H box scores."""
    avg_fgp: float
    avg_tpp: float
    avg_rebounds: float
    avg_assists: float
    avg_turnovers: float
    avg_disruption: float  # steals + blocks


class H2HMatchupStats(TypedDict):
    """Matchup-specific stats from H2H games."""
    team1: H2HTeamStats
    team2: H2HTeamStats


class H2HRecent(TypedDict):
    """Recent H2H data (last 2 seasons only)."""
    team1_wins_last_2_seasons: int
    team2_wins_last_2_seasons: int
    last_winner: str
    home_team_home_record: str
    games_last_2_seasons: int


class H2H(TypedDict):
    """Combined H2H analysis."""
    summary: H2HSummaryData
    patterns: H2HPatterns
    recent: H2HRecent
    quarters: Optional[QuarterAnalysis]
    matchup_stats: Optional[H2HMatchupStats]


class TeamSchedule(TypedDict):
    """Schedule/situational context for a team."""
    days_rest: Optional[int]
    streak: str  # e.g., "W3", "L2"
    games_last_7_days: int
    # Opponent strength context
    recent_opponent_avg_win_pct: float  # Avg win% of recent opponents
    quality_wins: int  # Wins vs .500+ teams in recent games
    quality_losses: int  # Losses vs .500+ teams in recent games


class TotalsAnalysis(TypedDict):
    """Totals/Over-Under analysis."""
    expected_total: float
    total_diff_from_h2h: float
    team1_h2h_scoring_diff: float
    team2_h2h_scoring_diff: float
    margin_volatility: float
    h2h_total_variance: float
    pace_adjusted_total: float
    defense_factor: float
    recent_scoring_trend: float


class RotationPlayer(TypedDict):
    """Rotation player data."""
    name: str
    ppg: float
    plus_minus: float
    games: int


class TeamPlayers(TypedDict, total=False):
    """Team player analysis."""
    rotation: List[RotationPlayer]
    availability_concerns: List[str]
    full_strength: bool
    top_scorers: str
    playmaker: str
    hot_hand: str
    star_dependency: float
    depth_rating: str
    bench_scoring: float
    injuries: List[Injury]  # Added post-generation from injuries API


class MatchupAnalysis(TypedDict):
    """Complete matchup analysis output."""
    matchup: Dict[str, str]
    current_season: Dict[str, TeamSnapshot]
    schedule: Dict[str, TeamSchedule]
    recent_games: Dict[str, List[RecentGame]]
    players: Dict[str, Optional[TeamPlayers]]
    h2h: Optional[H2H]
    totals_analysis: TotalsAnalysis
    comparison: MatchupEdges
    signals: List[str]


class BuildMatchupInput(TypedDict):
    """Input for build_matchup_analysis."""
    team1_name: str
    team2_name: str
    home_team: str
    team1_standings: List[SeasonStanding]
    team2_standings: List[SeasonStanding]
    team1_stats: Optional[Dict[int, ProcessedTeamStats]]
    team2_stats: Optional[Dict[int, ProcessedTeamStats]]
    team1_players: List[ProcessedPlayerStats]
    team2_players: List[ProcessedPlayerStats]
    team1_recent_games: List[RecentGame]
    team2_recent_games: List[RecentGame]
    h2h_summary: Optional[H2HSummary]
    h2h_results: Optional[H2HResults]
    game_date: Optional[str]  # YYYY-MM-DD or ISO datetime for rest calculations


# === Helper functions ===


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
    stats: Optional[ProcessedTeamStats]
) -> TeamSnapshot:
    """Build team snapshot with computed metrics."""
    last_ten_pct = standing.get("last_ten_pct", 0.0) if standing else 0.0

    ppg = stats.get("ppg", 0.0) if stats else 0.0
    net_rating = stats.get("net_rating", 0.0) if stats else 0.0
    pace = stats.get("pace", 100.0) if stats else 100.0

    # Estimate ORTG/DRTG from net rating and pace
    league_avg_efficiency = 112  # approximate 2024 NBA average
    ortg = round(league_avg_efficiency + net_rating / 2, 1)
    drtg = round(league_avg_efficiency - net_rating / 2, 1)
    # Points allowed estimate: DRTG * pace / 100
    opp_ppg = round(drtg * pace / 100, 1)

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
    }


def compute_recent_h2h(
    h2h_results: Optional[H2HResults],
    team1_name: str,
    home_team: str
) -> Optional[H2HRecent]:
    """Compute recent H2H data (last 2 seasons)."""
    if not h2h_results:
        return None

    current_year = get_current_nba_season_year()
    if not current_year:
        return None

    # Get games from last 2 seasons only
    recent_seasons = [current_year, current_year - 1]
    recent_games: List[Dict[str, str]] = []

    for season in recent_seasons:
        season_games = h2h_results.get(season)
        if season_games:
            recent_games.extend([
                {"winner": g["winner"], "home_team": g["home_team"]}
                for g in season_games
            ])

    if len(recent_games) == 0:
        return None

    team1_wins = sum(1 for g in recent_games if g["winner"] == team1_name)
    team2_wins = len(recent_games) - team1_wins

    # Home team's record when hosting this matchup
    home_games = [g for g in recent_games if g["home_team"] == home_team]
    home_wins = sum(1 for g in home_games if g["winner"] == home_team)

    return {
        "team1_wins_last_2_seasons": team1_wins,
        "team2_wins_last_2_seasons": team2_wins,
        "last_winner": recent_games[-1]["winner"] if recent_games else "N/A",
        "home_team_home_record": f"{home_wins}-{len(home_games) - home_wins}",
        "games_last_2_seasons": len(recent_games),
    }


def compute_h2h_matchup_stats(
    h2h_results: Optional[H2HResults],
    team1_name: str,
    team2_name: str
) -> Optional[H2HMatchupStats]:
    """Compute aggregated stats for each team from H2H box scores."""
    if not h2h_results:
        return None

    # Collect stats for each team
    team1_stats = {
        "fgp": [], "tpp": [],
        "rebounds": [], "assists": [], "turnovers": [],
        "disruption": []  # steals + blocks
    }
    team2_stats = {
        "fgp": [], "tpp": [],
        "rebounds": [], "assists": [], "turnovers": [],
        "disruption": []
    }

    for games in h2h_results.values():
        for game in games:
            home_stats = game.get("home_statistics")
            visitor_stats = game.get("visitor_statistics")

            if not home_stats or not visitor_stats:
                continue

            # Determine which stats belong to which team
            is_team1_home = game["home_team"] == team1_name
            t1_stats = home_stats if is_team1_home else visitor_stats
            t2_stats = visitor_stats if is_team1_home else home_stats

            # Collect team1 stats
            team1_stats["fgp"].append(float(t1_stats.get("fgp", 0) or 0))
            team1_stats["tpp"].append(float(t1_stats.get("tpp", 0) or 0))
            team1_stats["rebounds"].append(t1_stats.get("totReb", 0) or 0)
            team1_stats["assists"].append(t1_stats.get("assists", 0) or 0)
            team1_stats["turnovers"].append(t1_stats.get("turnovers", 0) or 0)
            t1_steals = t1_stats.get("steals", 0) or 0
            t1_blocks = t1_stats.get("blocks", 0) or 0
            team1_stats["disruption"].append(t1_steals + t1_blocks)

            # Collect team2 stats
            team2_stats["fgp"].append(float(t2_stats.get("fgp", 0) or 0))
            team2_stats["tpp"].append(float(t2_stats.get("tpp", 0) or 0))
            team2_stats["rebounds"].append(t2_stats.get("totReb", 0) or 0)
            team2_stats["assists"].append(t2_stats.get("assists", 0) or 0)
            team2_stats["turnovers"].append(t2_stats.get("turnovers", 0) or 0)
            t2_steals = t2_stats.get("steals", 0) or 0
            t2_blocks = t2_stats.get("blocks", 0) or 0
            team2_stats["disruption"].append(t2_steals + t2_blocks)

    games_count = len(team1_stats["fgp"])
    if games_count == 0:
        return None

    def avg(lst: list) -> float:
        return round(sum(lst) / len(lst), 1) if lst else 0.0

    return {
        "team1": {
            "avg_fgp": avg(team1_stats["fgp"]),
            "avg_tpp": avg(team1_stats["tpp"]),
            "avg_rebounds": avg(team1_stats["rebounds"]),
            "avg_assists": avg(team1_stats["assists"]),
            "avg_turnovers": avg(team1_stats["turnovers"]),
            "avg_disruption": avg(team1_stats["disruption"]),
        },
        "team2": {
            "avg_fgp": avg(team2_stats["fgp"]),
            "avg_tpp": avg(team2_stats["tpp"]),
            "avg_rebounds": avg(team2_stats["rebounds"]),
            "avg_assists": avg(team2_stats["assists"]),
            "avg_turnovers": avg(team2_stats["turnovers"]),
            "avg_disruption": avg(team2_stats["disruption"]),
        },
    }


def compute_h2h_patterns(h2h_results: Optional[H2HResults]) -> Optional[H2HPatterns]:
    """Compute H2H patterns from results."""
    if not h2h_results:
        return None

    all_games = [g for games in h2h_results.values() for g in games]
    if len(all_games) == 0:
        return None

    total_games = len(all_games)
    total_combined_score = 0
    home_wins = 0
    high_scoring = 0  # games over 220
    close_games = 0  # margin <= 5

    for game in all_games:
        combined = game["home_points"] + game["visitor_points"]
        total_combined_score += combined

        if game["winner"] == game["home_team"]:
            home_wins += 1
        if combined > 220:
            high_scoring += 1
        if abs(game["point_diff"]) <= 5:
            close_games += 1

    return {
        "avg_total": round(total_combined_score / total_games, 1),
        "home_win_pct": round(home_wins / total_games, 3),
        "high_scoring_pct": round(high_scoring / total_games, 2),
        "close_game_pct": round(close_games / total_games, 2),
    }


def compute_days_rest(
    recent_games: List[RecentGame],
    game_date: Optional[str] = None
) -> Optional[int]:
    """Compute days of rest before a game.

    Args:
        recent_games: List of recent games (most recent first)
        game_date: Target game date (YYYY-MM-DD or ISO). Defaults to today.
    """
    if not recent_games:
        return None

    last_game_date = datetime.strptime(recent_games[0]["date"], "%Y-%m-%d")

    if game_date:
        # Handle both "YYYY-MM-DD" and "YYYY-MM-DDTHH:MM:SS" formats
        target = datetime.strptime(game_date.split("T")[0], "%Y-%m-%d")
    else:
        target = datetime.now()

    target = target.replace(hour=0, minute=0, second=0, microsecond=0)
    last_game_date = last_game_date.replace(hour=0, minute=0, second=0, microsecond=0)

    return (target - last_game_date).days


def compute_streak(recent_games: List[RecentGame]) -> Dict[str, Any]:
    """Compute current win/loss streak."""
    if not recent_games:
        return {"type": None, "count": 0}

    first_result = recent_games[0]["result"]
    count = 0

    for game in recent_games:
        if game["result"] == first_result:
            count += 1
        else:
            break

    return {"type": first_result, "count": count}


def compute_games_last_n_days(
    recent_games: List[RecentGame],
    days: int = 7,
    game_date: Optional[str] = None
) -> int:
    """Count games played in the last N days.

    Args:
        recent_games: List of recent games
        days: Number of days to look back
        game_date: Reference date (YYYY-MM-DD or ISO). Defaults to today.
    """
    if not recent_games:
        return 0

    if game_date:
        target = datetime.strptime(game_date.split("T")[0], "%Y-%m-%d")
    else:
        target = datetime.now()

    target = target.replace(hour=0, minute=0, second=0, microsecond=0)
    cutoff = target - timedelta(days=days)
    count = 0

    for game in recent_games:
        gd = datetime.strptime(game["date"], "%Y-%m-%d")
        if gd >= cutoff:
            count += 1

    return count


def compute_schedule_context(
    recent_games: List[RecentGame],
    game_date: Optional[str] = None
) -> TeamSchedule:
    """Compute schedule/situational context for a team.

    Args:
        recent_games: List of recent games
        game_date: Target game date (YYYY-MM-DD or ISO). Defaults to today.
    """
    days_rest = compute_days_rest(recent_games, game_date)
    streak_data = compute_streak(recent_games)
    games_last_7 = compute_games_last_n_days(recent_games, 7, game_date)

    # Format streak as string (e.g., "W3", "L2")
    if streak_data["type"] and streak_data["count"] > 0:
        streak_str = f"{streak_data['type']}{streak_data['count']}"
    else:
        streak_str = "N/A"

    # Compute opponent strength metrics
    total_opp_win_pct = 0.0
    valid_opp_count = 0
    quality_wins = 0
    quality_losses = 0

    for game in recent_games:
        opp_win_pct = game.get("vs_win_pct", 0.0)
        if opp_win_pct > 0:  # Only count if we have valid data
            total_opp_win_pct += opp_win_pct
            valid_opp_count += 1

            # Quality game = opponent is .500 or better
            if opp_win_pct >= 0.5:
                if game["result"] == "W":
                    quality_wins += 1
                else:
                    quality_losses += 1

    recent_opponent_avg_win_pct = round(total_opp_win_pct / valid_opp_count, 3) if valid_opp_count > 0 else 0.0

    return {
        "days_rest": days_rest,
        "streak": streak_str,
        "games_last_7_days": games_last_7,
        "recent_opponent_avg_win_pct": recent_opponent_avg_win_pct,
        "quality_wins": quality_wins,
        "quality_losses": quality_losses,
    }


def generate_signals(
    team1: TeamSnapshot,
    team2: TeamSnapshot,
    home_team: str,
    comparison: MatchupEdges,
    h2h: Optional[H2H],
    team1_players: Optional[TeamPlayers],
    team2_players: Optional[TeamPlayers],
    totals_analysis: TotalsAnalysis,
    team1_recent: List[RecentGame],
    team2_recent: List[RecentGame],
    game_date: Optional[str] = None,
) -> List[str]:
    """Generate contextual signals for the matchup."""
    signals: List[str] = []
    is_team1_home = team1["name"] == home_team
    home_snapshot = team1 if is_team1_home else team2
    away_snapshot = team2 if is_team1_home else team1
    home_recent = team1_recent if is_team1_home else team2_recent
    away_recent = team2_recent if is_team1_home else team1_recent
    home_players = team1_players if is_team1_home else team2_players
    away_players = team2_players if is_team1_home else team1_players

    # === REST/SCHEDULE SIGNALS (Tier 1) ===
    team1_rest = compute_days_rest(team1_recent, game_date)
    team2_rest = compute_days_rest(team2_recent, game_date)

    if team1_rest is not None and team1_rest <= 1:
        rest_label = "playing second game today" if team1_rest == 0 else "on back-to-back"
        signals.append(f"{team1['name']} {rest_label} (fatigue factor)")
    if team2_rest is not None and team2_rest <= 1:
        rest_label = "playing second game today" if team2_rest == 0 else "on back-to-back"
        signals.append(f"{team2['name']} {rest_label} (fatigue factor)")

    # Rest advantage
    if team1_rest is not None and team2_rest is not None:
        rest_diff = team1_rest - team2_rest
        if rest_diff >= 2:
            signals.append(f"{team1['name']} rest advantage ({team1_rest} days vs {team2_rest} days)")
        elif rest_diff <= -2:
            signals.append(f"{team2['name']} rest advantage ({team2_rest} days vs {team1_rest} days)")

    # === STAR PLAYER IMPACT SIGNALS (Tier 1) ===
    if team1_players and not team1_players["full_strength"] and team1_players["star_dependency"] > 22:
        signals.append(f"{team1['name']} missing {team1_players['star_dependency']:.0f}% of offense with key players limited")
    if team2_players and not team2_players["full_strength"] and team2_players["star_dependency"] > 22:
        signals.append(f"{team2['name']} missing {team2_players['star_dependency']:.0f}% of offense with key players limited")

    # === WIN/LOSS STREAK SIGNALS (Tier 2) ===
    team1_streak = compute_streak(team1_recent)
    team2_streak = compute_streak(team2_recent)

    if team1_streak["count"] >= 3:
        streak_word = "won" if team1_streak["type"] == "W" else "lost"
        signals.append(f"{team1['name']} {streak_word} {team1_streak['count']} straight")
    if team2_streak["count"] >= 3:
        streak_word = "won" if team2_streak["type"] == "W" else "lost"
        signals.append(f"{team2['name']} {streak_word} {team2_streak['count']} straight")

    # NO H2H WARNING
    if not h2h:
        signals.append("No recent H2H history - projections based on current season stats only")

    # === QUARTER TENDENCIES FROM H2H (Tier 1) ===
    if h2h and h2h.get("quarters"):
        q = h2h["quarters"]

        # Q1 tendency
        q1_diff = q["team1_q1_avg"] - q["team2_q1_avg"]
        if abs(q1_diff) >= 2:
            q1_leader = team1["name"] if q1_diff > 0 else team2["name"]
            signals.append(f"{q1_leader} starts faster (+{abs(q1_diff):.1f} Q1 avg in H2H)")

        # Q4 tendency (closing strength)
        q4_diff = q["team1_q4_avg"] - q["team2_q4_avg"]
        if abs(q4_diff) >= 2:
            q4_leader = team1["name"] if q4_diff > 0 else team2["name"]
            signals.append(f"{q4_leader} stronger closer (+{abs(q4_diff):.1f} Q4 avg in H2H)")

        # Halftime leader reliability
        if q["halftime_leader_wins_pct"] >= 0.65:
            signals.append(f"Halftime leader wins {q['halftime_leader_wins_pct'] * 100:.0f}% in this matchup")

        # Half scoring tendency
        half_diff = q["avg_first_half"] - q["avg_second_half"]
        if abs(half_diff) >= 3:
            if half_diff > 0:
                signals.append(f"H2H games front-loaded (1H avg {q['avg_first_half']} vs 2H avg {q['avg_second_half']})")
            else:
                signals.append(f"H2H games back-loaded (2H avg {q['avg_second_half']} vs 1H avg {q['avg_first_half']})")

    # AVAILABILITY SIGNALS
    if team1_players and not team1_players["full_strength"]:
        concerns = team1_players["availability_concerns"][:2]
        signals.append(f"{team1['name']} injury concerns: {', '.join(concerns)}")
    if team2_players and not team2_players["full_strength"]:
        concerns = team2_players["availability_concerns"][:2]
        signals.append(f"{team2['name']} injury concerns: {', '.join(concerns)}")

    # Form signals (based on last 10 games)
    if team1["last_ten_pct"] >= 0.7:
        signals.append(f"{team1['name']} hot form ({team1['last_ten']} L10)")
    elif team1["last_ten_pct"] <= 0.3:
        signals.append(f"{team1['name']} struggling ({team1['last_ten']} L10)")

    if team2["last_ten_pct"] >= 0.7:
        signals.append(f"{team2['name']} hot form ({team2['last_ten']} L10)")
    elif team2["last_ten_pct"] <= 0.3:
        signals.append(f"{team2['name']} struggling ({team2['last_ten']} L10)")

    # Home/away performance
    if home_snapshot["home_win_pct"] > 0.6:
        signals.append(f"{home_snapshot['name']} strong at home ({home_snapshot['home_record']})")
    elif home_snapshot["home_win_pct"] < 0.4:
        signals.append(f"{home_snapshot['name']} struggling at home ({home_snapshot['home_record']})")

    if away_snapshot["away_win_pct"] > 0.55:
        signals.append(f"{away_snapshot['name']} solid on road ({away_snapshot['away_record']})")
    elif away_snapshot["away_win_pct"] < 0.35:
        signals.append(f"{away_snapshot['name']} poor on road ({away_snapshot['away_record']})")

    # Scoring edge
    if abs(comparison["ppg"]) >= 3:
        better = team1["name"] if comparison["ppg"] > 0 else team2["name"]
        signals.append(f"{better} +{abs(comparison['ppg']):.1f} PPG edge")

    # Net rating edge
    if abs(comparison["net_rating"]) >= 3:
        better = team1["name"] if comparison["net_rating"] > 0 else team2["name"]
        sign = "+" if comparison["net_rating"] > 0 else ""
        signals.append(f"{better} significantly better net rating ({sign}{comparison['net_rating']:.1f})")

    # H2H signals
    if h2h:
        summary = h2h["summary"]
        patterns = h2h["patterns"]
        recent = h2h["recent"]

        if recent["games_last_2_seasons"] >= 3:
            if recent["team1_wins_last_2_seasons"] > recent["team2_wins_last_2_seasons"] + 1:
                signals.append(f"{team1['name']} {recent['team1_wins_last_2_seasons']}-{recent['team2_wins_last_2_seasons']} in recent H2H")
            elif recent["team2_wins_last_2_seasons"] > recent["team1_wins_last_2_seasons"] + 1:
                signals.append(f"{team2['name']} {recent['team2_wins_last_2_seasons']}-{recent['team1_wins_last_2_seasons']} in recent H2H")

        if summary["recent_trend"] != "balanced":
            hot_team = team1["name"] if summary["recent_trend"] == "team1_hot" else team2["name"]
            signals.append(f"{hot_team} won 4+ of last 5 H2H meetings")

        # O/U SIGNALS from H2H patterns
        if patterns["high_scoring_pct"] > 0.6:
            signals.append(f"High-scoring matchup ({patterns['high_scoring_pct'] * 100:.0f}% H2H games over 220)")
        elif patterns["high_scoring_pct"] < 0.3:
            signals.append(f"Lower-scoring matchup (only {patterns['high_scoring_pct'] * 100:.0f}% H2H games over 220)")
        if patterns["close_game_pct"] > 0.4:
            signals.append(f"Competitive series ({patterns['close_game_pct'] * 100:.0f}% decided by 5 or less)")

    # Pace-based O/U signal
    if comparison["combined_pace"] > 105:
        signals.append(f"Fast-paced matchup (avg {comparison['combined_pace']} possessions) - lean OVER")
    elif comparison["combined_pace"] < 98:
        signals.append(f"Slow-paced matchup (avg {comparison['combined_pace']} possessions) - lean UNDER")

    # Recent scoring trend
    if abs(totals_analysis["recent_scoring_trend"]) > 5:
        if totals_analysis["recent_scoring_trend"] > 0:
            signals.append(f"Both teams scoring above season avg in recent games (+{totals_analysis['recent_scoring_trend']} combined)")
        else:
            signals.append(f"Both teams scoring below season avg in recent games ({totals_analysis['recent_scoring_trend']} combined)")

    # High variance warning
    if totals_analysis["h2h_total_variance"] > 15:
        signals.append(f"High-variance H2H (±{totals_analysis['h2h_total_variance']} pts std dev in totals)")

    # === H2H vs SEASON PERFORMANCE SIGNALS ===
    if h2h and h2h.get("matchup_stats"):
        ms = h2h["matchup_stats"]
        t1_h2h = ms["team1"]
        t2_h2h = ms["team2"]

        # FG% comparison (H2H vs season)
        t1_fgp_diff = t1_h2h["avg_fgp"] - team1["fgp"]
        t2_fgp_diff = t2_h2h["avg_fgp"] - team2["fgp"]

        if abs(t1_fgp_diff) >= 3:
            direction = "elevated" if t1_fgp_diff > 0 else "suppressed"
            signals.append(f"{team1['name']} FG% {direction} vs {team2['name']}: {t1_h2h['avg_fgp']}% H2H vs {team1['fgp']}% season")
        if abs(t2_fgp_diff) >= 3:
            direction = "elevated" if t2_fgp_diff > 0 else "suppressed"
            signals.append(f"{team2['name']} FG% {direction} vs {team1['name']}: {t2_h2h['avg_fgp']}% H2H vs {team2['fgp']}% season")

        # 3P% comparison
        t1_tpp_diff = t1_h2h["avg_tpp"] - team1["tpp"]
        t2_tpp_diff = t2_h2h["avg_tpp"] - team2["tpp"]

        if abs(t1_tpp_diff) >= 4:
            direction = "hot" if t1_tpp_diff > 0 else "cold"
            signals.append(f"{team1['name']} {direction} from 3 vs {team2['name']}: {t1_h2h['avg_tpp']}% H2H vs {team1['tpp']}% season")
        if abs(t2_tpp_diff) >= 4:
            direction = "hot" if t2_tpp_diff > 0 else "cold"
            signals.append(f"{team2['name']} {direction} from 3 vs {team1['name']}: {t2_h2h['avg_tpp']}% H2H vs {team2['tpp']}% season")

        # Turnover comparison
        t1_tov_diff = t1_h2h["avg_turnovers"] - team1["topg"]
        t2_tov_diff = t2_h2h["avg_turnovers"] - team2["topg"]

        if abs(t1_tov_diff) >= 2:
            direction = "careless" if t1_tov_diff > 0 else "careful"
            signals.append(f"{team1['name']} more {direction} vs {team2['name']}: {t1_h2h['avg_turnovers']} H2H vs {team1['topg']} season TOV")
        if abs(t2_tov_diff) >= 2:
            direction = "careless" if t2_tov_diff > 0 else "careful"
            signals.append(f"{team2['name']} more {direction} vs {team1['name']}: {t2_h2h['avg_turnovers']} H2H vs {team2['topg']} season TOV")

        # Rebounding comparison
        t1_reb_diff = t1_h2h["avg_rebounds"] - team1["rpg"]
        t2_reb_diff = t2_h2h["avg_rebounds"] - team2["rpg"]

        if abs(t1_reb_diff) >= 3:
            direction = "dominates" if t1_reb_diff > 0 else "struggles on"
            signals.append(f"{team1['name']} {direction} boards vs {team2['name']}: {t1_h2h['avg_rebounds']} H2H vs {team1['rpg']} season")
        if abs(t2_reb_diff) >= 3:
            direction = "dominates" if t2_reb_diff > 0 else "struggles on"
            signals.append(f"{team2['name']} {direction} boards vs {team1['name']}: {t2_h2h['avg_rebounds']} H2H vs {team2['rpg']} season")

    return signals


def compute_totals_analysis(
    team1: TeamSnapshot,
    team2: TeamSnapshot,
    h2h_summary: Optional[H2HSummary],
    h2h_results: Optional[H2HResults],
    team1_recent: List[RecentGame],
    team2_recent: List[RecentGame]
) -> TotalsAnalysis:
    """Compute totals/O-U analysis."""
    # Current combined PPG
    current_total = team1["ppg"] + team2["ppg"]

    # League average as fallback baseline
    league_avg_total = 225

    # H2H historical average total
    h2h_avg_total = h2h_summary.get("avg_total_points", league_avg_total) if h2h_summary else league_avg_total

    # Expected total: weight current form vs H2H/baseline
    h2h_weight = 0.4 if h2h_summary else 0.2
    expected_total = round(current_total * (1 - h2h_weight) + h2h_avg_total * h2h_weight, 1)

    # How each team's current scoring compares to their H2H average
    team1_h2h_scoring_diff = round(team1["ppg"] - h2h_summary["team1_avg_points"], 1) if h2h_summary else 0.0
    team2_h2h_scoring_diff = round(team2["ppg"] - h2h_summary["team2_avg_points"], 1) if h2h_summary else 0.0

    # Calculate margin and total volatility
    margin_volatility = 0.0
    h2h_total_variance = 0.0
    if h2h_results:
        all_games = [g for games in h2h_results.values() for g in games]
        if len(all_games) > 1:
            # Margin volatility: std dev of point differentials
            margins = [abs(g["point_diff"]) for g in all_games]
            avg_margin = sum(margins) / len(margins)
            margin_var = sum((m - avg_margin) ** 2 for m in margins) / len(margins)
            margin_volatility = round(math.sqrt(margin_var), 1)

            # H2H total variance: std dev of combined scores
            totals = [g["home_points"] + g["visitor_points"] for g in all_games]
            avg_total = sum(totals) / len(totals)
            total_var = sum((t - avg_total) ** 2 for t in totals) / len(totals)
            h2h_total_variance = round(math.sqrt(total_var), 1)

    # Pace-adjusted total
    combined_pace = (team1["pace"] + team2["pace"]) / 2
    combined_ortg = (team1["ortg"] + team2["ortg"]) / 2
    pace_adjusted_total = round(combined_pace * combined_ortg / 100, 1)

    # Defense factor
    defense_factor = round((team1["drtg"] + team2["drtg"]) / 2, 1)

    # Recent scoring trend
    recent_scoring_trend = 0.0
    if team1_recent and team2_recent:
        team1_recent_avg = 0.0
        for g in team1_recent:
            pts = g["score"].split("-")
            team1_recent_avg += int(pts[0]) + int(pts[1])
        team1_recent_avg /= len(team1_recent)

        team2_recent_avg = 0.0
        for g in team2_recent:
            pts = g["score"].split("-")
            team2_recent_avg += int(pts[0]) + int(pts[1])
        team2_recent_avg /= len(team2_recent)

        season_avg_total = team1["ppg"] + team1["opp_ppg"] + team2["ppg"] + team2["opp_ppg"]
        recent_avg_total = team1_recent_avg + team2_recent_avg
        recent_scoring_trend = round((recent_avg_total - season_avg_total) / 2, 1)

    return {
        "expected_total": expected_total,
        "total_diff_from_h2h": round(current_total - h2h_avg_total, 1),
        "team1_h2h_scoring_diff": team1_h2h_scoring_diff,
        "team2_h2h_scoring_diff": team2_h2h_scoring_diff,
        "margin_volatility": margin_volatility,
        "h2h_total_variance": h2h_total_variance,
        "pace_adjusted_total": pace_adjusted_total,
        "defense_factor": defense_factor,
        "recent_scoring_trend": recent_scoring_trend,
    }


def build_team_players(
    players: List[ProcessedPlayerStats],
    team_games: int,
    team_ppg: float,
    rotation_size: int = 6
) -> Optional[TeamPlayers]:
    """Build team players analysis."""
    if not players:
        return None

    # Build rotation (top N players by MPG)
    rotation: List[RotationPlayer] = [
        {
            "name": p["name"],
            "ppg": p["ppg"],
            "plus_minus": p["plus_minus"],
            "games": p["games"],
        }
        for p in players[:rotation_size]
    ]

    # Compute availability concerns
    availability_threshold = 0.7
    availability_concerns: List[str] = []
    for player in players:
        availability_pct = player["games"] / team_games if team_games > 0 else 1.0
        if availability_pct < availability_threshold:
            availability_concerns.append(f"{player['name']} ({player['games']}/{team_games} games)")
    full_strength = len(availability_concerns) == 0

    # Sort by different metrics for insights
    by_ppg = sorted(players, key=lambda x: x["ppg"], reverse=True)
    by_apg = sorted(players, key=lambda x: x["apg"], reverse=True)
    by_pm = sorted(players, key=lambda x: x["plus_minus"], reverse=True)

    # Top 3 scorers string
    top_scorers = ", ".join(
        f"{p['name'].split()[-1]} {p['ppg']}"
        for p in by_ppg[:3]
    )

    # Playmaker (top APG)
    playmaker_player = by_apg[0]
    playmaker_availability = playmaker_player["games"] / team_games if team_games > 0 else 1.0
    if playmaker_availability < 0.7:
        playmaker = f"{playmaker_player['name']} {playmaker_player['apg']} APG (limited: {playmaker_player['games']} games)"
    else:
        playmaker = f"{playmaker_player['name']} {playmaker_player['apg']} APG"

    # Hot hand (best plus/minus)
    hot_player = by_pm[0]
    hot_availability = hot_player["games"] / team_games if team_games > 0 else 1.0
    pm_sign = "+" if hot_player["plus_minus"] > 0 else ""
    if hot_availability < 0.7:
        hot_hand = f"{hot_player['name'].split()[-1]} {pm_sign}{hot_player['plus_minus']} (limited: {hot_player['games']} games)"
    else:
        hot_hand = f"{hot_player['name'].split()[-1]} {pm_sign}{hot_player['plus_minus']}"

    # Compute metrics
    top_scorer = by_ppg[0]
    star_dependency = round(top_scorer["ppg"] / team_ppg * 100, 1) if team_ppg > 0 else 0.0

    mpg_values = [p["mpg"] for p in players]
    avg_mpg = sum(mpg_values) / len(mpg_values)
    variance = sum((mpg - avg_mpg) ** 2 for mpg in mpg_values) / len(mpg_values)
    depth_score = round(math.sqrt(variance), 1)

    bench_players = players[5:8]
    bench_scoring = round(sum(p["ppg"] for p in bench_players), 1)

    # Depth rating interpretation
    depth_rating = f"balanced ({depth_score} MPG std dev)" if depth_score < 5 else f"star-dependent ({depth_score} MPG std dev)"

    return {
        "rotation": rotation,
        "availability_concerns": availability_concerns,
        "full_strength": full_strength,
        "top_scorers": top_scorers,
        "playmaker": playmaker,
        "hot_hand": hot_hand,
        "star_dependency": star_dependency,
        "depth_rating": depth_rating,
        "bench_scoring": bench_scoring,
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
    team1_snapshot = build_team_snapshot(team1_name, team1_standing, team1_current_stats)
    team2_snapshot = build_team_snapshot(team2_name, team2_standing, team2_current_stats)

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
