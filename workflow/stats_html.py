"""HTML template rendering for the betting analytics dashboard."""

import html
import json
from typing import Optional


def _render_html(
    overview: dict,
    cumulative_pnl: list,
    rolling_win_rate: list,
    breakdowns: dict,
    skip_stats: dict,
    paper_overview: Optional[dict] = None,
    paper_cumulative_pnl: Optional[list] = None,
    paper_breakdowns: Optional[dict] = None,
) -> str:
    """Render self-contained HTML dashboard."""
    pnl_dates = json.dumps([p["date"] for p in cumulative_pnl])
    pnl_units = json.dumps([p["cumulative_units"] for p in cumulative_pnl])
    pnl_dollars = json.dumps([p["cumulative_dollars"] for p in cumulative_pnl])

    rwr_numbers = json.dumps([r["bet_number"] for r in rolling_win_rate])
    rwr_rates = json.dumps([r["rolling_win_rate"] for r in rolling_win_rate])

    def _color(val: float) -> str:
        if val > 0:
            return "color: #22c55e"
        if val < 0:
            return "color: #ef4444"
        return ""

    def _esc(val: str) -> str:
        return html.escape(str(val))

    def _breakdown_rows(rows: list) -> str:
        out = ""
        for r in rows:
            wr_pct = f"{r['win_rate'] * 100:.1f}%"
            roi_pct = f"{r['roi'] * 100:.1f}%"
            nu_style = _color(r["net_units"])
            roi_style = _color(r["roi"])
            out += (
                f"<tr><td>{_esc(r['category'])}</td><td>{r['wins']}</td><td>{r['losses']}</td>"
                f"<td>{r['pushes']}</td><td>{r['total']}</td><td>{wr_pct}</td>"
                f"<td style=\"{nu_style}\">{r['net_units']:+.2f}</td>"
                f"<td style=\"{roi_style}\">{roi_pct}</td></tr>\n"
            )
        return out

    def _skip_rows(skips: list) -> str:
        out = ""
        for s in skips:
            outcome = ""
            if s.get("outcome_resolved"):
                outcome = f"{_esc(s.get('final_score', ''))} ({_esc(s.get('winner', ''))})"
            out += (
                f"<tr><td>{_esc(s.get('date', ''))}</td><td>{_esc(s.get('matchup', ''))}</td>"
                f"<td>{_esc(s.get('reason', ''))}</td><td>{_esc(s.get('source', ''))}</td>"
                f"<td>{outcome}</td></tr>\n"
            )
        return out

    # Paper trading HTML section (conditional)
    paper_section = ""
    paper_chart_js = ""
    if paper_overview and paper_overview.get("total_trades", 0) > 0:
        p_nu_style = _color(paper_overview["net_units"])
        paper_section = f"""
<h1>Paper Trading</h1>

<div class="cards">
  <div class="card"><div class="label">Record</div><div class="value">{paper_overview['wins']}-{paper_overview['losses']}-{paper_overview['pushes']}</div></div>
  <div class="card"><div class="label">Win Rate</div><div class="value">{paper_overview['win_rate'] * 100:.1f}%</div></div>
  <div class="card"><div class="label">Net Units</div><div class="value" style="{p_nu_style}">{paper_overview['net_units']:+.2f}</div></div>
  <div class="card"><div class="label">Total Trades</div><div class="value">{paper_overview['total_trades']}</div></div>
</div>

<h2>Cumulative Units (Paper)</h2>
<div class="chart-container"><canvas id="paperPnlChart"></canvas></div>

<h2>By Confidence (Paper)</h2>
<table>
<tr><th>Level</th><th>W</th><th>L</th><th>P</th><th>Total</th><th>Win%</th><th>Net Units</th><th>ROI</th></tr>
{_breakdown_rows(paper_breakdowns['by_confidence']) if paper_breakdowns else ''}
</table>

<h2>By Bet Type (Paper)</h2>
<table>
<tr><th>Type</th><th>W</th><th>L</th><th>P</th><th>Total</th><th>Win%</th><th>Net Units</th><th>ROI</th></tr>
{_breakdown_rows(paper_breakdowns['by_bet_type']) if paper_breakdowns else ''}
</table>

<h2>By Skip Reason (Paper)</h2>
<table>
<tr><th>Reason</th><th>W</th><th>L</th><th>P</th><th>Total</th><th>Win%</th><th>Net Units</th><th>ROI</th></tr>
{_breakdown_rows(paper_breakdowns['by_skip_reason']) if paper_breakdowns else ''}
</table>
"""
        if paper_cumulative_pnl:
            p_dates = json.dumps([p["date"] for p in paper_cumulative_pnl])
            p_units = json.dumps([p["cumulative_units"] for p in paper_cumulative_pnl])
            paper_chart_js = f"""
new Chart(document.getElementById('paperPnlChart'), {{
  type: 'line',
  data: {{
    labels: {p_dates},
    datasets: [
      {{ label: 'Units', data: {p_units}, borderColor: '#a855f7', backgroundColor: 'rgba(168,85,247,0.1)', fill: true, tension: 0.3 }}
    ]
  }},
  options: {{
    responsive: true,
    scales: {{
      x: {{ ticks: {{ color: '#94a3b8' }}, grid: {{ color: '#1e293b' }} }},
      y: {{ title: {{ display: true, text: 'Units', color: '#94a3b8' }}, ticks: {{ color: '#94a3b8' }}, grid: {{ color: '#334155' }} }}
    }},
    plugins: {{ legend: {{ labels: {{ color: '#e2e8f0' }} }} }}
  }}
}});
"""

    nu_style = _color(overview["net_units"])
    nd_style = _color(overview["net_dollars"])
    roi_style = _color(overview["roi"])

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>NBA Betting Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0f172a; color: #e2e8f0; padding: 24px; }}
  h1 {{ text-align: center; margin-bottom: 24px; font-size: 1.8rem; }}
  h2 {{ margin: 32px 0 16px; font-size: 1.3rem; border-bottom: 1px solid #334155; padding-bottom: 8px; }}
  .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; margin-bottom: 24px; }}
  .card {{ background: #1e293b; border-radius: 8px; padding: 16px; text-align: center; }}
  .card .label {{ font-size: 0.75rem; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.05em; }}
  .card .value {{ font-size: 1.5rem; font-weight: 700; margin-top: 4px; }}
  .chart-container {{ background: #1e293b; border-radius: 8px; padding: 16px; margin-bottom: 24px; }}
  table {{ width: 100%; border-collapse: collapse; background: #1e293b; border-radius: 8px; overflow: hidden; margin-bottom: 24px; }}
  th {{ background: #334155; padding: 10px 12px; text-align: left; font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.05em; }}
  td {{ padding: 8px 12px; border-top: 1px solid #334155; font-size: 0.9rem; }}
  tr:hover {{ background: #253347; }}
</style>
</head>
<body>
<h1>NBA Betting Dashboard</h1>

<div class="cards">
  <div class="card"><div class="label">Record</div><div class="value">{overview['wins']}-{overview['losses']}-{overview['pushes']}</div></div>
  <div class="card"><div class="label">Win Rate</div><div class="value">{overview['win_rate'] * 100:.1f}%</div></div>
  <div class="card"><div class="label">Net Units</div><div class="value" style="{nu_style}">{overview['net_units']:+.2f}</div></div>
  <div class="card"><div class="label">Net $</div><div class="value" style="{nd_style}">${overview['net_dollars']:+.2f}</div></div>
  <div class="card"><div class="label">ROI</div><div class="value" style="{roi_style}">{overview['roi'] * 100:.1f}%</div></div>
  <div class="card"><div class="label">Streak</div><div class="value">{overview['streak']}</div></div>
  <div class="card"><div class="label">Avg Units</div><div class="value">{overview['avg_units']}</div></div>
  <div class="card"><div class="label">Total Bets</div><div class="value">{overview['total_bets']}</div></div>
</div>

<h2>Cumulative P&amp;L</h2>
<div class="chart-container"><canvas id="pnlChart"></canvas></div>

<h2>Rolling Win Rate (10-bet window)</h2>
<div class="chart-container"><canvas id="wrChart"></canvas></div>

<h2>By Confidence</h2>
<table>
<tr><th>Level</th><th>W</th><th>L</th><th>P</th><th>Total</th><th>Win%</th><th>Net Units</th><th>ROI</th></tr>
{_breakdown_rows(breakdowns['by_confidence'])}
</table>

<h2>By Edge Type</h2>
<table>
<tr><th>Edge</th><th>W</th><th>L</th><th>P</th><th>Total</th><th>Win%</th><th>Net Units</th><th>ROI</th></tr>
{_breakdown_rows(breakdowns['by_edge_type'])}
</table>

<h2>By Bet Type</h2>
<table>
<tr><th>Type</th><th>W</th><th>L</th><th>P</th><th>Total</th><th>Win%</th><th>Net Units</th><th>ROI</th></tr>
{_breakdown_rows(breakdowns['by_bet_type'])}
</table>

<h2>By Pick Side</h2>
<table>
<tr><th>Side</th><th>W</th><th>L</th><th>P</th><th>Total</th><th>Win%</th><th>Net Units</th><th>ROI</th></tr>
{_breakdown_rows(breakdowns['by_pick_side'])}
</table>

<h2>Skipped Games ({skip_stats['total_skipped']} total, {skip_stats['resolved']} resolved)</h2>
<table>
<tr><th>Date</th><th>Matchup</th><th>Reason</th><th>Source</th><th>Outcome</th></tr>
{_skip_rows(skip_stats['skips'])}
</table>

{paper_section}

<script>
new Chart(document.getElementById('pnlChart'), {{
  type: 'line',
  data: {{
    labels: {pnl_dates},
    datasets: [
      {{ label: 'Units', data: {pnl_units}, borderColor: '#3b82f6', backgroundColor: 'rgba(59,130,246,0.1)', fill: true, tension: 0.3, yAxisID: 'y' }},
      {{ label: 'Dollars', data: {pnl_dollars}, borderColor: '#22c55e', backgroundColor: 'rgba(34,197,94,0.1)', fill: true, tension: 0.3, yAxisID: 'y1' }}
    ]
  }},
  options: {{
    responsive: true,
    interaction: {{ mode: 'index', intersect: false }},
    scales: {{
      x: {{ ticks: {{ color: '#94a3b8' }}, grid: {{ color: '#1e293b' }} }},
      y: {{ position: 'left', title: {{ display: true, text: 'Units', color: '#94a3b8' }}, ticks: {{ color: '#94a3b8' }}, grid: {{ color: '#334155' }} }},
      y1: {{ position: 'right', title: {{ display: true, text: 'Dollars', color: '#94a3b8' }}, ticks: {{ color: '#94a3b8' }}, grid: {{ drawOnChartArea: false }} }}
    }},
    plugins: {{ legend: {{ labels: {{ color: '#e2e8f0' }} }} }}
  }}
}});

new Chart(document.getElementById('wrChart'), {{
  type: 'line',
  data: {{
    labels: {rwr_numbers},
    datasets: [
      {{ label: 'Win Rate', data: {rwr_rates}, borderColor: '#f59e0b', backgroundColor: 'rgba(245,158,11,0.1)', fill: true, tension: 0.3 }}
    ]
  }},
  options: {{
    responsive: true,
    scales: {{
      x: {{ title: {{ display: true, text: 'Bet #', color: '#94a3b8' }}, ticks: {{ color: '#94a3b8' }}, grid: {{ color: '#1e293b' }} }},
      y: {{ min: 0, max: 1, title: {{ display: true, text: 'Win Rate', color: '#94a3b8' }}, ticks: {{ color: '#94a3b8', callback: function(v) {{ return (v * 100) + '%'; }} }}, grid: {{ color: '#334155' }} }}
    }},
    plugins: {{ legend: {{ labels: {{ color: '#e2e8f0' }} }} }}
  }}
}});

{paper_chart_js}
</script>
</body>
</html>"""
