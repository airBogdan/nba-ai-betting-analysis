Analyze football matches for goal probabilities using the Poisson model.

Arguments: $ARGUMENTS

## Instructions

Run `python football.py analyze` with the arguments provided. If no arguments given, ask which league and date.

Available leagues: epl, la_liga, bundesliga, serie_a, ligue_1, ucl, uel

Examples:
- `/football --league uel` → today's UEL matches
- `/football --league epl --date 2026-02-27` → EPL on specific date
- `/football --league ucl` → today's Champions League matches

Steps:
1. Parse the arguments for `--league` / `-l` and `--date` / `-d`
2. If no league specified, ask the user which league
3. Run: `python football.py analyze --league {league}` (add `--date {date}` if provided)
4. Read and display the generated report from `output/football/{date}/analysis.md`
5. Highlight the key probabilities: Over 1.5, Under 3.5, Under 4.5 for each match
