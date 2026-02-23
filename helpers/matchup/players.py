"""Team player analysis computations."""

import math
from typing import List, Optional

from ..api import ProcessedPlayerStats
from .types import AVAILABILITY_THRESHOLD, RotationPlayer, TeamPlayers


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
    availability_concerns: List[str] = []
    for player in players:
        availability_pct = player["games"] / team_games if team_games > 0 else 1.0
        if availability_pct < AVAILABILITY_THRESHOLD:
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
    if playmaker_availability < AVAILABILITY_THRESHOLD:
        playmaker = f"{playmaker_player['name']} {playmaker_player['apg']} APG (limited: {playmaker_player['games']} games)"
    else:
        playmaker = f"{playmaker_player['name']} {playmaker_player['apg']} APG"

    # Hot hand (best plus/minus)
    hot_player = by_pm[0]
    hot_availability = hot_player["games"] / team_games if team_games > 0 else 1.0
    pm_sign = "+" if hot_player["plus_minus"] > 0 else ""
    if hot_availability < AVAILABILITY_THRESHOLD:
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

    bench_players = players[5:]
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
