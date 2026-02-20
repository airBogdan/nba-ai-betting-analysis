"""Analytics computation and HTML dashboard generation."""

import webbrowser
from pathlib import Path
from typing import Optional

from .io import BETS_DIR, get_history, get_paper_history, get_skips
from .stats_compute import (
    compute_all_breakdowns,
    compute_cumulative_pnl,
    compute_overview,
    compute_paper_breakdowns,
    compute_paper_overview,
    compute_rolling_win_rate,
    compute_skip_stats,
)
from .stats_html import _render_html


def generate_dashboard(output_path: Optional[str] = None) -> None:
    """Generate HTML dashboard and open in browser."""
    history = get_history()
    bets = history.get("bets", [])
    skips = get_skips()

    if not bets:
        print("No bet history found. Run some analyses first.")
        return

    overview = compute_overview(history)
    cumulative_pnl = compute_cumulative_pnl(bets)
    rolling_wr = compute_rolling_win_rate(bets)
    breakdowns = compute_all_breakdowns(bets)
    skip_stats = compute_skip_stats(skips)

    paper_history = get_paper_history()
    paper_trades = paper_history.get("trades", [])

    paper_ov = compute_paper_overview(paper_history) if paper_trades else None
    paper_pnl = compute_cumulative_pnl(paper_trades) if paper_trades else None
    paper_bkd = compute_paper_breakdowns(paper_trades) if paper_trades else None

    html = _render_html(overview, cumulative_pnl, rolling_wr, breakdowns, skip_stats,
                        paper_ov, paper_pnl, paper_bkd)

    path = Path(output_path) if output_path else BETS_DIR / "dashboard.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html)
    print(f"Dashboard written to {path}")

    try:
        webbrowser.open(f"file://{path.resolve()}")
    except Exception:
        pass
