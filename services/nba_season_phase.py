"""NBA season-phase contract (pure, import-light: no `app` import, no I/O, no network).

One governed answer to "what phase is the NBA in on date D?":

    PRESEASON | REGULAR | POSTSEASON | OFFSEASON | UNKNOWN   (+ a machine-readable reason)

The answer comes ONLY from the configured official dates in ``NBA_SEASON_CONFIG``. Nothing is
inferred from props, feed availability, playoff results or the calendar shape of past seasons.
A date whose season (or whose relevant boundary) is not configured resolves to ``UNKNOWN`` --
it is never guessed as REGULAR. Callers must handle UNKNOWN explicitly.

Season membership ("ending year"): a date belongs to the season ENDING in ``d.year + 1`` when
``d.month >= 10`` (October rollover), else to the season ending in ``d.year``. This mirrors the
historical ``app.get_current_nba_season()`` rule, but is applied to an EASTERN date
(``eastern_today()``), never ``datetime.now()`` on the process's ambient zone.

Phase rules for a date ``d`` in ending year ``Y`` (all boundaries inclusive where stated):

    season Y not configured                      -> UNKNOWN  season_not_configured
    postseason_start missing                     -> UNKNOWN  postseason_start_not_configured
    d >= postseason_start, postseason_end missing-> UNKNOWN  postseason_end_not_configured
    postseason_start <= d <= postseason_end      -> POSTSEASON
    d > postseason_end (through Sep 30)          -> OFFSEASON
    d < postseason_start, regular_start missing  -> UNKNOWN  regular_start_not_configured
                                                    (but in_postseason=False: d precedes the
                                                    configured official postseason start)
    regular_start <= d < postseason_start        -> REGULAR
    Oct 1 (rollover) <= d < regular_start        -> PRESEASON

``SeasonPhase.in_postseason`` is the narrower tri-state answer to "is d inside the postseason
window?": True / False when the configuration decides it, None when it cannot be decided.

ANNUAL CHORE (checked by ``qc_nba_season_phase_contract.py``, which FAILS with a dated message
when today or any date in its look-ahead resolves UNKNOWN): before each season, add the next
ending year with the official opening-night date (``regular_start``), the official Play-In start
(``postseason_start``) and the official latest-possible Finals date (``postseason_end``), from the
published NBA schedule (nba.com key dates). Enter only published official dates; leave a field
``None`` until it is published -- the contract reports that as UNKNOWN rather than guessing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Mapping, Optional

from services.timeutils import DISPLAY_TZ

PRESEASON = "PRESEASON"
REGULAR = "REGULAR"
POSTSEASON = "POSTSEASON"
OFFSEASON = "OFFSEASON"
UNKNOWN = "UNKNOWN"
PHASES = (PRESEASON, REGULAR, POSTSEASON, OFFSEASON, UNKNOWN)

SEASON_ROLLOVER_MONTH = 10  # October: a date on/after Oct 1 belongs to the next ending year
DEFAULT_LOOKAHEAD_DAYS = 60

# Official dates per season ENDING YEAR. Field meanings:
#   regular_start    -- official regular-season opening night
#   postseason_start -- official SoFi NBA Play-In Tournament start (the product surfaces the
#                       20-team play-in field, so the postseason window starts at the play-in)
#   postseason_end   -- official latest-possible NBA Finals date
# Values for 2027 are mirrored EXACTLY from the former app.NBA_POSTSEASON_DATES; the two fields
# that were never configured there stay None (unpublished/unverified -- do not guess them).
NBA_SEASON_CONFIG = {
    2027: {
        "regular_start": None,               # official 2026-27 opening night -- NOT YET ENTERED
        "postseason_start": date(2027, 4, 13),  # SoFi NBA Play-In Tournament start, Apr 13 2027 (official)
        "postseason_end": None,              # official latest-possible NBA Finals date -- NOT YET PUBLISHED
    },
}


def _legacy_view(config: Mapping) -> dict:
    return {
        year: {"start": entry.get("postseason_start"), "end": entry.get("postseason_end")}
        for year, entry in config.items()
    }


# Back-compat view in the historical {year: {'start', 'end'}} shape; app.NBA_POSTSEASON_DATES is
# this object. Edit NBA_SEASON_CONFIG (the source of record), never this view.
NBA_POSTSEASON_DATES = _legacy_view(NBA_SEASON_CONFIG)


@dataclass(frozen=True)
class SeasonPhase:
    phase: str
    reason: str
    as_of: date
    ending_year: int
    in_postseason: Optional[bool]
    missing: tuple = field(default_factory=tuple)

    @property
    def known(self) -> bool:
        return self.phase != UNKNOWN

    def describe(self) -> str:
        return f"{self.as_of.isoformat()} NBA {self.ending_year - 1}-{str(self.ending_year)[2:]}: {self.phase} ({self.reason})"


def eastern_today() -> date:
    """Today's US-Eastern calendar date (the league clock). Raises if tzdata is unavailable --
    the contract does not silently fall back to the process's ambient zone."""
    if DISPLAY_TZ is None:
        raise RuntimeError("America/New_York tz unavailable; cannot anchor NBA phase to Eastern")
    return datetime.now(DISPLAY_TZ).date()


def season_ending_year(d: date) -> int:
    return d.year + 1 if d.month >= SEASON_ROLLOVER_MONTH else d.year


def _fields(entry: Mapping):
    """Accept the contract shape and the legacy {'start','end'} shape."""
    regular_start = entry.get("regular_start")
    ps = entry.get("postseason_start", entry.get("start"))
    pe = entry.get("postseason_end", entry.get("end"))
    return regular_start, ps, pe


def resolve_nba_season_phase(d: date, config: Optional[Mapping] = None) -> SeasonPhase:
    """Pure: phase of Eastern calendar date ``d`` under ``config`` (default NBA_SEASON_CONFIG)."""
    if isinstance(d, datetime):
        d = d.date()
    config = NBA_SEASON_CONFIG if config is None else config
    year = season_ending_year(d)

    def out(phase, reason, in_post, missing=()):
        return SeasonPhase(phase, reason, d, year, in_post, tuple(missing))

    entry = config.get(year)
    if not entry:
        return out(UNKNOWN, "season_not_configured", None, ("season",))
    regular_start, ps, pe = _fields(entry)
    if ps is None:
        return out(UNKNOWN, "postseason_start_not_configured", None, ("postseason_start",))
    if d >= ps:
        if pe is None:
            return out(UNKNOWN, "postseason_end_not_configured", None, ("postseason_end",))
        if pe < ps:
            return out(UNKNOWN, "config_invalid_postseason_end_before_start", None, ("postseason_end",))
        if d <= pe:
            return out(POSTSEASON, "inside_configured_postseason_window", True)
        return out(OFFSEASON, "after_configured_postseason_end", False)
    # d precedes the configured official postseason start: definitively not postseason.
    if regular_start is None:
        return out(UNKNOWN, "regular_start_not_configured", False, ("regular_start",))
    if regular_start >= ps:
        return out(UNKNOWN, "config_invalid_regular_start_not_before_postseason", False, ("regular_start",))
    if d >= regular_start:
        return out(REGULAR, "between_configured_regular_start_and_postseason_start", False)
    return out(PRESEASON, "before_configured_regular_start", False)


def default_postseason_flag(result: SeasonPhase) -> bool:
    """FAIL-CLOSED boolean for the legacy postseason-or-not default.

    POSTSEASON -> True; PRESEASON/REGULAR/OFFSEASON -> False. UNKNOWN -> its ``in_postseason`` when
    the configuration still decides the postseason question (a date before the configured official
    postseason start is False), otherwise True: postseason-strict, so playoff-data checks FIRE
    rather than vanish while the calendar is unconfigured."""
    if result.in_postseason is None:
        return True
    return bool(result.in_postseason)


# --- legacy-compatible helpers (app.py delegates its historical names to these) -----------------

def in_configured_postseason_window(today: date, ending_year: int, config: Optional[Mapping] = None) -> bool:
    """Identical semantics to the historical app._resolve_nba_postseason: True iff ``today`` is
    inside the COMPLETE inclusive [start, end] window for ``ending_year``. This is window
    membership only, NOT a phase -- an incomplete window returns False here; use
    resolve_nba_season_phase() to learn whether the phase is actually known."""
    config = NBA_POSTSEASON_DATES if config is None else config
    entry = config.get(ending_year)
    if not entry:
        return False
    _, start, end = _fields(entry)
    if start is None or end is None:
        return False
    return start <= today <= end


def postseason_window_complete(ending_year: int, config: Optional[Mapping] = None) -> bool:
    config = NBA_POSTSEASON_DATES if config is None else config
    entry = config.get(ending_year)
    if not entry:
        return False
    _, start, end = _fields(entry)
    return start is not None and end is not None


def season_config_complete(ending_year: int, config: Optional[Mapping] = None) -> bool:
    config = NBA_SEASON_CONFIG if config is None else config
    entry = config.get(ending_year)
    return bool(entry) and all(v is not None for v in _fields(entry))


def unknown_dates(start: date, days: int, config: Optional[Mapping] = None) -> list:
    """Every date in [start, start+days] whose phase resolves UNKNOWN (as SeasonPhase objects)."""
    return [
        r for r in (resolve_nba_season_phase(start + timedelta(days=i), config) for i in range(days + 1))
        if r.phase == UNKNOWN
    ]


def validate_config(config: Optional[Mapping] = None) -> list:
    """Structural problems in the configured table (wrong types, out-of-order or out-of-season
    dates). Missing (None) fields are NOT problems here -- they surface as UNKNOWN phases."""
    config = NBA_SEASON_CONFIG if config is None else config
    problems = []
    for year, entry in config.items():
        if not isinstance(year, int):
            problems.append(f"{year!r}: ending year must be int")
            continue
        regular_start, ps, pe = _fields(entry)
        type_errors = [
            f"{year} {name}: must be a datetime.date, got {type(value).__name__}"
            for name, value in (("regular_start", regular_start), ("postseason_start", ps), ("postseason_end", pe))
            if value is not None and (not isinstance(value, date) or isinstance(value, datetime))
        ]
        if type_errors:
            problems.extend(type_errors)
            continue
        lo, hi = date(year - 1, SEASON_ROLLOVER_MONTH, 1), date(year, SEASON_ROLLOVER_MONTH, 1) - timedelta(days=1)
        for name, value in (("regular_start", regular_start), ("postseason_start", ps), ("postseason_end", pe)):
            if value is not None and not (lo <= value <= hi):
                problems.append(f"{year} {name} {value} outside season span {lo}..{hi}")
        if regular_start is not None and ps is not None and regular_start >= ps:
            problems.append(f"{year} regular_start {regular_start} must precede postseason_start {ps}")
        if ps is not None and pe is not None and pe < ps:
            problems.append(f"{year} postseason_end {pe} precedes postseason_start {ps}")
    return problems


def config_warning(as_of: date, lookahead_days: int = DEFAULT_LOOKAHEAD_DAYS, config: Optional[Mapping] = None) -> str:
    """Owner-facing note ('' when nothing is missing): the current season's incomplete fields, and
    the first date within the look-ahead whose phase is UNKNOWN (with what it is defaulting to)."""
    config = NBA_SEASON_CONFIG if config is None else config
    year = season_ending_year(as_of)
    notes = []
    entry = config.get(year)
    if not entry:
        notes.append(f"NBA season ending {year} is not configured in NBA_SEASON_CONFIG")
    else:
        names = ("regular_start", "postseason_start", "postseason_end")
        missing = [n for n, v in zip(names, _fields(entry)) if v is None]
        if missing:
            notes.append(f"NBA season ending {year} is incomplete (missing official {', '.join(missing)})")
    gaps = unknown_dates(as_of, lookahead_days, config)
    firsts = {}
    for g in gaps:
        firsts.setdefault(g.reason, g)
    for reason, first in firsts.items():
        notes.append(
            f"phase is UNKNOWN from {first.as_of.isoformat()} ({reason}); the postseason default "
            f"fails closed to {'postseason' if default_postseason_flag(first) else 'not-postseason'} there"
        )
    if not notes:
        return ""
    return ("; ".join(notes) + ". Enter the official dates in services/nba_season_phase.py "
            "NBA_SEASON_CONFIG (see qc_nba_season_phase_contract.py).")
