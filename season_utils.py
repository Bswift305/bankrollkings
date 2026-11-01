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

# Sport -> live props file. Necessary (not sufficient) for "active": the props file
# must exist and have at least one data row.
_PROP_FILES = {
    "NBA": "NBA_Props.csv",
    "WNBA": "WNBA_Props.csv",
    "MLB": "MLB_Props.csv",
    "NFL": "NFL_Props.csv",
    "NCAAF": "NCAAF_Props.csv",
}

# Zero-cost "are there events?" artifacts, SHARED with report_feed_availability.py (single source of
# truth for which files say what is scheduled). Schedule = the schedule + odds-derived schedule; lines =
# the game-lines feed (also carries one row per upcoming event).
SCHEDULE_SOURCES = {s: (f"data/schedules/{s}_Schedule.csv", f"data/schedules/{s}_Odds.csv") for s in _PROP_FILES}
LINES_SOURCES = {s: (f"data/odds/{s}_Odds.csv", f"data/schedules/{s}_Odds.csv") for s in _PROP_FILES}

# Event-date columns in a schedule/odds CSV, most-specific first. (report_feed_availability appends
# 'LastUpdated' as a last resort for its report; activation does NOT -- a fetch timestamp is not an event.)
EVENT_DATE_COLUMNS = ("Date", "CommenceDate", "GameDate", "commence_time", "CommenceTime")

DEFAULT_ACTIVE_WINDOW_DAYS = 7


def _props_have_rows(path: Path) -> bool:
    try:
        if not path.exists() or path.stat().st_size == 0:
            return False
        with path.open("r", encoding="utf-8", errors="replace", newline="") as fh:
            reader = csv.reader(fh)
            if next(reader, None) is None:
                return False
            return next(reader, None) is not None  # at least one data row
    except Exception:
        # Be conservative: if we can't read it, don't claim it's active.
        return False


def read_event_dates(path: Path, date_cols=EVENT_DATE_COLUMNS):
    """Parse one schedule/odds CSV into Eastern event dates (stdlib only, zero network).

    Returns (status, dates, note):
      ("missing", [], ..)  file absent
      ("dated",  [..], ..) readable and determinate: header-only / empty file => [] (the fetchers write
                           that when the provider has no events -- the off-season signal)
      ("unknown", [], ..)  unreadable, rows with no recognised date column, or no parseable dates --
                           we CANNOT say there are no events
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
    return "dated", dates, f"from {col!r}"


# mtime-keyed memo: app.get_focus_mode_labels() calls active_sports() from a GLOBAL context processor,
# i.e. on every request -- re-parse a schedule only when the file actually changes.
_EVENT_DATE_MEMO: dict = {}


def _event_dates_cached(path: Path):
    try:
        st = path.stat()
        key = (str(path), st.st_mtime_ns, st.st_size)
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

    Unions every schedule/lines artifact (so one empty alias cannot hide games in another):
      True  -> at least one source shows an in-window event
      None  -> UNKNOWN: no source on disk, or a source exists that we cannot date -- the caller must not
               conclude "no events" from this
      False -> every present source is readable and determinate, and none has an in-window event
    """
    from services.timeutils import eastern_today

    base = Path(base_dir) if base_dir is not None else BASE_DIR
    today = today or eastern_today()
    hi = today + timedelta(days=window_days)
    rels = list(dict.fromkeys((*SCHEDULE_SOURCES.get(sport, ()), *LINES_SOURCES.get(sport, ()))))
    unknown, determinate, notes = False, False, []
    for rel in rels:
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
        return None, ("; ".join(notes) or "no schedule/lines file on disk")
    return False, "; ".join(notes)


def sport_activation(sport: str, today: Optional[date] = None,
                     window_days: int = DEFAULT_ACTIVE_WINDOW_DAYS,
                     base_dir: Optional[Path] = None) -> tuple[bool, str]:
    """(active, reason) for one sport. See active_sports()."""
    base = Path(base_dir) if base_dir is not None else BASE_DIR
    fname = _PROP_FILES.get(sport)
    if not fname or not _props_have_rows(base / "data" / "props" / fname):
        return False, "no props rows"
    has_events, detail = events_in_window(sport, today, window_days, base)
    if has_events is True:
        return True, f"props rows + events in {window_days}d window ({detail})"
    if has_events is None:
        # FAIL TOWARD THE OLD BEHAVIOUR: no usable schedule means we cannot prove the sport is out of
        # season, so props rows alone keep it active. Dropping an in-season NFL/NBA because its schedule
        # alias is missing would turn its real failures into "SKIP (off-season)" and hide them.
        return True, f"props rows; schedule UNKNOWN -> props-only fallback ({detail})"
    return False, f"stale props rows; no events in {window_days}d window ({detail})"


def active_sports(today: Optional[date] = None, window_days: int = DEFAULT_ACTIVE_WINDOW_DAYS,
                  base_dir: Optional[Path] = None) -> set:
    """Sports that are in season NOW.

    A sport is active only when BOTH hold:
      1. its props file has at least one data row, AND
      2. its schedule/lines artifacts show at least one event in [today, today+window_days], with
         "today" on the Eastern calendar (services.timeutils, never the server's ambient zone).

    Props rows alone used to be sufficient, but stale rows never expire: off-season MLB/WNBA kept
    their last props, stayed "active", and their expected empty-slice refresh failures (validator:
    0 rows < min 1 -- correct, never weakened) failed bk-daily every day.

    Missing/undatable schedule: falls back to (1) alone -- the previous behaviour -- so an in-season
    sport is never silently dropped because a schedule file is absent. See sport_activation().
    """
    return {s for s in _PROP_FILES if sport_activation(s, today, window_days, base_dir)[0]}


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
