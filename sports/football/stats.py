"""Poisson-based goal probability model for football matches."""

from math import exp, lgamma, log

DEFAULT_LEAGUE_AVG = 2.68
MIN_XG = 0.2


def poisson_pmf(k: int, lam: float) -> float:
    """P(X=k) for Poisson distribution with rate lambda.

    Uses log-space computation to avoid overflow for large k or lambda.
    """
    if k < 0:
        return 0.0
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return exp(-lam + k * log(lam) - lgamma(k + 1))


def compute_season_averages(matches: list[dict], team_id: str) -> dict:
    """Compute goal averages from a list of matches for a team.

    Returns dict with goals_for_avg, goals_against_avg, and
    home/away splits (home_gf_avg, home_ga_avg, away_gf_avg, away_ga_avg).
    """
    total_for = 0
    total_against = 0
    home_for = 0
    home_against = 0
    away_for = 0
    away_against = 0
    home_count = 0
    away_count = 0

    for match in matches:
        try:
            h_score = int(match.get("match_hometeam_score", 0))
            a_score = int(match.get("match_awayteam_score", 0))
        except (ValueError, TypeError):
            continue

        home_id = str(match.get("match_hometeam_id", ""))
        away_id = str(match.get("match_awayteam_id", ""))
        is_home = home_id == str(team_id)

        if not is_home and away_id != str(team_id):
            continue

        if is_home:
            total_for += h_score
            total_against += a_score
            home_for += h_score
            home_against += a_score
            home_count += 1
        else:
            total_for += a_score
            total_against += h_score
            away_for += a_score
            away_against += h_score
            away_count += 1

    total = home_count + away_count
    if total == 0:
        return {
            "goals_for_avg": 0.0,
            "goals_against_avg": 0.0,
            "home_gf_avg": 0.0,
            "home_ga_avg": 0.0,
            "away_gf_avg": 0.0,
            "away_ga_avg": 0.0,
            "matches": 0,
            "home_matches": 0,
            "away_matches": 0,
        }

    return {
        "goals_for_avg": total_for / total,
        "goals_against_avg": total_against / total,
        "home_gf_avg": home_for / home_count if home_count else 0.0,
        "home_ga_avg": home_against / home_count if home_count else 0.0,
        "away_gf_avg": away_for / away_count if away_count else 0.0,
        "away_ga_avg": away_against / away_count if away_count else 0.0,
        "matches": total,
        "home_matches": home_count,
        "away_matches": away_count,
    }


def compute_expected_goals(
    home_avg_for: float,
    home_avg_against: float,
    away_avg_for: float,
    away_avg_against: float,
    league_avg: float = DEFAULT_LEAGUE_AVG,
) -> tuple[float, float]:
    """Compute expected goals for home and away teams.

    Uses attack/defense strength indices relative to league average.
    Returns (home_xG, away_xG).
    """
    if league_avg <= 0:
        return (0.0, 0.0)

    half_avg = league_avg / 2

    home_attack = home_avg_for / half_avg
    home_defense = home_avg_against / half_avg
    away_attack = away_avg_for / half_avg
    away_defense = away_avg_against / half_avg

    home_xg = max(home_attack * away_defense * half_avg, MIN_XG)
    away_xg = max(away_attack * home_defense * half_avg, MIN_XG)

    return (home_xg, away_xg)


def compute_goal_probabilities(
    home_xg: float, away_xg: float, max_goals: int = 12
) -> dict:
    """Compute goal market probabilities from expected goals.

    Returns dict with over_1_5, under_3_5, under_4_5, and the full
    probability matrix dimensions.
    """
    # Build joint probability matrix
    matrix = []
    for i in range(max_goals + 1):
        row = []
        for j in range(max_goals + 1):
            row.append(poisson_pmf(i, home_xg) * poisson_pmf(j, away_xg))
        matrix.append(row)

    # Sum probabilities by total goals
    total_probs = {}
    for i in range(max_goals + 1):
        for j in range(max_goals + 1):
            total = i + j
            total_probs[total] = total_probs.get(total, 0.0) + matrix[i][j]

    p_under_1_5 = sum(total_probs.get(t, 0.0) for t in range(2))
    p_under_2_5 = sum(total_probs.get(t, 0.0) for t in range(3))
    p_under_3_5 = sum(total_probs.get(t, 0.0) for t in range(4))
    p_under_4_5 = sum(total_probs.get(t, 0.0) for t in range(5))

    return {
        "over_1_5": 1.0 - p_under_1_5,
        "under_1_5": p_under_1_5,
        "over_2_5": 1.0 - p_under_2_5,
        "under_2_5": p_under_2_5,
        "under_3_5": p_under_3_5,
        "over_3_5": 1.0 - p_under_3_5,
        "under_4_5": p_under_4_5,
        "over_4_5": 1.0 - p_under_4_5,
    }


def compute_live_probabilities(
    home_xg: float,
    away_xg: float,
    home_goals: int,
    away_goals: int,
    minute: int,
    max_goals: int = 12,
) -> dict:
    """Compute goal probabilities conditioned on current score and time.

    Scales pre-game xG by remaining time fraction, then computes Poisson
    probabilities for additional goals. Final totals = current + remaining.
    """
    remaining = max(90 - minute, 0) / 90
    rem_home_xg = max(home_xg * remaining, 0.0)
    rem_away_xg = max(away_xg * remaining, 0.0)

    current_total = home_goals + away_goals

    # Poisson distribution for additional goals in remaining time
    total_probs: dict[int, float] = {}
    for i in range(max_goals + 1):
        for j in range(max_goals + 1):
            final_total = current_total + i + j
            p = poisson_pmf(i, rem_home_xg) * poisson_pmf(j, rem_away_xg)
            total_probs[final_total] = total_probs.get(final_total, 0.0) + p

    p_under_1_5 = sum(total_probs.get(t, 0.0) for t in range(2))
    p_under_2_5 = sum(total_probs.get(t, 0.0) for t in range(3))
    p_under_3_5 = sum(total_probs.get(t, 0.0) for t in range(4))
    p_under_4_5 = sum(total_probs.get(t, 0.0) for t in range(5))

    return {
        "over_1_5": 1.0 - p_under_1_5,
        "under_1_5": p_under_1_5,
        "over_2_5": 1.0 - p_under_2_5,
        "under_2_5": p_under_2_5,
        "under_3_5": p_under_3_5,
        "over_3_5": 1.0 - p_under_3_5,
        "under_4_5": p_under_4_5,
        "over_4_5": 1.0 - p_under_4_5,
    }
