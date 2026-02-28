"""Football goal analysis orchestration pipeline."""

import html as html_mod
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

from .averages import DOMESTIC_LEAGUES, ensure_averages, get_league_avg, get_league_home_away_avg
from .client import (
    LEAGUES,
    close_session,
    fetch_matches_for_date,
    fetch_standings,
    fetch_team_matches,
)
from .stats import (
    DEFAULT_LEAGUE_AVG,
    compute_expected_goals,
    compute_goal_probabilities,
    compute_live_probabilities,
    compute_season_averages,
)

OUTPUT_DIR = Path(__file__).parent.parent.parent / "output" / "football"

MATCH_HISTORY_DAYS = 120


def _build_standings_lookup(standings: list[dict]) -> dict[str, dict]:
    """Build team_id → standing info lookup from API standings data."""
    lookup = {}
    for entry in standings:
        tid = str(entry.get("team_id", ""))
        if tid:
            lookup[tid] = {
                "position": entry.get("overall_league_position"),
                "played": entry.get("overall_league_payed"),
                "won": entry.get("overall_league_W"),
                "drawn": entry.get("overall_league_D"),
                "lost": entry.get("overall_league_L"),
                "gf": entry.get("overall_league_GF"),
                "ga": entry.get("overall_league_GA"),
                "pts": entry.get("overall_league_PTS"),
            }
    return lookup


async def _fetch_team_history(team_id: str, date: str) -> list[dict]:
    """Fetch a team's last ~4 months of matches, excluding match day."""
    end = datetime.strptime(date, "%Y-%m-%d")
    start = end - timedelta(days=MATCH_HISTORY_DAYS)
    yesterday = end - timedelta(days=1)
    return await fetch_team_matches(
        team_id, start.strftime("%Y-%m-%d"), yesterday.strftime("%Y-%m-%d")
    )


async def analyze_match(
    match: dict,
    date: str,
    league_avg: float = DEFAULT_LEAGUE_AVG,
    league_home_avg: float | None = None,
    league_away_avg: float | None = None,
    standings: dict[str, dict] | None = None,
) -> dict | None:
    """Run full analysis on a single match."""
    home = match.get("match_hometeam_name", "")
    away = match.get("match_awayteam_name", "")
    home_id = str(match.get("match_hometeam_id", ""))
    away_id = str(match.get("match_awayteam_id", ""))
    league = match.get("league_name", "")

    if not home or not away:
        return None

    lg_home = league_home_avg if league_home_avg is not None else league_avg / 2
    lg_away = league_away_avg if league_away_avg is not None else league_avg / 2

    logger.info("  Analyzing: %s vs %s (league avg: %.2f, H:%.2f A:%.2f)", home, away, league_avg, lg_home, lg_away)

    home_hist = await _fetch_team_history(home_id, date)
    away_hist = await _fetch_team_history(away_id, date)

    home_avg = compute_season_averages(home_hist, home_id)
    away_avg = compute_season_averages(away_hist, away_id)

    home_xg, away_xg = compute_expected_goals(
        _avg_or_default(home_avg, "home_gf_avg", "goals_for_avg", lg_home),
        _avg_or_default(home_avg, "home_ga_avg", "goals_against_avg", lg_away),
        _avg_or_default(away_avg, "away_gf_avg", "goals_for_avg", lg_away),
        _avg_or_default(away_avg, "away_ga_avg", "goals_against_avg", lg_home),
        league_home_avg=lg_home,
        league_away_avg=lg_away,
    )

    probabilities = compute_goal_probabilities(home_xg, away_xg)

    home_standing = standings.get(home_id) if standings else None
    away_standing = standings.get(away_id) if standings else None

    return {
        "home": home,
        "away": away,
        "league": league,
        "league_avg": league_avg,
        "venue": match.get("match_stadium", ""),
        "time": match.get("match_time", ""),
        "home_avg": home_avg,
        "away_avg": away_avg,
        "home_xg": home_xg,
        "away_xg": away_xg,
        "probabilities": probabilities,
        "home_standing": home_standing,
        "away_standing": away_standing,
    }


MIN_VENUE_MATCHES = 3
VENUE_REGRESSION_WEIGHT = 6


def _avg_or_default(avg: dict, primary: str, fallback: str, default: float) -> float:
    """Get a venue-specific average, regressed toward overall average.

    Blends venue splits toward the overall average to reduce small-sample
    noise. With VENUE_REGRESSION_WEIGHT=6, a 12-game venue split is weighted
    2:1 against the overall; a 6-game split is weighted 1:1.
    """
    if avg.get("matches", 0) == 0:
        return default

    overall = avg.get(fallback, default)

    if primary.startswith("home_"):
        venue_count = avg.get("home_matches", 0)
    elif primary.startswith("away_"):
        venue_count = avg.get("away_matches", 0)
    else:
        return avg.get(primary, default)

    if venue_count < MIN_VENUE_MATCHES:
        return overall

    venue_val = avg.get(primary)
    if venue_val is None:
        return overall

    return (venue_val * venue_count + overall * VENUE_REGRESSION_WEIGHT) / (venue_count + VENUE_REGRESSION_WEIGHT)


def _ordinal(n) -> str:
    n = int(n)
    suffix = "th" if 11 <= n % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _esc(val) -> str:
    return html_mod.escape(str(val))


def _standings_row(name: str, st: dict) -> str:
    return (
        f"<tr><td>{_esc(name)}</td><td>{_ordinal(st['position'])}</td>"
        f"<td>{st['played']}</td><td>{st['won']}</td><td>{st['drawn']}</td>"
        f"<td>{st['lost']}</td><td>{st['gf']}</td><td>{st['ga']}</td>"
        f"<td><strong>{st['pts']}</strong></td></tr>"
    )


def _standings_table(a: dict) -> str:
    home_st = a.get("home_standing")
    away_st = a.get("away_standing")
    if not home_st and not away_st:
        return ""
    rows = ""
    if home_st:
        rows += _standings_row(a["home"], home_st)
    if away_st:
        rows += _standings_row(a["away"], away_st)
    return (
        '<table class="standings"><thead><tr>'
        "<th>Team</th><th>Pos</th><th>P</th><th>W</th><th>D</th>"
        "<th>L</th><th>GF</th><th>GA</th><th>Pts</th>"
        f"</tr></thead><tbody>{rows}</tbody></table>"
    )


def _stats_row(name: str, avg: dict) -> str | None:
    if avg.get("matches", 0) == 0:
        return None
    cells = (
        f"<td>{_esc(name)}</td>"
        f"<td>{avg['goals_for_avg']:.2f}</td>"
        f"<td>{avg['goals_against_avg']:.2f}</td>"
    )
    if avg.get("home_matches", 0) >= MIN_VENUE_MATCHES:
        cells += f"<td>{avg.get('home_gf_avg', 0):.2f} / {avg.get('home_ga_avg', 0):.2f}</td>"
    else:
        cells += "<td>—</td>"
    if avg.get("away_matches", 0) >= MIN_VENUE_MATCHES:
        cells += f"<td>{avg.get('away_gf_avg', 0):.2f} / {avg.get('away_ga_avg', 0):.2f}</td>"
    else:
        cells += "<td>—</td>"
    return f"<tr>{cells}</tr>"


def _stats_table(a: dict) -> str:
    home_row = _stats_row(a["home"], a["home_avg"])
    away_row = _stats_row(a["away"], a["away_avg"])
    if not home_row and not away_row:
        return ""
    rows = (home_row or "") + (away_row or "")
    return (
        '<table class="stats"><thead><tr>'
        "<th>Team</th><th>GF/G</th><th>GA/G</th><th>Home</th><th>Away</th>"
        f"</tr></thead><tbody>{rows}</tbody></table>"
    )


def _prob_class(val: float) -> str:
    if val >= 0.75:
        return "high"
    if val >= 0.50:
        return "mid"
    return "low"


def render_match_section(analysis: dict) -> str:
    """Render a single match analysis as an HTML card."""
    a = analysis
    probs = a["probabilities"]
    total_xg = a["home_xg"] + a["away_xg"]
    league_avg = a.get("league_avg", DEFAULT_LEAGUE_AVG)

    venue = f' — {_esc(a["venue"])}' if a.get("venue") else ""
    header = (
        f'<div class="match-card">'
        f'<div class="match-header">'
        f'<h2>{_esc(a["home"])} vs {_esc(a["away"])}</h2>'
        f'<span class="meta">{_esc(a["league"])} · {_esc(a["time"])}{venue}</span>'
        f'</div>'
    )

    standings = _standings_table(a)
    stats = _stats_table(a)

    prob_grid = (
        '<div class="prob-grid">'
        f'<div class="prob {_prob_class(probs["over_1_5"])}"><span class="label">Over 1.5</span><span class="val">{probs["over_1_5"]:.0%}</span></div>'
        f'<div class="prob {_prob_class(probs["over_2_5"])}"><span class="label">Over 2.5</span><span class="val">{probs["over_2_5"]:.0%}</span></div>'
        f'<div class="prob {_prob_class(probs["under_3_5"])}"><span class="label">Under 3.5</span><span class="val">{probs["under_3_5"]:.0%}</span></div>'
        f'<div class="prob {_prob_class(probs["under_4_5"])}"><span class="label">Under 4.5</span><span class="val">{probs["under_4_5"]:.0%}</span></div>'
        '</div>'
    )

    xg_bar = (
        '<div class="xg-row">'
        f'<span class="xg-team">{_esc(a["home"])} <strong>{a["home_xg"]:.2f}</strong></span>'
        f'<span class="xg-total">Total xG {total_xg:.2f}</span>'
        f'<span class="xg-team"><strong>{a["away_xg"]:.2f}</strong> {_esc(a["away"])}</span>'
        '</div>'
        f'<div class="league-avg">League avg: {league_avg:.2f} goals/game</div>'
    )

    return f"{header}{standings}{stats}{prob_grid}{xg_bar}</div>"


_CSS = """\
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
       background: #f0f2f5; color: #1a1a2e; padding: 24px; max-width: 800px; margin: 0 auto; }
h1 { font-size: 1.4rem; margin-bottom: 20px; color: #1a1a2e; }
.match-card { background: #fff; border-radius: 10px; padding: 20px; margin-bottom: 16px;
              box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
.match-header h2 { font-size: 1.15rem; margin-bottom: 2px; }
.match-header .meta { font-size: 0.85rem; color: #666; }
table { width: 100%; border-collapse: collapse; margin: 12px 0; font-size: 0.85rem; }
th { background: #f7f8fa; text-align: left; padding: 6px 10px; font-weight: 600; border-bottom: 2px solid #e5e7eb; }
td { padding: 6px 10px; border-bottom: 1px solid #f0f0f0; }
.prob-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin: 14px 0; }
.prob { text-align: center; padding: 10px 6px; border-radius: 8px; background: #f7f8fa; }
.prob .label { display: block; font-size: 0.75rem; color: #888; margin-bottom: 2px; }
.prob .val { display: block; font-size: 1.1rem; font-weight: 700; }
.prob.high .val { color: #16a34a; }
.prob.mid .val { color: #ca8a04; }
.prob.low .val { color: #9ca3af; }
.xg-row { display: flex; justify-content: space-between; align-items: center;
          padding: 10px 0; font-size: 0.95rem; }
.xg-total { color: #666; font-size: 0.85rem; }
.league-avg { text-align: center; font-size: 0.8rem; color: #999; padding-bottom: 4px; }
.live-grid { border-top: 2px solid #3b82f6; margin-top: 14px; padding-top: 12px; }
.live-header { font-size: 0.9rem; font-weight: 600; color: #3b82f6; margin-bottom: 8px; }
"""


def render_report(analyses: list[dict], date: str) -> str:
    """Render full analysis report as an HTML page."""
    cards = "\n".join(render_match_section(a) for a in analyses)
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        f"<title>Football Analysis — {_esc(date)}</title>"
        f"<style>{_CSS}</style></head><body>"
        f"<h1>Football Goal Analysis — {_esc(date)}</h1>"
        f"{cards}</body></html>"
    )


async def run_analysis(
    league: str,
    date: str | None = None,
):
    """Main entry point: fetch matches, analyze, write report."""
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")

    league_id = LEAGUES.get(league)
    if not league_id:
        logger.error("Unknown league '%s'. Available: %s", league, ", ".join(LEAGUES.keys()))
        return

    logger.info("Fetching matches for %s (%s)", date, league)
    try:
        averages = await ensure_averages()
        lg_avg = get_league_avg(league, averages)
        lg_home, lg_away = get_league_home_away_avg(league, averages)
        logger.info("Using league average: %.2f goals/game (H:%.2f A:%.2f)", lg_avg, lg_home, lg_away)

        standings_lookup = None
        if league in DOMESTIC_LEAGUES:
            try:
                raw_standings = await fetch_standings(league_id)
                standings_lookup = _build_standings_lookup(raw_standings)
                logger.info("Loaded standings: %d teams", len(standings_lookup))
            except Exception as e:
                logger.warning("Could not fetch standings: %s", e)

        all_matches = await fetch_matches_for_date(date, league_id)

        if not all_matches:
            logger.info("No matches found.")
            return

        logger.info("Found %d matches", len(all_matches))

        analyses = []
        for match in all_matches:
            result = await analyze_match(
                match, date, league_avg=lg_avg,
                league_home_avg=lg_home, league_away_avg=lg_away,
                standings=standings_lookup,
            )
            if result:
                analyses.append(result)

        if not analyses:
            logger.info("No matches could be analyzed.")
            return

        report = render_report(analyses, date)

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        out_path = OUTPUT_DIR / f"{league}.html"
        out_path.write_text(report)
        logger.info("Report written to %s", out_path)
        logger.info("Analyzed %d matches", len(analyses))
    finally:
        await close_session()


def merge_reports() -> Path | None:
    """Merge all league HTML reports in OUTPUT_DIR into a single all.html."""
    if not OUTPUT_DIR.exists():
        logger.info("No output directory found.")
        return None

    league_files = sorted(OUTPUT_DIR.glob("*.html"))
    league_files = [f for f in league_files if f.name != "all.html"]

    if not league_files:
        logger.info("No league reports to merge.")
        return None

    cards: list[str] = []

    all_path = OUTPUT_DIR / "all.html"
    if all_path.exists():
        existing = all_path.read_text()
        start = existing.find('<div class="match-card">')
        end = existing.rfind("</div>")
        if start != -1 and end != -1:
            cards.append(existing[start : end + len("</div>")])

    for path in league_files:
        html = path.read_text()
        start = html.find('<div class="match-card">')
        end = html.rfind("</div>")
        if start != -1 and end != -1:
            cards.append(html[start : end + len("</div>")])

    today = datetime.now().strftime("%Y-%m-%d")
    merged = (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        f"<title>Football Analysis — {_esc(today)}</title>"
        f"<style>{_CSS}</style></head><body>"
        f"<h1>Football Goal Analysis — {_esc(today)}</h1>"
        f"{''.join(cards)}</body></html>"
    )

    out_path = OUTPUT_DIR / "all.html"
    out_path.write_text(merged)

    for path in league_files:
        path.unlink()

    logger.info("Merged %d reports → %s", len(cards), out_path)
    return out_path


# ---------------------------------------------------------------------------
# Live update
# ---------------------------------------------------------------------------

_MINUTE_RE = re.compile(r"^(\d+)")  # extract leading digits from "45", "45+", "90+3" etc.

_XG_RE = re.compile(
    r'<span class="xg-team">.*?<strong>([\d.]+)</strong></span>'
    r'.*?<strong>([\d.]+)</strong>'
)

_LIVE_GRID_START = '<div class="live-grid">'
_LIVE_GRID_END_TAG = "<!-- /live -->"


_CARD_HEADER_RE = re.compile(
    r'<div class="match-card">.*?<h2>(.*?) vs (.*?)</h2>',
    re.DOTALL,
)


def _parse_match_cards(html: str) -> list[tuple[int, int, str, str]]:
    """Extract (start, end, home, away) for each match card in the HTML."""
    # Find all card start positions
    starts = [m.start() for m in _CARD_HEADER_RE.finditer(html)]
    if not starts:
        return []

    cards = []
    body_end = html.find("</body>")
    if body_end == -1:
        body_end = len(html)

    for i, card_start in enumerate(starts):
        # Card ends where the next card begins, or at </body>
        card_end = starts[i + 1] if i + 1 < len(starts) else body_end
        card_html = html[card_start:card_end]
        m = _CARD_HEADER_RE.match(card_html)
        if not m:
            continue
        home = html_mod.unescape(m.group(1))
        away = html_mod.unescape(m.group(2))
        cards.append((card_start, card_end, home, away))
    return cards


def _extract_xg(card_html: str) -> tuple[float, float] | None:
    """Pull home_xg and away_xg from a match card's xg-row."""
    m = _XG_RE.search(card_html)
    if not m:
        return None
    return float(m.group(1)), float(m.group(2))


def _render_live_grid(
    probs: dict, minute: int, home_goals: int, away_goals: int,
    home: str, away: str, home_xg_rem: float, away_xg_rem: float,
) -> str:
    """Render the live probability grid HTML."""
    total_xg_rem = home_xg_rem + away_xg_rem
    return (
        f'{_LIVE_GRID_START}'
        f'<div class="live-header">Live ({minute}\') — '
        f'{_esc(home)} {home_goals} - {away_goals} {_esc(away)}</div>'
        f'<div class="prob-grid">'
        f'<div class="prob {_prob_class(probs["over_1_5"])}"><span class="label">Over 1.5</span><span class="val">{probs["over_1_5"]:.0%}</span></div>'
        f'<div class="prob {_prob_class(probs["over_2_5"])}"><span class="label">Over 2.5</span><span class="val">{probs["over_2_5"]:.0%}</span></div>'
        f'<div class="prob {_prob_class(probs["under_3_5"])}"><span class="label">Under 3.5</span><span class="val">{probs["under_3_5"]:.0%}</span></div>'
        f'<div class="prob {_prob_class(probs["under_4_5"])}"><span class="label">Under 4.5</span><span class="val">{probs["under_4_5"]:.0%}</span></div>'
        f'</div>'
        f'<div class="xg-row">'
        f'<span class="xg-team">{_esc(home)} <strong>{home_xg_rem:.2f}</strong></span>'
        f'<span class="xg-total">Rem. xG {total_xg_rem:.2f}</span>'
        f'<span class="xg-team"><strong>{away_xg_rem:.2f}</strong> {_esc(away)}</span>'
        f'</div>'
        f'{_LIVE_GRID_END_TAG}'
        f'</div>'
    )


def _strip_existing_live(card_html: str) -> str:
    """Remove any previous live grid from a card."""
    start = card_html.find(_LIVE_GRID_START)
    if start == -1:
        return card_html
    end = card_html.find(_LIVE_GRID_END_TAG, start)
    if end == -1:
        return card_html
    end += len(_LIVE_GRID_END_TAG)
    # Also consume the closing </div> for the live-grid
    if card_html[end : end + 6] == "</div>":
        end += 6
    return card_html[:start] + card_html[end:]


def _match_minute(status: str) -> int | None:
    """Parse the match minute from match_status. Returns None if not live.

    APIFootball returns: "45", "45+", "90+3", "Half Time", "Finished", etc.
    """
    status = status.strip()
    if status == "Half Time":
        return 45
    m = _MINUTE_RE.match(status)
    if m:
        return int(m.group(1))
    return None


async def update_live() -> bool:
    """Fetch live data and update all.html with live probabilities."""
    all_path = OUTPUT_DIR / "all.html"
    if not all_path.exists():
        logger.info("No all.html found. Run analyze + merge first.")
        return False

    html = all_path.read_text()
    cards = _parse_match_cards(html)
    if not cards:
        logger.info("No match cards found in all.html.")
        return False

    today = datetime.now().strftime("%Y-%m-%d")
    try:
        live_matches = await fetch_matches_for_date(today)
    finally:
        await close_session()

    live_by_teams: dict[tuple[str, str], dict] = {}
    for m in live_matches:
        home = m.get("match_hometeam_name", "")
        away = m.get("match_awayteam_name", "")
        if home and away:
            live_by_teams[(home, away)] = m

    updated = 0
    # Process cards in reverse so string indices stay valid
    for card_start, card_end, home, away in reversed(cards):
        match = live_by_teams.get((home, away))
        if not match:
            continue

        minute = _match_minute(match.get("match_status", ""))
        if minute is None:
            continue

        try:
            home_goals = int(match.get("match_hometeam_score", 0))
            away_goals = int(match.get("match_awayteam_score", 0))
        except (ValueError, TypeError):
            continue

        card_html = html[card_start:card_end]
        card_html = _strip_existing_live(card_html)

        xg = _extract_xg(card_html)
        if not xg:
            continue

        home_xg, away_xg = xg
        remaining = max(90 - minute, 0) / 90
        home_xg_rem = home_xg * remaining
        away_xg_rem = away_xg * remaining

        probs = compute_live_probabilities(
            home_xg, away_xg, home_goals, away_goals, minute,
        )

        # Insert live grid before the league-avg closing </div> (end of card)
        league_avg_pos = card_html.rfind("league-avg")
        if league_avg_pos == -1:
            continue
        insert_pos = card_html.find("</div>", league_avg_pos)
        if insert_pos == -1:
            continue
        insert_pos += len("</div>")

        live_grid = _render_live_grid(
            probs, minute, home_goals, away_goals,
            home, away, home_xg_rem, away_xg_rem,
        )
        card_html = card_html[:insert_pos] + live_grid + card_html[insert_pos:]

        html = html[:card_start] + card_html + html[card_end:]
        updated += 1

    if updated:
        all_path.write_text(html)
        logger.info("Updated %d live matches in %s", updated, all_path)
    else:
        logger.info("No live matches found matching all.html.")

    return updated > 0
