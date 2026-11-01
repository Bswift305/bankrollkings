"""Governed season calendar: the BOOTSTRAP half of season_utils.season_state() (F2v2 audit, Nov 2026).

Why a calendar exists at all: the schedule/lines artifacts that tell the season gate "games are coming"
are written by the very provider steps the gate skips, so off-season they freeze with last season's
dates. Without a calendar a sport judged OFF_SEASON could never re-open itself (deadlock). The calendar
only BOOTSTRAPS the gate; readable schedule evidence of in-window events SUPERSEDES it (see
season_utils.season_state for the precedence rules).

This module replaces the old bare recurring `SEASON_WINDOWS` month/day tuples. Every entry is ONE
season of ONE sport, with dated provenance:

  window_start..window_end   the gate's ACTIVE window (inclusive, Eastern calendar dates). It is the
                             official first game minus a START margin (generous: opening late would
                             skip opening day, and only the calendar can re-open a frozen schedule)
                             through the official LAST POSSIBLE game plus a small END margin (schedule
                             evidence keeps a sport ACTIVE past the window while games are listed, so
                             the tail margin only absorbs a postponed final game).
  covers_from..window_end    the COVERAGE of the entry: the dates this entry is the calendar authority
                             for (the preceding off-season + its own window). Coverage per sport must be
                             contiguous (checked by validate_calendar). A date covered by NO entry makes
                             the calendar return None and the gate UNKNOWN => FAIL-OPEN (steps run): an
                             expired calendar can never skip in-season work.
  verified_through           the last date through which the entry's assertions are backed by the
                             cited OFFICIAL league sources (None = nothing verified). An entry is
                             `verified` when verified_through >= window_end. Unverified entries still
                             gate (they are deliberately WIDE, which fails safe) but are reported.
  official                   the official milestone dates found, as ISO strings, verbatim from sources.
  sources / retrieved        URLs and the retrieval date.

COVERAGE CONTRACT (qc_season_calendar_coverage.py): for every governed sport, every date in
[today, today + COVERAGE_LOOKAHEAD_DAYS] must be covered by a VERIFIED entry. Covered only by an
unverified entry => reported (WATCH); not covered at all => hard FAIL. So a missing/unverified future
season becomes visible COVERAGE_LOOKAHEAD_DAYS before it can affect production.

MAINTENANCE: when a league publishes a new season (MLB ~July, NFL ~May, NBA ~August, WNBA ~January,
CFP ~summer), replace that sport's trailing unverified entry with a verified one (official dates,
sources, retrieval date) and append a new unverified conservative entry for the season after.
Pure data + stdlib; no network; no app import.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

COVERAGE_LOOKAHEAD_DAYS = 60


@dataclass(frozen=True)
class SeasonEntry:
    sport: str
    season: str
    covers_from: date
    window_start: date
    window_end: date
    verified_through: Optional[date]
    official: dict = field(default_factory=dict)
    sources: tuple = ()
    retrieved: Optional[date] = None
    notes: str = ""

    @property
    def covers_through(self) -> date:
        return self.window_end

    @property
    def verified(self) -> bool:
        return self.verified_through is not None and self.verified_through >= self.window_end

    def covers(self, d: date) -> bool:
        return self.covers_from <= d <= self.window_end

    def in_window(self, d: date) -> bool:
        return self.window_start <= d <= self.window_end

    def label(self) -> str:
        v = "verified" if self.verified else (
            f"UNVERIFIED after {self.verified_through}" if self.verified_through else "UNVERIFIED")
        return (f"{self.sport} {self.season} window {self.window_start}..{self.window_end} ({v})")


R = date(2026, 11, 1)  # retrieval date of this audit

SEASON_CALENDAR: dict[str, tuple[SeasonEntry, ...]] = {
    "MLB": (
        SeasonEntry(
            "MLB", "2026", covers_from=date(2026, 1, 1),
            window_start=date(2026, 3, 11),   # Opening Night 2026-03-25 minus 14d
            window_end=date(2026, 11, 3),     # World Series G7 (if needed) 2026-10-31 plus 3d
            verified_through=date(2026, 11, 3),
            official={"opening_night": "2026-03-25", "regular_season_end": "2026-09-27",
                      "wild_card_start": "2026-09-29", "world_series": "2026-10-23..2026-10-31 (G7 if needed)"},
            sources=("https://www.mlb.com/news/press-release-mlb-announces-2026-postseason-schedule",
                     "https://www.mlb.com/news/mlb-2026-schedule-released"),
            retrieved=R,
            notes="Postseason dates fetched from the MLB press release. Opening Night / regular-season "
                  "end are from the mlb.com schedule-release article as returned by search (the page "
                  "itself answered HTTP 406 to a direct fetch); both are past dates and not forward-relevant.",
        ),
        SeasonEntry(
            "MLB", "2027", covers_from=date(2026, 11, 4),
            window_start=date(2027, 3, 10),   # Opening Night 2027-03-24 minus 14d (covers an unannounced intl opener)
            window_end=date(2027, 11, 7),     # 2027 postseason UNPUBLISHED: conservative (2026 G7 was Oct 31)
            verified_through=date(2027, 9, 26),
            official={"opening_night": "2027-03-24", "opening_day": "2027-03-25",
                      "regular_season_end": "2027-09-26", "postseason": "unpublished"},
            sources=("https://www.mlb.com/news/mlb-2027-schedule-released",),
            retrieved=R,
            notes="Regular season verified (article published 2026-07-16, no international opener "
                  "mentioned). Postseason dates not yet announced -> window end is a wide estimate.",
        ),
    ),
    "WNBA": (
        SeasonEntry(
            "WNBA", "2026", covers_from=date(2026, 1, 1),
            window_start=date(2026, 4, 24),   # tip-off 2026-05-08 minus 14d
            window_end=date(2026, 11, 3),     # Finals G7 (if needed) 2026-10-31 plus 3d
            verified_through=date(2026, 11, 3),
            official={"tip_off": "2026-05-08", "regular_season_end": "2026-09-24",
                      "playoffs_start": "2026-09-27", "finals": "2026-10-17..2026-10-31 (G5-7 if needed)"},
            sources=("https://www.wnba.com/news/2026-schedule-release",
                     "https://www.wnba.com/news/2026-wnba-postseason-faq"),
            retrieved=R,
            notes="The pre-audit envelope ended Oct 20 -- 11 days BEFORE the last possible Finals game.",
        ),
        SeasonEntry(
            "WNBA", "2027", covers_from=date(2026, 11, 4),
            window_start=date(2027, 4, 15),   # earlier than any recent tip-off (2026: May 8)
            window_end=date(2027, 11, 7),
            verified_through=None,
            official={"schedule": "unpublished"},
            sources=(),
            retrieved=R,
            notes="UNVERIFIED: no official 2027 dates published as of retrieval (wnba.com 2026 release "
                  "mentions none). Conservative wide placeholder; replace when the 2027 schedule ships.",
        ),
    ),
    "NBA": (
        SeasonEntry(
            "NBA", "2026-27", covers_from=date(2026, 7, 15),
            window_start=date(2026, 10, 6),   # regular season 2026-10-20 minus 14d
            window_end=date(2027, 6, 30),     # Finals end UNPUBLISHED; historical latest ~Jun 22 + margin
            verified_through=date(2027, 4, 17),
            official={"regular_season": "2026-10-20..2027-04-11", "play_in": "2027-04-13..2027-04-16",
                      "playoffs_start": "2027-04-17", "finals_end": "unpublished"},
            sources=("https://pr.nba.com/2026-27-nba-regular-season-schedule",
                     "https://www.nba.com/news/key-dates"),
            retrieved=R,
            notes="Verified through the playoffs start; the Finals end is an estimate (wide).",
        ),
        SeasonEntry(
            "NBA", "2027-28", covers_from=date(2027, 7, 1),
            window_start=date(2027, 10, 1),
            window_end=date(2028, 6, 30),
            verified_through=None,
            official={"schedule": "unpublished"},
            sources=(),
            retrieved=R,
            notes="UNVERIFIED conservative placeholder (NBA releases ~August).",
        ),
    ),
    "NFL": (
        SeasonEntry(
            "NFL", "2026", covers_from=date(2026, 3, 1),
            window_start=date(2026, 8, 26),   # Kickoff 2026-09-09 minus 14d (preseason has its own gate)
            window_end=date(2027, 2, 17),     # Super Bowl LXI 2027-02-14 plus 3d
            verified_through=date(2027, 2, 17),
            official={"kickoff_weekend": "2026-09-09..2026-09-14", "week_18": "2027-01-09..2027-01-10",
                      "wild_card": "2027-01-16..2027-01-18", "divisional": "2027-01-23..2027-01-24",
                      "conference_championships": "2027-01-31", "super_bowl_lxi": "2027-02-14"},
            sources=("https://www.nfl.com/news/2026-27-national-football-league-important-dates",),
            retrieved=R,
        ),
        SeasonEntry(
            "NFL", "2027", covers_from=date(2027, 2, 18),
            window_start=date(2027, 8, 20),
            window_end=date(2028, 2, 20),
            verified_through=None,
            official={"super_bowl_lxii": "2028, Atlanta, date TBA"},
            sources=("https://www.nfl.com/news/mercedes-benz-stadium-in-atlanta-to-host-super-bowl-lxii-in-2028",),
            retrieved=R,
            notes="UNVERIFIED conservative placeholder (NFL schedule releases ~May).",
        ),
    ),
    "NCAAF": (
        SeasonEntry(
            "NCAAF", "2026", covers_from=date(2026, 3, 1),
            window_start=date(2026, 8, 13),   # first FBS games 2026-08-29 (Week 0) minus 16d
            window_end=date(2027, 1, 28),     # CFP National Championship 2027-01-25 plus 3d
            verified_through=date(2027, 1, 28),
            official={"first_fbs_games": "2026-08-29", "cfp_first_round": "2026-12-18..2026-12-19",
                      "cfp_championship": "2027-01-25 (last game of the season)"},
            sources=("https://www.ncaa.com/news/football/article/2026-10-27/2026-27-college-football-bowl-game-schedule-scores-tv-channels-times",
                     "https://www.ncaa.com/news/football/article/2026-06-01/college-football-schedule-when-does-2026-college-football-season-start"),
            retrieved=R,
            notes="Championship date fetched from ncaa.com. Week 0 date is from the ncaa.com season-start "
                  "article as returned by search (page body not retrievable); past, not forward-relevant.",
        ),
        SeasonEntry(
            "NCAAF", "2027", covers_from=date(2027, 1, 29),
            window_start=date(2027, 8, 12),
            window_end=date(2028, 1, 31),
            verified_through=None,
            official={"schedule": "unpublished; CFP format beyond 2026-27 not confirmed"},
            sources=(),
            retrieved=R,
            notes="UNVERIFIED conservative placeholder.",
        ),
    ),
}


def entry_for(sport: str, d: date, calendar: Optional[dict] = None) -> Optional[SeasonEntry]:
    """The entry whose coverage contains `d`, or None (calendar expired / not declared)."""
    cal = SEASON_CALENDAR if calendar is None else calendar
    for e in cal.get((sport or "").upper(), ()):
        if e.covers(d):
            return e
    return None


def validate_calendar(calendar: Optional[dict] = None) -> list[str]:
    """Structural problems (empty list = sound): ordering, contiguous coverage, provenance present."""
    cal = SEASON_CALENDAR if calendar is None else calendar
    problems = []
    for sport, entries in cal.items():
        prev = None
        for e in entries:
            tag = f"{sport} {e.season}"
            if e.sport != sport:
                problems.append(f"{tag}: entry sport {e.sport!r} filed under {sport!r}")
            if not (e.covers_from <= e.window_start <= e.window_end):
                problems.append(f"{tag}: needs covers_from <= window_start <= window_end")
            if e.retrieved is None:
                problems.append(f"{tag}: no retrieval date")
            if e.verified_through is not None and not e.sources:
                problems.append(f"{tag}: claims verification with no source URL")
            if e.verified_through is not None and e.verified_through < e.covers_from:
                problems.append(f"{tag}: verified_through precedes coverage")
            if not e.official:
                problems.append(f"{tag}: no official-date record")
            if prev is not None and e.covers_from != prev.window_end + timedelta(days=1):
                problems.append(f"{tag}: coverage gap/overlap after {prev.season} "
                                f"({prev.window_end} -> {e.covers_from})")
            prev = e
    return problems


def coverage_status(sport: str, today: date, lookahead_days: int = COVERAGE_LOOKAHEAD_DAYS,
                    calendar: Optional[dict] = None) -> dict:
    """Coverage contract for one sport over [today, today + lookahead_days].

    Returns {sport, first_unverified, first_uncovered, unverified_fire, uncovered_fire, ok, lapse,
    unverified_entries}. first_unverified / first_uncovered = the first date >= today not covered by
    a VERIFIED entry / by ANY entry (coverage is finite, so both are always dates). *_fire = the first
    'today' on which the contract check reports it (= first_* - lookahead_days). ok = no unverified
    date inside the horizon; lapse = an uncovered date inside the horizon (the gate would go UNKNOWN)."""
    cal = SEASON_CALENDAR if calendar is None else calendar
    entries = cal.get(sport, ())

    def first_bad(pred) -> date:
        d = today
        for _ in range(3660):  # 10y cap; coverage is finite so this terminates far earlier
            e = entry_for(sport, d, cal)
            if e is None or not pred(e, d):
                return d
            d += timedelta(days=1)
        return d

    fu = first_bad(lambda e, d: e.verified_through is not None and d <= e.verified_through)
    fc = first_bad(lambda e, d: True)
    horizon = today + timedelta(days=lookahead_days)
    return {
        "sport": sport,
        "first_unverified": fu,
        "first_uncovered": fc,
        "unverified_fire": fu - timedelta(days=lookahead_days),
        "uncovered_fire": fc - timedelta(days=lookahead_days),
        "ok": fu > horizon,
        "lapse": fc <= horizon,
        "unverified_entries": [e.label() for e in entries if not e.verified],
    }
