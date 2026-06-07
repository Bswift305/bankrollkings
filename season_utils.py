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
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent

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
