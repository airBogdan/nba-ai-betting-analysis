"""Results sub-package — post-game processing, history tracking, and resolution."""

from .results import run_results_workflow
from .game_results import match_bet_to_result, parse_game_results
from .history import update_history_with_bet, _categorize_edge, _categorize_skip_reason

__all__ = [
    "run_results_workflow",
    "match_bet_to_result",
    "parse_game_results",
    "update_history_with_bet",
    "_categorize_edge",
    "_categorize_skip_reason",
]
