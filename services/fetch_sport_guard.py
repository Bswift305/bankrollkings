"""
Bankroll Kings - fail-closed sport guard for the Odds API fetchers (truthfulness safeguard A).
==============================================================================================

Defect this closes (NCAAB discovery audit, 2026-11): `fetch_game_lines.py --sport basketball_ncaab`
resolved its output paths with `SPORT_OUTPUTS.get(sport, SPORT_OUTPUTS[DEFAULT_SPORT])`, i.e. an
unconfigured sport silently fell back to the NBA files, and the path/sport token guard returned nothing
for "ncaab" so it was skipped. Only a row-collapse check stood between an NCAAB fetch and overwriting
data/odds/NBA_Odds.csv (+ its schedule mirrors and the NBA line-movement history). fetch_player_props.py
had the identical fallback onto data/props/NBA_Props.csv.

Rule: every sport a fetcher may write for is declared EXPLICITLY in that fetcher's one path table. A
sport that is not in the table -- including sports that are deliberately UNCONFIGURED because no
pipeline exists yet -- fails closed BEFORE any provider request and BEFORE any filesystem write, with a
typed outcome from the shared vocabulary (services.run_outcomes) and a distinct non-zero exit.

Pure: stdlib only, no pandas, no app import.
"""
from __future__ import annotations

from services.run_outcomes import (EXIT_UNCONFIGURED_SPORT, UNCONFIGURED_SPORT_REASON,  # noqa: F401
                                   VALIDATION_FAILED)

# Typed outcome for an unconfigured sport. VALIDATION_FAILED is ALERTING in services.run_outcomes, so a
# parent step can never read this as a benign skip; the reason code says why. The exit code (2) is
# deliberately NOT 1: refresh_line_movement_snapshots treats exit 1 from fetch_game_lines as the benign
# "no new rows, existing CSV preserved". Constants live in services.run_outcomes (shared vocabulary).
UNCONFIGURED_SPORT_OUTCOME = VALIDATION_FAILED

# Sports the provider offers that we deliberately do NOT fetch yet (no pipeline, no output paths). Listed
# so the refusal message is specific; ANY key absent from a fetcher's path table fails closed regardless.
EXPLICITLY_UNCONFIGURED_SPORTS = {
    "basketball_ncaab": "no NCAAB pipeline yet (no output, receipt, coverage or cache paths declared)",
    "basketball_wncaab": "no WNCAAB pipeline yet (no output, receipt, coverage or cache paths declared)",
}


class UnconfiguredSportError(ValueError):
    """Raised when a fetcher is asked for a sport its path table does not declare."""

    outcome = UNCONFIGURED_SPORT_OUTCOME
    reason_code = UNCONFIGURED_SPORT_REASON
    exit_code = EXIT_UNCONFIGURED_SPORT

    def __init__(self, fetcher: str, sport: str, configured):
        self.fetcher = fetcher
        self.sport = sport
        self.configured = tuple(sorted(configured))
        why = EXPLICITLY_UNCONFIGURED_SPORTS.get(sport, "not declared in the fetcher's sport path table")
        super().__init__(
            f"{fetcher}: sport {sport!r} is UNCONFIGURED ({why}). Refusing before any provider request "
            f"or file write. Configured sports: {', '.join(self.configured)}")


def require_configured_sport(fetcher: str, sport, table: dict) -> str:
    """Normalize `sport` and return it if `table` declares it; else raise UnconfiguredSportError.
    No default, no fallback: an empty/None sport is unconfigured too."""
    key = str(sport or "").strip().lower()
    if not key or key in EXPLICITLY_UNCONFIGURED_SPORTS or key not in table:
        raise UnconfiguredSportError(fetcher, key, table.keys())
    return key


def report_unconfigured(exc: UnconfiguredSportError) -> int:
    """Print the typed refusal and return the exit code. Writes nothing."""
    print(f"ERROR: {exc}")
    print(f"OUTCOME: {exc.outcome} reason_code={exc.reason_code} sport={exc.sport or '(empty)'} "
          f"fetcher={exc.fetcher} network_requests=0 files_written=0")
    return exc.exit_code
