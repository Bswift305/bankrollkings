"""NBA season-phase contract (pure, import-light: no `app` import, no I/O, no network).

One governed answer to "what phase is the NBA in on date D?":

    PRESEASON | REGULAR | PRE_POSTSEASON_BREAK | POSTSEASON | OFFSEASON | UNKNOWN
    (+ a machine-readable reason)

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
    postseason_start <= d <= postseason_end      -> POSTSEASON
    d > postseason_end (through Sep 30)          -> OFFSEASON
    d >= postseason_start, postseason_end missing:
        d <= last PUBLISHED postseason date      -> POSTSEASON   (published = playoffs_start when
                                                                  configured, else postseason_start)
        d after it                               -> UNKNOWN  postseason_end_not_configured
    d < postseason_start, regular_start missing  -> UNKNOWN  regular_start_not_configured
                                                    (but in_postseason=False: d precedes the
                                                    configured official postseason start)
    Oct 1 (rollover) <= d < regular_start        -> PRESEASON
    regular_start <= d <= regular_end            -> REGULAR
    regular_end < d < postseason_start           -> PRE_POSTSEASON_BREAK  (in_postseason=False)
    regular_start <= d < postseason_start, regular_end missing
                                                 -> REGULAR  (pre-regular_end semantics, back-compat)

Why the gap is its own phase: after the official regular-season end the date is NOT regular season
(no regular-season games remain), NOT postseason (the Play-In has not begun) and NOT OFFSEASON (the
season is live). It is a known, configured state, so it is not UNKNOWN either. ``in_postseason`` is
False there, so the fail-closed postseason default stays False -- the same value that date had
before ``regular_end`` existed.

Why the postseason boundary is the Play-In start, not ``playoffs_start``: the product surfaces the
20-team Play-In field, and the pre-existing semantics (app.NBA_POSTSEASON_DATES 'start') already
used the Play-In start. ``playoffs_start`` (first-round start) is recorded for provenance and
extends the PUBLISHED postseason span while the Finals end is unpublished; it is not a phase
boundary. Dates after the last published postseason date stay UNKNOWN: no Finals date is inferred.

``SeasonPhase.in_postseason`` is the narrower tri-state answer to "is d inside the postseason
window?": True / False when the configuration decides it, None when it cannot be decided.

ANNUAL CHORE (checked by ``qc_nba_season_phase_contract.py``): before each season, add the next
ending year with the official opening night (``regular_start``), regular-season end
(``regular_end``), Play-In start (``postseason_start``), playoffs start (``playoffs_start``) and
latest-possible Finals date (``postseason_end``), plus a ``provenance`` block (source URLs, quoted
source lines, retrieval date, and ``unpublished`` naming every boundary left None). Enter only
published official dates; leave a field ``None`` until it is published -- the contract reports
that as UNKNOWN rather than guessing. The QC fails when today is UNKNOWN, and fails its look-ahead
check from ``lookahead_fire_date()`` (= first UNKNOWN date minus the look-ahead days) onward, so a
missing boundary is visible before it reaches production.

DESIGN NOTE (not implemented) -- deriving ``postseason_end`` from evidence later. The NBA publishes
the Finals schedule (Games 1-7, so the latest-possible date) separately from the regular-season
release. A licensed schedule feed could supply it only under these rules: (1) the value is the date
of the LAST SCHEDULED Finals game (Game 7 "if necessary"), never the last game actually played and
never an estimate from round lengths or prior seasons; (2) it is accepted only from a schedule
record the source itself identifies as the NBA Finals, with source + retrieval time stored in
``provenance`` exactly like a hand-entered value; (3) it enters this table through an
operator-reviewed change (or a governed artifact the resolver reads), never inferred at request
time from props, feed availability or playoff results; (4) absent such a record the field stays
None and the phase stays UNKNOWN.
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
# Regular season over (after the configured official regular_end), postseason not yet begun.
PRE_POSTSEASON_BREAK = "PRE_POSTSEASON_BREAK"
PHASES = (PRESEASON, REGULAR, PRE_POSTSEASON_BREAK, POSTSEASON, OFFSEASON, UNKNOWN)

# Every date boundary a season entry may carry, in required chronological order.
BOUNDARY_FIELDS = ("regular_start", "regular_end", "postseason_start", "playoffs_start", "postseason_end")
DEFAULT_UNKNOWN_HORIZON_DAYS = 731  # how far first_unknown_date() scans (two seasons)

SEASON_ROLLOVER_MONTH = 10  # October: a date on/after Oct 1 belongs to the next ending year
DEFAULT_LOOKAHEAD_DAYS = 60

# Official dates per season ENDING YEAR. Field meanings:
#   regular_start    -- official regular-season opening night
#   regular_end      -- official last day of the regular season (optional; see module docstring)
#   postseason_start -- official SoFi NBA Play-In Tournament start (the product surfaces the
#                       20-team play-in field, so the postseason window starts at the play-in)
#   playoffs_start   -- official NBA Playoffs (first round) start (optional; provenance, and it
#                       extends the published postseason span while postseason_end is unpublished)
#   postseason_end   -- official latest-possible NBA Finals date
#   provenance       -- retrieval date + sources (url, verbatim quoted lines, retrieved date, the
#                       fields each supports, notes) + `unpublished` = every boundary left None.
# Enter only dates quoted from an official source; never infer a Finals date.
NBA_SEASON_CONFIG = {
    2027: {  # 2026-27 season
        "regular_start": date(2026, 10, 20),    # "American Express NBA Tip-Off 2026 will begin on Tuesday, Oct. 20."
        "regular_end": date(2027, 4, 11),       # "The NBA's 81st regular season will conclude on Sunday, April 11, 2027."
        "postseason_start": date(2027, 4, 13),  # "April 13-16: SoFi NBA Play-In Tournament"
        "playoffs_start": date(2027, 4, 17),    # "April 17: NBA Playoffs 2026 begin" (sic -- see provenance notes)
        "postseason_end": None,                 # latest-possible NBA Finals date: NOT PUBLISHED -- do not guess
        "provenance": {
            "retrieved": date(2026, 11, 1),
            "sources": (
                {
                    "url": "https://pr.nba.com/2026-27-nba-regular-season-schedule",
                    "retrieved": date(2026, 11, 1),
                    "quotes": (
                        "American Express NBA Tip-Off 2026 will begin on Tuesday, Oct. 20.",
                        "The NBA's 81st regular season will conclude on Sunday, April 11, 2027.",
                    ),
                    "supports": ("regular_start", "regular_end"),
                    "notes": "Play-In, playoffs and Finals dates are NOT stated on this page.",
                },
                {
                    "url": "https://www.nba.com/news/key-dates",
                    "retrieved": date(2026, 11, 1),
                    "quotes": (
                        "Oct. 20: Start of NBA regular season",
                        "April 11: 2026-27 Regular Season ends",
                        "April 13-16: SoFi NBA Play-In Tournament",
                        "April 17: NBA Playoffs 2026 begin",
                    ),
                    "supports": ("regular_start", "regular_end", "postseason_start", "playoffs_start"),
                    "notes": ("2026-27 season key-dates page. LABELING DISCREPANCY: the playoffs line reads "
                              "'NBA Playoffs 2026' although it sits in the 2026-27 list (April 2027); recorded "
                              "as 2027-04-17. NBA Finals start and latest-possible end are NOT listed."),
                },
            ),
            "unpublished": ("postseason_end",),
        },
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


def _all_boundaries(entry: Mapping) -> dict:
    """Every boundary field (BOUNDARY_FIELDS order) -> date or None."""
    regular_start, ps, pe = _fields(entry)
    return {"regular_start": regular_start, "regular_end": entry.get("regular_end"),
            "postseason_start": ps, "playoffs_start": entry.get("playoffs_start"), "postseason_end": pe}


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
    regular_end, playoffs_start = entry.get("regular_end"), entry.get("playoffs_start")
    if ps is None:
        return out(UNKNOWN, "postseason_start_not_configured", None, ("postseason_start",))
    if d >= ps:
        if playoffs_start is not None and playoffs_start < ps:
            return out(UNKNOWN, "config_invalid_playoffs_start_before_postseason_start", None, ("playoffs_start",))
        play_in = playoffs_start is not None and d < playoffs_start
        if pe is not None:
            if pe < ps or (playoffs_start is not None and pe < playoffs_start):
                return out(UNKNOWN, "config_invalid_postseason_end_before_start", None, ("postseason_end",))
            if d <= pe:
                return out(POSTSEASON, "inside_configured_play_in" if play_in else "inside_configured_postseason_window", True)
            return out(OFFSEASON, "after_configured_postseason_end", False)
        # Finals end unpublished: only the PUBLISHED postseason dates are known to be postseason.
        published_through = playoffs_start if playoffs_start is not None else ps
        if d <= published_through:
            return out(POSTSEASON, "inside_published_play_in_end_unpublished" if play_in
                       else "on_published_postseason_date_end_unpublished", True)
        return out(UNKNOWN, "postseason_end_not_configured", None, ("postseason_end",))
    # d precedes the configured official postseason start: definitively not postseason.
    if regular_start is None:
        return out(UNKNOWN, "regular_start_not_configured", False, ("regular_start",))
    if regular_start >= ps:
        return out(UNKNOWN, "config_invalid_regular_start_not_before_postseason", False, ("regular_start",))
    if regular_end is not None and not (regular_start <= regular_end < ps):
        return out(UNKNOWN, "config_invalid_regular_end_order", False, ("regular_end",))
    if d < regular_start:
        return out(PRESEASON, "before_configured_regular_start", False)
    if regular_end is None:
        return out(REGULAR, "between_configured_regular_start_and_postseason_start", False)
    if d <= regular_end:
        return out(REGULAR, "inside_configured_regular_season", False)
    return out(PRE_POSTSEASON_BREAK, "after_configured_regular_end_before_postseason_start", False)


def default_postseason_flag(result: SeasonPhase) -> bool:
    """FAIL-CLOSED boolean for the legacy postseason-or-not default.

    POSTSEASON -> True; PRESEASON/REGULAR/PRE_POSTSEASON_BREAK/OFFSEASON -> False. UNKNOWN -> its ``in_postseason`` when
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
        bounds = _all_boundaries(entry)
        type_errors = [
            f"{year} {name}: must be a datetime.date, got {type(value).__name__}"
            for name, value in bounds.items()
            if value is not None and (not isinstance(value, date) or isinstance(value, datetime))
        ]
        if type_errors:
            problems.extend(type_errors)
            continue
        lo, hi = date(year - 1, SEASON_ROLLOVER_MONTH, 1), date(year, SEASON_ROLLOVER_MONTH, 1) - timedelta(days=1)
        for name, value in bounds.items():
            if value is not None and not (lo <= value <= hi):
                problems.append(f"{year} {name} {value} outside season span {lo}..{hi}")
        regular_start, ps, pe = bounds["regular_start"], bounds["postseason_start"], bounds["postseason_end"]
        if regular_start is not None and ps is not None and regular_start >= ps:
            problems.append(f"{year} regular_start {regular_start} must precede postseason_start {ps}")
        if ps is not None and pe is not None and pe < ps:
            problems.append(f"{year} postseason_end {pe} precedes postseason_start {ps}")
        # Chronological order over every configured boundary; regular_end strictly before the Play-In.
        present = [(n, bounds[n]) for n in BOUNDARY_FIELDS if bounds[n] is not None]
        for (n1, v1), (n2, v2) in zip(present, present[1:]):
            if v2 < v1 or (v2 == v1 and n1 == "regular_end"):
                problems.append(f"{year} {n2} {v2} is out of order after {n1} {v1}")
    return problems


def validate_provenance(config: Optional[Mapping] = None) -> list:
    """Every configured season must say where its dates came from: a provenance block with a
    retrieval date and >=1 source (https url, verbatim quoted lines, retrieval date, supported
    fields); every set boundary must be supported by some source; every None boundary must be
    listed in ``unpublished`` (and nothing listed there may be set)."""
    config = NBA_SEASON_CONFIG if config is None else config
    problems = []
    for year, entry in config.items():
        prov = entry.get("provenance") if isinstance(entry, Mapping) else None
        if not isinstance(prov, Mapping):
            problems.append(f"{year}: missing provenance")
            continue
        if not isinstance(prov.get("retrieved"), date):
            problems.append(f"{year}: provenance.retrieved must be a date")
        sources = prov.get("sources") or ()
        if not sources:
            problems.append(f"{year}: provenance.sources is empty")
        supported = set()
        for i, src in enumerate(sources):
            url = str(src.get("url") or "")
            if not url.startswith("https://"):
                problems.append(f"{year}: source[{i}] url must be https, got {url!r}")
            quotes = src.get("quotes") or ()
            if not quotes or not all(isinstance(q, str) and q.strip() for q in quotes):
                problems.append(f"{year}: source[{i}] needs non-empty quoted source lines")
            if not isinstance(src.get("retrieved"), date):
                problems.append(f"{year}: source[{i}] retrieved must be a date")
            supported.update(src.get("supports") or ())
        unpublished = set(prov.get("unpublished") or ())
        for name, value in _all_boundaries(entry).items():
            if value is not None and name not in supported:
                problems.append(f"{year}: {name} is set but no source supports it")
            if value is None and name not in unpublished:
                problems.append(f"{year}: {name} is None but not listed in provenance.unpublished")
            if value is not None and name in unpublished:
                problems.append(f"{year}: {name} is set but listed as unpublished")
    return problems


def first_unknown_date(start: date, config: Optional[Mapping] = None,
                       horizon_days: int = DEFAULT_UNKNOWN_HORIZON_DAYS) -> Optional[SeasonPhase]:
    """The first date on/after ``start`` (within ``horizon_days``) whose phase is UNKNOWN, or None."""
    for i in range(horizon_days + 1):
        r = resolve_nba_season_phase(start + timedelta(days=i), config)
        if r.phase == UNKNOWN:
            return r
    return None


def lookahead_fire_date(start: date, lookahead_days: int = DEFAULT_LOOKAHEAD_DAYS,
                        config: Optional[Mapping] = None) -> Optional[date]:
    """First as-of date (on/after ``start``) whose ``unknown_dates(as_of, lookahead_days)`` is
    non-empty: ``first UNKNOWN date - lookahead_days``, clamped to ``start``. None when nothing is
    UNKNOWN within the scan horizon."""
    first = first_unknown_date(start, config)
    if first is None:
        return None
    return max(start, first.as_of - timedelta(days=lookahead_days))


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
