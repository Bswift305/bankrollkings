"""NFL season calendar — the SINGLE, PURE source of the completed-week / season contract.

Extracted from `app.py` so the dark research-candidate identity/event adapter and store can consume the
exact same season logic WITHOUT importing the Flask monolith. This module is deliberately pure and
side-effect-free: it imports only the standard library (`datetime.date`), reads NO system clock, NO
filesystem, NO network, and NO app/Flask/pandas. The CORE resolver takes the Eastern calendar date
EXPLICITLY; supplying "today" (via the one shared Eastern-date provider) is the caller's job, so nothing
here embeds a second timezone implementation.

`app.py` keeps `_nfl_expected_completed_week(today=None)` as a thin compatibility wrapper that supplies
`sports_today_date()` when `today` is omitted and then delegates here; existing callers do not change.

Yearly chore (unchanged): add each new NFL season's Week-1 Thursday to `NFL_SEASON_WEEK1_THURSDAY`. A
season with no entry resolves to `(None, season)` — "no staleness claim" — rather than guessing.
"""
from __future__ import annotations

from datetime import date

# Week 1's Thursday (Eastern calendar date) per season. SINGLE SOURCE — `app.py` imports this name.
NFL_SEASON_WEEK1_THURSDAY: dict[int, date] = {
    2025: date(2025, 9, 4),
    2026: date(2026, 9, 10),
}


def expected_completed_week(today: date) -> tuple[int | None, int]:
    """How many NFL weeks SHOULD be final as of `today` (an EXPLICIT Eastern calendar date). Pure: it
    never reads the clock. Returns `(week, season)`.

    A week's slate runs Thu->Mon; it is not "complete" until its games finalize, so a week is only counted
    once its Tuesday (ET) has passed. `week == 0` means the season has not started; `(None, season)` means
    there is no configured Week-1 anchor for that season (so no staleness claim is made). Regular season
    only (capped at 18). NFL season N spans Sep N -> Feb N+1, so Jan/Feb dates belong to the prior season
    label.
    """
    season = today.year if today.month >= 3 else today.year - 1
    wk1 = NFL_SEASON_WEEK1_THURSDAY.get(season)
    if wk1 is None:
        return None, season
    if today < wk1:
        return 0, season
    days = (today - wk1).days
    cur_week = days // 7 + 1          # 1-based week the slate is currently in
    day_in_week = days % 7           # 0=Thu .. 4=Mon, 5=Tue (games final), 6=Wed
    completed = cur_week if day_in_week >= 5 else cur_week - 1
    return max(0, min(completed, 18)), season


__all__ = ["NFL_SEASON_WEEK1_THURSDAY", "expected_completed_week"]
