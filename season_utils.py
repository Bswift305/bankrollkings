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
#   1. SEASON CALENDAR (SEASON_WINDOWS) -- a recurring month/day envelope per sport covering the regular
#      season AND postseason, opened ~a week before the earliest plausible first game. It is static, so
#      it stays current off-season with no refresh step and no network. Inside the envelope the sport is
#      ACTIVE regardless of what the on-disk schedule says.
#   2. ON-DISK SCHEDULE / LINES ARTIFACTS (SCHEDULE_SOURCES) -- dated events in [Eastern today,
#      today + window_days]. Any in-window event => ACTIVE (also outside the envelope, e.g. an early
#      international opener or a postseason that runs past the envelope end).
#
#   OFF_SEASON requires BOTH: today is outside the envelope AND every present schedule artifact is
#   readable and determinate with zero in-window events. Missing / unreadable / undatable artifacts =>
#   UNKNOWN => FAIL-OPEN (the caller runs the step as before).
#
# Why the calendar is required (the deadlock): the schedule artifacts for NBA/WNBA/MLB are WRITTEN BY
# the very provider steps this gate skips (fetch_game_lines writes <S>_Odds.csv + the <S>_Schedule.csv
# alias; refresh_mlb_daily's schedule step writes MLB_Schedule.csv). A zero-row fetch is rejected by the
# validator and preserves the last-season file, so off-season the artifacts are frozen with past dates.
# If file evidence alone could declare OFF_SEASON, the skipped steps would never rewrite the files and
# the sport would stay "off-season" forever -- including the day the season opens, or after any >7-day
# mid-season outage. The calendar envelope re-opens the gate on its own, the steps run, the files
# refresh, and from then on the file evidence takes over again at the season's tail.
#
# Envelope maintenance: dates are recurring (no yearly chore), deliberately generous at the START (the
# cost of opening early is a few empty provider calls; opening late would miss opening day). If a league
# moves its calendar (lockout, expansion pushing finals later), edit SEASON_WINDOWS. After the envelope
# end the sport stays ACTIVE while its (still refreshed) artifacts list upcoming games, so a late finish
# is safe unless a gap between postseason rounds exceeds the fetch horizon (documented risk).

ACTIVE = "ACTIVE"
OFF_SEASON = "OFF_SEASON"
UNKNOWN = "UNKNOWN"

GOVERNED_SPORTS = ("NBA", "WNBA", "MLB", "NFL", "NCAAF")

# Sport -> ((start_month, start_day), (end_month, end_day)), inclusive, Eastern calendar; may wrap the
# new year. Start = ~1 week before the earliest plausible first regular-season game; end = typical
# latest finish of the postseason (file evidence extends it while games are still listed).
SEASON_WINDOWS = {
    "MLB": ((3, 10), (10, 31)),    # Tokyo/Seoul openers ~Mar 18-20; World Series ends late Oct
    "WNBA": ((5, 1), (10, 20)),    # tip-off mid-May; Finals into mid-Oct
    "NBA": ((10, 15), (6, 30)),    # tip-off ~Oct 20-24; Finals mid/late June
    "NFL": ((8, 25), (2, 20)),     # regular season early Sep (preseason has its own gate); SB mid-Feb
    "NCAAF": ((8, 15), (1, 25)),   # Week 0 late Aug; CFP title mid/late Jan
}

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
    """True/False against the sport's calendar envelope; None when no envelope is declared."""
    win = SEASON_WINDOWS.get((sport or "").upper())
    if not win:
        return None
    start, end = win
    md = (today.month, today.day)
    if start <= end:
        return start <= md <= end
    return md >= start or md <= end  # wraps the new year


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
      events in window                                   -> ACTIVE
      inside the season calendar envelope                -> ACTIVE
      no calendar declared for the sport                 -> UNKNOWN (fail-open)
      outside envelope, schedule missing/undatable       -> UNKNOWN (fail-open)
      outside envelope, readable schedule, zero events   -> OFF_SEASON (the only state that skips)
    """
    from services.timeutils import eastern_today

    sport = (sport or "").upper()
    today = today or eastern_today()
    has_events, detail = events_in_window(sport, today, window_days, base_dir)
    if has_events is True:
        return SeasonState(sport, ACTIVE, f"events scheduled in {window_days}d window from {today}", detail)
    in_window = in_season_window(sport, today)
    if in_window is True:
        (sm, sd), (em, ed) = SEASON_WINDOWS[sport]
        return SeasonState(sport, ACTIVE, f"inside season calendar {sm:02d}-{sd:02d}..{em:02d}-{ed:02d} "
                                          f"on {today}", detail)
    if in_window is None:
        return SeasonState(sport, UNKNOWN, "no season calendar declared -- fail-open", detail)
    if has_events is None:
        return SeasonState(sport, UNKNOWN, f"outside season calendar on {today} but schedule evidence "
                                           f"unavailable -- fail-open", detail)
    return SeasonState(sport, OFF_SEASON, f"outside season calendar on {today}; no events in "
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
