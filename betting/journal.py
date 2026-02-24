"""Journal writing for post-game results and paper trades."""

from typing import List

from .io import JOURNAL_DIR, PAPER_JOURNAL_DIR, append_text
from .types import CompletedBet


def append_journal_post_game(date: str, completed: List[CompletedBet]) -> None:
    """Append post-game results to journal."""
    journal_path = JOURNAL_DIR / f"{date}.md"

    # Check if results already appended (avoid duplicates on re-run)
    existing = ""
    if journal_path.exists():
        existing = journal_path.read_text()
        if "## Post-Game Results" in existing:
            print(f"Post-game results already in journal for {date}, skipping append")
            return

    lines = []
    # Add header if journal doesn't exist
    if not existing:
        lines.extend([f"# NBA Betting Journal - {date}", "", ""])

    lines.extend(["## Post-Game Results", ""])

    wins = sum(1 for b in completed if b["result"] == "win")
    losses = sum(1 for b in completed if b["result"] == "loss")
    pushes = sum(1 for b in completed if b["result"] == "push")
    net = sum(b["profit_loss"] for b in completed)

    if pushes > 0:
        record_str = f"{wins}-{losses}-{pushes}"
    else:
        record_str = f"{wins}-{losses}"
    lines.append(f"**Record: {record_str} | Net: {net:+.1f} units**")
    lines.append("")

    for bet in completed:
        bet_type = bet.get("bet_type", "moneyline")
        pick = bet["pick"]
        line = bet.get("line")

        # Format pick display
        if bet_type == "player_prop":
            player = bet.get("player_name", "?")
            prop = bet.get("prop_type", "?")
            pick_display = f"{player} {prop} {pick} {line}" if line else f"{player} {prop} {pick}"
        elif bet_type == "spread" and line is not None:
            pick_display = f"{pick} {line:+.1f}"
        elif bet_type == "total" and line is not None:
            pick_display = f"{pick} {line:.1f}"
        else:
            pick_display = pick

        emoji = "+" if bet["result"] == "win" else ("-" if bet["result"] == "loss" else "=")
        result_str = bet["result"].upper()
        if bet["result"] == "push":
            profit_str = "push"
        else:
            profit_str = f"{emoji}{abs(bet['profit_loss']):.1f}u"

        lines.append(f"### {bet['matchup']} - {bet_type.upper()}")
        lines.append(f"- Pick: {pick_display}")
        lines.append(f"- Result: **{result_str}** ({profit_str})")
        lines.append(f"- Final: {bet['final_score']}")
        if bet_type == "player_prop":
            actual = bet.get("actual_stat")
            lines.append(f"- Actual {bet.get('prop_type', 'stat')}: {actual if actual is not None else 'DNP'}")
        elif bet_type == "total":
            lines.append(f"- Actual Total: {bet.get('actual_total', 'N/A')}")
        lines.append(f"- Winner: {bet['winner']}")
        if bet["reflection"]:
            lines.append(f"- Reflection: {bet['reflection']}")
        lines.append("")

    append_text(journal_path, "\n".join(lines))


def _append_paper_journal_results(date: str, resolved_trades: List[dict]) -> None:
    """Append results to paper journal entry."""
    journal_path = PAPER_JOURNAL_DIR / f"{date}.md"
    existing = ""
    if journal_path.exists():
        existing = journal_path.read_text()
        if "## Results" in existing:
            return  # Already appended

    lines = []
    if not existing:
        lines.extend([f"# Paper Trading Journal - {date}", "", ""])

    wins = sum(1 for t in resolved_trades if t["result"] == "win")
    losses = sum(1 for t in resolved_trades if t["result"] == "loss")
    net = sum(t.get("profit_loss", 0) for t in resolved_trades)

    lines.extend(["## Results", "", f"**Record: {wins}-{losses} | Net: {net:+.1f} units**", ""])

    for trade in resolved_trades:
        bt = trade.get("bet_type", "moneyline")
        pick = trade["pick"]
        line = trade.get("line")
        if bt == "spread" and line is not None:
            pick_display = f"{pick} {line:+.1f}"
        elif bt == "total" and line is not None:
            pick_display = f"{pick} {line:.1f}"
        else:
            pick_display = pick

        emoji = "+" if trade["result"] == "win" else "-"
        lines.append(f"### {trade['matchup']} - {bt.upper()}")
        lines.append(f"- Pick: {pick_display}")
        lines.append(f"- Result: **{trade['result'].upper()}** ({emoji}{abs(trade.get('profit_loss', 0)):.1f}u)")
        lines.append(f"- Final: {trade.get('final_score', 'N/A')}")
        lines.append(f"- Skip reason: {trade.get('skip_reason', '')}")
        lines.append("")

    append_text(journal_path, "\n".join(lines))
