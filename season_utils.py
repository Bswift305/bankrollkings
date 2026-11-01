"""Shared season-awareness helpers for the daily operator chain.

The daily refresh runs every sport's steps year-round, but off-season sports
have no data, so their pipeline steps and 99% scorecards fail as a matter of
course. If those expected failures bubble up as a non-zero exit code, a real,
in-season problem can't be distinguished from off-season noise in monitoring.

These helpers let the orchestrators classify a failing step by sport and treat
off-season-sport failures (and WATCH-only "not yet READY" states) as non-fatal,
so a non-zero daily exit becomes a genuine, actionable alarm.

Intentionally dependency-free (stdlib csv only) so it is safe to import from any
batch script without pulling in pandas.
"""

from __future__ import annotations

import csv
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent


def nfl_preseason_active(today: Optional[date] = None) -> bool:
    """True only inside the NFL preseason window (~mid-July through mid-September).

    The preseason Odds-API sport key (`americanfootball_nfl_preseason`) only has events during
    this window; outside it the fetch has nothing to do. Because the regular season gate keys on
    `NFL_Props.csv` (which is populated in-season), 'NFL preseason lines' is NOT treated as an
    off-season NFL step in October -- so an out-of-window preseason fetch that errors (e.g. a
    transient Odds API 4xx) would otherwise hard-FAIL the daily operator and, because the operator
    aborts on the first FAIL, stall every downstream refresh. Gating the preseason job on this
    window makes it a clean SKIP out of season (never a FAIL), which is the correct season-gate.

    Conservative window: Jul 20 -> Sep 12 (Hall of Fame game through the final preseason week,
    before the regular season opener). Date-only; dependency-free (stdlib)."""
    d = today or date.today()
    m, day = d.month, d.day
    if m == 7:
        return day >= 20
    if m == 8:
        return True
    if m == 9:
        return day <= 12
    return False


def is_preseason_step(label: str) -> bool:
    """True for a daily-operator step that only applies during the NFL preseason window."""
    return "PRESEASON" in (label or "").upper()

# ---------------------------------------------------------------------------------------------------
# GOVERNED SEASON STATE (Nov 2026, F2v2)
# ---------------------------------------------------------------------------------------------------
# One function answers "is this sport in season?" for every orchestrator: season_state(). It returns
# ACTIVE / OFF_SEASON / UNKNOWN with a human-readable reason. Authority is SCHEDULE/CALENDAR evidence,
# never props-file presence (stale props rows never expire, which kept off-season MLB/WNBA "active" and
# made their empty-slice refreshes FAIL bk-daily every day; conversely an empty props file must never
# stop an in-season refresh -- the bootstrap trap).
#
# Two evidence sources, combined so the gate can never deadlock:
#
#   1. SEASON CALENDAR (season_calendar.SEASON_CALENDAR) -- governed, per-season, provenance-carrying
#      entries (official dates, source URLs, retrieval date, verified_through). Static and network-free,
#      so it stays current off-season with no refresh step. It only BOOTSTRAPS the gate.
#   2. ON-DISK SCHEDULE / LINES ARTIFACTS (SCHEDULE_SOURCES) -- dated events in [Eastern today,
#      today + window_days]. This evidence SUPERSEDES the calendar wherever it is positive.
#
# PRECEDENCE (first match wins):
#   P1 readable schedule evidence of an in-window event        -> ACTIVE (inside, outside, or beyond the
#                                                                 calendar's coverage -- evidence wins)
#   P2 inside the covering calendar entry's window             -> ACTIVE (bootstrap)
#   P3 date covered by NO calendar entry (expired/undeclared)   -> UNKNOWN -> FAIL-OPEN (steps run; an
#                                                                 expired calendar can never skip work)
#   P4 covered, outside window, schedule missing / undatable    -> UNKNOWN -> FAIL-OPEN
#   P5 covered, outside window, readable + determinate, 0 events -> OFF_SEASON (the ONLY skipping state)
#
# DECISION (Nov 2026 audit): evidence of NO events can NOT make a sport OFF_SEASON while it is inside its
# calendar window (e.g. a World Series that ends in 5 games). Reasons: (a) the artifacts only prove
# absence over whatever horizon the provider/fetch covered -- the Odds API lists a game only once it is
# priced, so a normal gap between postseason rounds (NFL conference title -> Super Bowl is 14 days, CFP
# semis -> title 10) reads as "no events"; (b) skipping stops the very steps that rewrite the artifacts,
# re-creating the deadlock the calendar exists to break. The cost is bounded and visible: from the real
# last game to the window end (official last-possible game + 3 days) the steps keep running.
#
# Why the calendar is required (the deadlock): the schedule artifacts for NBA/WNBA/MLB are WRITTEN BY
# the very provider steps this gate skips (fetch_game_lines writes <S>_Odds.csv + the <S>_Schedule.csv
# alias; refresh_mlb_daily's schedule step writes MLB_Schedule.csv). A zero-row fetch is rejected by the
# validator and preserves the last-season file, so off-season the artifacts are frozen with past dates.
# If file evidence alone could declare OFF_SEASON, the skipped steps would never rewrite the files and
# the sport would stay "off-season" forever -- including the day the season opens, or after any >7-day
# mid-season outage. The calendar window re-opens the gate on its own, the steps run, the files
# refresh, and from then on the file evidence takes over again at the season's tail.
#
# Calendar maintenance: see season_calendar.py. Windows open ~2 weeks before the official first game
# (generous: only the calendar can re-open a frozen schedule) and close 3 days after the official LAST
# POSSIBLE game (evidence extends a later finish). qc_season_calendar_coverage.py reports any date in
# the next 60 days not covered by a VERIFIED entry, so a missing season surfaces before it matters.

ACTIVE = "ACTIVE"
OFF_SEASON = "OFF_SEASON"
UNKNOWN = "UNKNOWN"

GOVERNED_SPORTS = ("NBA", "WNBA", "MLB", "NFL", "NCAAF")

# The calendar lives in season_calendar.py (governed entries with provenance + coverage contract).
from season_calendar import SEASON_CALENDAR, entry_for as calendar_entry  # noqa: E402

# Zero-cost "are there events?" artifacts (the same files report_feed_availability reads).
SCHEDULE_SOURCES = {
    s: (f"data/schedules/{s}_Schedule.csv", f"data/schedules/{s}_Odds.csv", f"data/odds/{s}_Odds.csv")
    for s in GOVERNED_SPORTS
}

# Event-date columns, most-specific first. A fetch timestamp (LastUpdated) is NOT an event date.
EVENT_DATE_COLUMNS = ("Date", "CommenceDate", "GameDate", "commence_time", "CommenceTime")

DEFAULT_ACTIVE_WINDOW_DAYS = 7


class SeasonState(tuple):
    """(sport, state, reason, detail) -- a plain tuple, hashable/printable with no extra imports.

    reason = one short line (safe inside a log status bracket: never contains ']');
    detail = the per-artifact schedule evidence behind it."""

    __slots__ = ()

    def __new__(cls, sport: str, state: str, reason: str, detail: str = ""):
        clean = lambda t: str(t).replace("[", "(").replace("]", ")")
        return super().__new__(cls, (sport, state, clean(reason), clean(detail)))

    sport = property(lambda self: self[0])
    state = property(lambda self: self[1])
    reason = property(lambda self: self[2])
    detail = property(lambda self: self[3])

    @property
    def off_season(self) -> bool:
        return self[1] == OFF_SEASON


def in_season_window(sport: str, today: date) -> Optional[bool]:
    """True/False against the covering calendar entry's window; None when no entry covers `today`
    (calendar expired or sport undeclared) -- the caller must treat None as UNKNOWN (fail-open)."""
    e = calendar_entry(sport, today)
    if e is None:
        return None
    return e.in_window(today)


def read_event_dates(path: Path, date_cols=EVENT_DATE_COLUMNS):
    """Parse one schedule/odds CSV into Eastern event dates (stdlib only, zero network).

    Returns (status, dates, note):
      ("missing", [], ..)  file absent
      ("dated",  [..], ..) readable and determinate. A blank / header-only file => [] -- that is what the
                           fetchers write when the provider has no events (fetch_mlb_schedule writes an
                           empty frame) -- the off-season signal.
      ("unknown", [], ..)  unreadable, data rows with no recognised date column, or no parseable dates --
                           we CANNOT say there are no events.
    Dates are Eastern calendar dates via services.timeutils.event_eastern_date (UTC-aware values are
    converted, so a 01:00 UTC game belongs to the previous Eastern date)."""
    from services.timeutils import event_eastern_date

    if not path.exists() or not path.is_file():
        return "missing", [], "no file"
    try:
        with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as fh:
            rows = list(csv.reader(fh))
    except Exception as exc:
        return "unknown", [], f"unreadable ({type(exc).__name__})"
    rows = [r for r in rows if any((c or "").strip() for c in r)]
    if len(rows) <= 1:
        return "dated", [], "no data rows"
    header = [h.strip() for h in rows[0]]
    col = next((c for c in date_cols if c in header), None)
    if col is None:
        return "unknown", [], "no date column"
    idx = header.index(col)
    dates = []
    for r in rows[1:]:
        d = event_eastern_date(r[idx]) if idx < len(r) else None
        if d is not None:
            dates.append(d)
    if not dates:
        return "unknown", [], f"date column {col!r} did not parse"
    return "dated", dates, f"{col} {min(dates)}..{max(dates)}"


# mtime-keyed memo: app.get_focus_mode_labels() reaches active_sports() from a GLOBAL context processor,
# i.e. on every request -- a schedule file is re-parsed only when its (mtime, size) changes; otherwise a
# request costs one stat() per artifact.
_EVENT_DATE_MEMO: dict = {}


def _event_dates_cached(path: Path):
    try:
        st = path.stat()
        key = (st.st_mtime_ns, st.st_size)
    except OSError:
        return read_event_dates(path)
    hit = _EVENT_DATE_MEMO.get(str(path))
    if hit and hit[0] == key:
        return hit[1]
    result = read_event_dates(path)
    _EVENT_DATE_MEMO[str(path)] = (key, result)
    return result


def events_in_window(sport: str, today: Optional[date] = None,
                     window_days: int = DEFAULT_ACTIVE_WINDOW_DAYS,
                     base_dir: Optional[Path] = None) -> tuple[Optional[bool], str]:
    """Are any of `sport`'s events scheduled in [today, today+window_days] (Eastern, inclusive)?

    Unions every schedule/lines artifact (one empty alias cannot hide games listed in another):
      True  -> at least one artifact shows an in-window event
      None  -> UNKNOWN: no artifact on disk, or one exists that we cannot date
      False -> every present artifact is readable and determinate, none has an in-window event
    """
    from services.timeutils import eastern_today

    base = Path(base_dir) if base_dir is not None else BASE_DIR
    today = today or eastern_today()
    hi = today + timedelta(days=window_days)
    unknown, determinate, notes = False, False, []
    for rel in SCHEDULE_SOURCES.get((sport or "").upper(), ()):
        status, dates, note = _event_dates_cached(base / rel)
        if status == "missing":
            continue
        n = sum(1 for d in dates if today <= d <= hi)
        notes.append(f"{rel}: {note}, {n} in-window")
        if n > 0:
            return True, "; ".join(notes)
        if status == "unknown":
            unknown = True
        else:
            determinate = True
    if unknown or not determinate:
        return None, ("; ".join(notes) or "no schedule/lines artifact on disk")
    return False, "; ".join(notes)


def season_state(sport: str, today: Optional[date] = None,
                 window_days: int = DEFAULT_ACTIVE_WINDOW_DAYS,
                 base_dir: Optional[Path] = None) -> SeasonState:
    """THE governed season state for one sport: ACTIVE / OFF_SEASON / UNKNOWN, with a reason.

    "today" is the Eastern league date (services.timeutils.eastern_today), never the server's ambient
    zone. Props presence is deliberately NOT an input. Rules (see the block comment above):
      P1 events in window (schedule evidence)            -> ACTIVE  (supersedes the calendar)
      P2 inside the covering calendar entry's window     -> ACTIVE  (bootstrap; absence can't override)
      P3 no calendar entry covers today                  -> UNKNOWN (fail-open)
      P4 outside window, schedule missing/undatable      -> UNKNOWN (fail-open)
      P5 outside window, readable schedule, zero events  -> OFF_SEASON (the only state that skips)
    """
    from services.timeutils import eastern_today

    sport = (sport or "").upper()
    today = today or eastern_today()
    has_events, detail = events_in_window(sport, today, window_days, base_dir)
    if has_events is True:
        return SeasonState(sport, ACTIVE, f"events scheduled in {window_days}d window from {today}", detail)
    entry = calendar_entry(sport, today)
    if entry is None:
        return SeasonState(sport, UNKNOWN, f"no season calendar entry covers {today} (expired or "
                                           f"undeclared) -- fail-open", detail)
    cal = f"{entry.season} calendar {entry.window_start}..{entry.window_end}" + (
        "" if entry.verified else " (UNVERIFIED entry)")
    if entry.in_window(today):
        absent = " (no listed events; calendar holds ACTIVE in-window)" if has_events is False else ""
        return SeasonState(sport, ACTIVE, f"inside {cal} on {today}{absent}", detail)
    if has_events is None:
        return SeasonState(sport, UNKNOWN, f"outside {cal} on {today} but schedule evidence "
                                           f"unavailable -- fail-open", detail)
    return SeasonState(sport, OFF_SEASON, f"outside {cal} on {today}; no events in "
                                          f"{window_days}d window", detail)


def season_states(sports=GOVERNED_SPORTS, today: Optional[date] = None,
                  window_days: int = DEFAULT_ACTIVE_WINDOW_DAYS,
                  base_dir: Optional[Path] = None) -> dict:
    """{SPORT: SeasonState} for the given sports, all judged against ONE Eastern "today"."""
    from services.timeutils import eastern_today

    today = today or eastern_today()
    return {str(s).upper(): season_state(s, today, window_days, base_dir) for s in sports}


def active_sports(today: Optional[date] = None, window_days: int = DEFAULT_ACTIVE_WINDOW_DAYS,
                  base_dir: Optional[Path] = None) -> set:
    """Governed sports that are NOT authoritatively off-season (ACTIVE, or UNKNOWN -> fail-open).

    Back-compat surface for the SKIP-vs-FAIL callers (Edge Engine pipeline, scorecard runner, prelaunch
    scorecard, run_daily's post-hoc relabel) and app.py: `sport not in active_sports()` now means
    season_state() == OFF_SEASON -- never "props file empty". Sports with no governed state (college
    hoops) are not in the set, exactly as before."""
    states = season_states(GOVERNED_SPORTS, today, window_days, base_dir)
    return {s for s, st in states.items() if not st.off_season}


def sport_for_label(label: str) -> Optional[str]:
    """Map a pipeline/scorecard step label to its sport.

    Returns None for cross-sport / core / platform steps, which must always
    pass regardless of season. Order matters so 'WNBA' is not swallowed by
    'NBA' and 'NCAAF' is not swallowed by 'NFL'.
    """
    up = (label or "").upper()
    for token, sport in (
        ("NCAAF", "NCAAF"),
        ("NCAAMB", "NCAAMB"),
        ("NCAAWB", "NCAAWB"),
        ("WNBA", "WNBA"),
        ("NBA", "NBA"),
        ("NFL", "NFL"),
        ("MLB", "MLB"),
    ):
        if token in up:
            return sport
    return None
