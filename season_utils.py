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
from datetime import date
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

# Sport -> live props file. A sport is "active" (in-season) when its props file
# exists and has at least one data row. Reactivates automatically when props
# return for that sport.
_PROP_FILES = {
    "NBA": "NBA_Props.csv",
    "WNBA": "WNBA_Props.csv",
    "MLB": "MLB_Props.csv",
    "NFL": "NFL_Props.csv",
    "NCAAF": "NCAAF_Props.csv",
}


def active_sports() -> set:
    """Return the set of sports that currently have live props loaded."""
    active = set()
    for sport, fname in _PROP_FILES.items():
        path = BASE_DIR / "data" / "props" / fname
        try:
            if not path.exists() or path.stat().st_size == 0:
                continue
            with path.open("r", encoding="utf-8", errors="replace", newline="") as fh:
                reader = csv.reader(fh)
                header = next(reader, None)
                if header is None:
                    continue
                if next(reader, None) is not None:  # at least one data row
                    active.add(sport)
        except Exception:
            # Be conservative: if we can't read it, don't claim it's active.
            pass
    return active


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
