"""Resolution helpers for skips and paper trades."""

from typing import List

from sports.nba.api import get_games_by_date
from ..evaluation import _evaluate_bet
from .game_results import _format_score, _teams_match, parse_game_results
from .history import update_paper_history_with_trade
from ..io import (
    get_paper_history,
    get_paper_trades,
    get_skips,
    save_paper_history,
    save_paper_trades,
    save_skips_all,
)
from ..journal import _append_paper_journal_results


async def _resolve_skips_for_date(date: str, season: int) -> None:
    """Fetch outcomes for skipped games on this date."""
    all_skips = get_skips()
    date_skips = [s for s in all_skips if s.get("date") == date and not s.get("outcome_resolved")]
    if not date_skips:
        return

    api_results = await get_games_by_date(season, date)
    all_results = parse_game_results(api_results) if api_results else []
    finished = [r for r in all_results if r["status"] == "finished"]
    if not finished:
        return

    resolved = 0
    for skip in date_skips:
        matched = None
        gid = skip.get("game_id")
        if gid:
            matched = next((r for r in finished if r["game_id"] == gid), None)
        if not matched:
            parts = skip["matchup"].split(" @ ")
            if len(parts) == 2:
                away, home = parts
                matched = next(
                    (r for r in finished if _teams_match(r["home_team"], home) and _teams_match(r["away_team"], away)),
                    None,
                )
        if matched:
            skip["winner"] = matched["winner"]
            skip["final_score"] = _format_score(matched)
            skip["actual_total"] = matched["home_score"] + matched["away_score"]
            skip["actual_margin"] = matched["home_score"] - matched["away_score"]
            skip["outcome_resolved"] = True
            resolved += 1

    if resolved:
        save_skips_all(all_skips)
        print(f"  Resolved outcomes for {resolved} skipped game(s)")


async def _resolve_paper_trades_for_date(date: str, season: int) -> None:
    """Resolve paper trade outcomes for a date."""
    all_trades = get_paper_trades()
    date_trades = [t for t in all_trades if t.get("date") == date and "result" not in t]
    if not date_trades:
        return

    api_results = await get_games_by_date(season, date)
    all_results = parse_game_results(api_results) if api_results else []
    finished = [r for r in all_results if r["status"] == "finished"]
    if not finished:
        return

    resolved = 0
    paper_history = get_paper_history()

    for trade in date_trades:
        matched = None
        gid = trade.get("game_id")
        if gid:
            matched = next((r for r in finished if r["game_id"] == str(gid)), None)
        if not matched:
            parts = trade["matchup"].split(" @ ")
            if len(parts) == 2:
                away, home = parts
                matched = next(
                    (r for r in finished if _teams_match(r["home_team"], home) and _teams_match(r["away_team"], away)),
                    None,
                )
        if matched:
            if trade.get("bet_type") == "player_prop":
                print(f"  Skipping paper trade with unsupported bet_type 'player_prop': {trade['matchup']}")
                continue
            outcome, profit_loss = _evaluate_bet(trade, matched)
            trade["result"] = outcome
            trade["profit_loss"] = profit_loss
            trade["winner"] = matched["winner"]
            trade["final_score"] = _format_score(matched)
            trade["actual_total"] = matched["home_score"] + matched["away_score"]
            trade["actual_margin"] = matched["home_score"] - matched["away_score"]
            update_paper_history_with_trade(paper_history, trade)
            resolved += 1

    if resolved:
        save_paper_trades(all_trades)
        save_paper_history(paper_history)
        _append_paper_journal_results(date, [t for t in date_trades if "result" in t])
        print(f"  Resolved {resolved} paper trade(s)")
