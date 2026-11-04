"""
Governed NBA schedule authority for the game-lines NO-GAME decision (2026-11, Gap 1).
=====================================================================================

Question this module answers: "for the governed Eastern service date, does an AUTHORITATIVE schedule that
is INDEPENDENT of the odds provider say there are zero NBA games?" Only that can turn a provider's empty
answer into the benign NO_GAMES_SCHEDULED. An empty provider response alone is never proof of no games.

Decision table (docs/game_lines_event_contract.md, "Governed no-game result"):
  fresh authoritative schedule says ZERO games  -> NO_GAMES_SCHEDULED, decided BEFORE any paid call
  schedule says games expected, provider zero   -> fail closed (VALIDATION_FAILED, PROVIDER_ZERO_EVENTS_GAMES_EXPECTED)
  schedule missing / stale / ambiguous / circular -> SCHEDULE_UNAVAILABLE, fail closed (never invented)

AUDIT RESULT (read-only, 2026-11-03, file:line at f06e568): NO authoritative independent NBA schedule
source exists in this repo on production. Every candidate is circular, gated off, dev-only, or
backward-looking:

  * data/schedules/NBA_Schedule.csv -- written by fetch_game_lines.py:587-591 as the `schedule_alias`
    output of the SAME Odds API /odds response (SPORT_OUTPUTS fetch_game_lines.py:31-35), and ALSO by
    fetch_schedule.py:160. Circular for this decision.
  * data/schedules/NBA_Odds.csv, data/odds/NBA_Odds.csv -- the game-lines artifact itself (circular).
  * app.load_schedule (app.py:20934-20968) -- while BK_NBA_STATS_ENABLED is off it does not read
    NBA_Schedule.csv at all and returns the NBA_Odds-derived frame (app.py:20941-20950): circular.
  * fetch_schedule.py (nba_api ScoreboardV2, :43,:100-147) -- gated off by BK_NBA_STATS_ENABLED
    (:179-183), not wired into run_daily.py (only batch/TASK_refresh_data.bat:8 and batch/REFRESH_DATA.bat:12,
    which run on the Windows dev box, never prod), falls back to NBA_Odds.csv when NBA Stats is empty
    (:56-89, circular), computes the service date with a naive datetime.now() (:101, not Eastern), and
    writes the same NBA_Schedule.csv the odds alias overwrites (:160) -- so its provenance is not
    recoverable from the file.
  * refresh_playoff_results.py (ScoreboardV2 :111 + ESPN scoreboard :63,:176-196) -- postseason RESULTS,
    backward-looking (days_back), gated (:398-399). Not a forward schedule.
  * refresh_live_scores.py:105-123 -- reads NBA_Schedule.csv (circular, above).
  * Odds API /v4/sports/basketball_nba/events -- free, but the SAME provider as /odds. Its empty answer is
    the very thing that must not prove a no-game day.
  * sport_registry.py:74 declares schedule_loader='load_schedule' (the circular loader above).

Therefore AUTHORITATIVE_SOURCES is empty and schedule_verdict() ALWAYS returns SCHEDULE_UNAVAILABLE. This
module deliberately implements no NO_GAMES_SCHEDULED short-circuit: none can be justified today.

What source would be needed (documented, not built): a licensed, provider-independent NBA season
schedule (e.g. the league's published season schedule via a cleared data licence, or a schedule feed from
a second licensed vendor) persisted with (a) provider game ids, (b) UTC tip times, (c) a fetched_at
provenance timestamp and source name, (d) an explicit Eastern service-date field, refreshed daily on prod
through run_daily.py, with a freshness bound (e.g. <= 24h) and a QC. Only after that exists and is
reviewed may a source be added to AUTHORITATIVE_SOURCES and the pre-provider NO_GAMES_SCHEDULED branch be
written.

Pure stdlib; no app import.
"""
from __future__ import annotations

from datetime import datetime

from services.run_outcomes import SCHEDULE_UNAVAILABLE, VALIDATION_FAILED
from services.timeutils import DISPLAY_TZ, utc_now

GAMES_SCHEDULED = "GAMES_SCHEDULED"

# Sources examined by the audit above and REJECTED as authority for the no-game decision.
REJECTED_SOURCES = (
    ("data/schedules/NBA_Schedule.csv", "CIRCULAR: written by fetch_game_lines from the same /odds response"),
    ("data/schedules/NBA_Odds.csv", "CIRCULAR: the game-lines artifact itself"),
    ("data/odds/NBA_Odds.csv", "CIRCULAR: the game-lines artifact itself"),
    ("app.load_schedule", "CIRCULAR: NBA_Odds-derived while BK_NBA_STATS_ENABLED is off"),
    ("fetch_schedule.py", "GATED + DEV-ONLY + falls back to NBA_Odds (circular) + naive service date"),
    ("refresh_playoff_results.py", "BACKWARD-LOOKING postseason results, gated"),
    ("odds_api:/events", "SAME PROVIDER as /odds; not independent"),
)

# Registered authoritative, independent, fresh schedule sources. EMPTY by audit (see module docstring).
AUTHORITATIVE_SOURCES: tuple = ()


def governed_service_date(now: datetime | None = None) -> str:
    """The governed NBA service date: the US Eastern calendar date of `now` (aware; default utc_now()).
    Never the process's ambient zone (CLAUDE.md section 5: the UTC prod box rolls at 8pm ET)."""
    now = now or utc_now()
    if now.tzinfo is None:
        raise ValueError("governed_service_date needs a timezone-aware instant")
    return now.astimezone(DISPLAY_TZ).strftime("%Y-%m-%d") if DISPLAY_TZ else now.strftime("%Y-%m-%d")


def schedule_verdict(service_date: str | None = None, now: datetime | None = None) -> dict:
    """Return the governed schedule verdict for `service_date` (default: today, Eastern).

    With no registered authoritative source this is always SCHEDULE_UNAVAILABLE / NO_AUTHORITATIVE_SOURCE.
    The shape is the contract a future source must fill: status in {GAMES_SCHEDULED, NO_GAMES_SCHEDULED,
    SCHEDULE_UNAVAILABLE}, the source name, its fetched_at provenance and the service date it covers."""
    service_date = service_date or governed_service_date(now)
    return {
        "status": SCHEDULE_UNAVAILABLE,
        "reason_code": "NO_AUTHORITATIVE_SOURCE",
        "service_date": service_date,
        "source": None,
        "source_fetched_at": None,
        "expected_games": None,
        "rejected_sources": [name for name, _ in REJECTED_SOURCES],
    }


def zero_event_outcome(verdict: dict) -> tuple[str, str]:
    """Classify a provider response with ZERO events, given the pre-provider schedule verdict.
    Returns (outcome, reason_code). Never returns NO_GAMES_SCHEDULED: that is only decided before the
    provider call, from an authoritative source, and costs zero credits."""
    status = (verdict or {}).get("status")
    if status == GAMES_SCHEDULED:
        return VALIDATION_FAILED, "PROVIDER_ZERO_EVENTS_GAMES_EXPECTED"
    return SCHEDULE_UNAVAILABLE, str((verdict or {}).get("reason_code") or "NO_AUTHORITATIVE_SOURCE")
