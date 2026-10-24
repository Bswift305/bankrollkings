"""
Bankroll Kings - Zero-network feed availability report
=======================================================

Decides, WITHOUT spending a single API credit, whether a narrow paid prop/line
fetch is justified for each sport. The Oct 2026 incident taught us that a blanket
"the feeds are stale, refetch everything" burns credits on sports that have no
scheduled events (so a fetch can only return nothing) -- and worse, a sport whose
books simply have not posted markets yet (NBA opening week) looks identical to a
broken pipeline until you look at the schedule.

This report reads ONLY local files:
  - schedule:  data/schedules/<SPORT>_Schedule.csv  (+ _Odds.csv as odds-derived schedule)
  - game lines data/odds/<SPORT>_Odds.csv           (fallback data/schedules/<SPORT>_Odds.csv)
  - props:     data/props/<SPORT>_Props.csv

For each sport it answers three questions from disk:
  1. Are there eligible events inside the fetch window?       (schedule row count)
  2. How stale are the current-market artifacts?             (file mtime age)
  3. Is a paid fetch JUSTIFIED, and what would it prove?      (verdict below)

Verdicts (a paid fetch is "justified to PROBE" only -- a probe can still legitimately
come back NO_MARKETS_POSTED at 0 cost; that is a real answer, not a failure):
  - FRESH ............... props already fresh; no fetch needed.
  - PROBE_JUSTIFIED ..... events are scheduled in-window AND props are stale ->
                          a narrow fetch is worth its cost; expect UPDATED, or a
                          legitimate NO_MARKETS_POSTED if books have not posted yet.
  - NO_FETCH ............ no events in-window -> a fetch can only return nothing; do
                          not spend. (Off-season or between slates.)
  - NO_SCHEDULE ........  no readable schedule on disk -> cannot justify spend; refresh
                          the schedule feed first (usually free) before any paid props.

Staleness is NOT a hand-picked threshold: props age is judged against the ONE declared freshness
contract (services/freshness_contract.py, CLOCK B = refresh cadence, file mtime), the SAME source
qc_odds_feed and generate_run_status use -- so this report can never call a file STALE while those
call it FRESH. --stale-hours overrides it uniformly for what-if analysis only.

Timezone: event dates are compared against EASTERN "today" (CLAUDE.md s5), so the
UTC prod box does not roll a day early and mis-count tonight's slate.

Run on the box that has the data (prod or a data-populated dev box), with the app venv python:
    /opt/bankrollkings/venv/bin/python3 report_feed_availability.py
    .../python3 report_feed_availability.py --sports nfl,ncaaf,nba,mlb --props-window 7
Exit code is always 0 (this is a report, not a gate that should fail a run).
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
    _EASTERN = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover - zoneinfo always present on 3.9+ prod
    _EASTERN = None

import pandas as pd

from services.freshness_contract import refresh_cadence_hours

BASE_DIR = Path(__file__).resolve().parent

# Per sport: the on-disk artifacts. Game lines + props are the current-market feeds
# the incident was about; schedule is the zero-cost "should there be events" source.
SPORTS = {
    "NFL": {
        "schedule": ["data/schedules/NFL_Schedule.csv", "data/schedules/NFL_Odds.csv"],
        "lines": ["data/odds/NFL_Odds.csv", "data/schedules/NFL_Odds.csv"],
        "props": ["data/props/NFL_Props.csv"],
    },
    "NCAAF": {
        "schedule": ["data/schedules/NCAAF_Schedule.csv", "data/schedules/NCAAF_Odds.csv"],
        "lines": ["data/odds/NCAAF_Odds.csv", "data/schedules/NCAAF_Odds.csv"],
        "props": ["data/props/NCAAF_Props.csv"],
    },
    "NBA": {
        "schedule": ["data/schedules/NBA_Schedule.csv", "data/schedules/NBA_Odds.csv"],
        "lines": ["data/odds/NBA_Odds.csv", "data/schedules/NBA_Odds.csv"],
        "props": ["data/props/NBA_Props.csv"],
    },
    "WNBA": {
        "schedule": ["data/schedules/WNBA_Schedule.csv", "data/schedules/WNBA_Odds.csv"],
        "lines": ["data/odds/WNBA_Odds.csv", "data/schedules/WNBA_Odds.csv"],
        "props": ["data/props/WNBA_Props.csv"],
    },
    "MLB": {
        "schedule": ["data/schedules/MLB_Schedule.csv", "data/schedules/MLB_Odds.csv"],
        "lines": ["data/odds/MLB_Odds.csv", "data/schedules/MLB_Odds.csv"],
        "props": ["data/props/MLB_Props.csv"],
    },
}

# Candidate date columns in a schedule/odds CSV, most-specific first.
_DATE_COLS = ("Date", "CommenceDate", "GameDate", "commence_time", "CommenceTime", "LastUpdated")


def _eastern_today() -> date:
    now = datetime.now(_EASTERN) if _EASTERN else datetime.now()
    return now.date()


def _first_existing(rels: list[str]) -> Path | None:
    for rel in rels:
        p = BASE_DIR / rel
        if p.exists() and p.is_file():
            return p
    return None


def _age_hours(path: Path | None) -> float | None:
    if path is None:
        return None
    try:
        return (datetime.now().timestamp() - path.stat().st_mtime) / 3600.0
    except OSError:
        return None


def _upcoming_counts(path: Path | None, today: date, windows: list[int]) -> tuple[dict[int, int], str]:
    """Count schedule rows whose event date is in [today, today+window]. Returns
    ({window: count}, note). Zero-network: parses the Date column only."""
    empty = {w: 0 for w in windows}
    if path is None:
        return empty, "no schedule file"
    try:
        df = pd.read_csv(path, low_memory=False)
    except Exception as exc:
        return empty, f"unreadable schedule ({type(exc).__name__})"
    if df.empty:
        return empty, "schedule empty"
    col = next((c for c in _DATE_COLS if c in df.columns), None)
    if col is None:
        return empty, f"no date column (have: {', '.join(map(str, df.columns[:6]))})"
    parsed = pd.to_datetime(df[col], errors="coerce", utc=False)
    dates = parsed.dropna()
    if dates.empty:
        return empty, f"date column {col!r} did not parse"
    event_dates = dates.dt.date
    counts = {}
    for w in windows:
        hi = today + timedelta(days=w)
        counts[w] = int(((event_dates >= today) & (event_dates <= hi)).sum())
    return counts, f"from {col!r}"


def _verdict(lines_age, props_age, upcoming_props_window: int, has_schedule: bool,
             stale_hours: float) -> tuple[str, str]:
    """Return (verdict, one-line rationale)."""
    props_stale = props_age is None or props_age > stale_hours
    if not has_schedule:
        return "NO_SCHEDULE", "no readable schedule on disk -- refresh the (free) schedule feed before any paid props"
    if upcoming_props_window <= 0:
        return "NO_FETCH", "no events scheduled in-window -- a paid fetch can only return nothing"
    if not props_stale:
        return "FRESH", f"props fresh ({props_age:.0f}h) -- no fetch needed"
    # events scheduled AND props stale
    return ("PROBE_JUSTIFIED",
            f"{upcoming_props_window} event(s) in-window and props stale -- a NARROW probe is worth its cost "
            f"(expect UPDATED, or a legitimate NO_MARKETS_POSTED at 0 cost if books have not posted yet)")


def build_report(sports: list[str], props_window: int, lines_window: int,
                 stale_hours: float | None = None) -> dict:
    """stale_hours None => use the declared freshness contract's props cadence per sport (CLOCK B);
    a number overrides it uniformly (for what-if analysis only)."""
    today = _eastern_today()
    windows = sorted({2, props_window, lines_window})
    rows = []
    for sport in sports:
        spec = SPORTS[sport]
        sched = _first_existing(spec["schedule"])
        lines = _first_existing(spec["lines"])
        props = _first_existing(spec["props"])
        lines_age = _age_hours(lines)
        props_age = _age_hours(props)
        props_stale_hours = stale_hours if stale_hours is not None else refresh_cadence_hours("props", sport)
        counts, sched_note = _upcoming_counts(sched, today, windows)
        verdict, rationale = _verdict(lines_age, props_age, counts.get(props_window, 0),
                                      has_schedule=sched is not None, stale_hours=props_stale_hours)
        rows.append({
            "sport": sport,
            "schedule_file": str(sched.relative_to(BASE_DIR)) if sched else "(none)",
            "schedule_note": sched_note,
            "events_next_2d": counts.get(2, 0),
            f"events_next_{props_window}d": counts.get(props_window, 0),
            "lines_file": str(lines.relative_to(BASE_DIR)) if lines else "(none)",
            "lines_age_h": round(lines_age, 1) if lines_age is not None else None,
            "props_file": str(props.relative_to(BASE_DIR)) if props else "(none)",
            "props_age_h": round(props_age, 1) if props_age is not None else None,
            "props_stale_hours": props_stale_hours,
            "verdict": verdict,
            "rationale": rationale,
        })
    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "eastern_today": today.isoformat(),
        "props_window_days": props_window,
        "lines_window_days": lines_window,
        "stale_hours_override": stale_hours,
        "rows": rows,
        "probe_justified": [r["sport"] for r in rows if r["verdict"] == "PROBE_JUSTIFIED"],
    }


def _fmt_age(v) -> str:
    return "MISSING" if v is None else f"{v:.0f}h"


def main() -> int:
    parser = argparse.ArgumentParser(description="Zero-network feed availability + paid-fetch justification report.")
    parser.add_argument("--sports", default="nfl,ncaaf,nba,mlb",
                        help="Comma-separated sports (nfl,ncaaf,nba,wnba,mlb). Default: nfl,ncaaf,nba,mlb")
    parser.add_argument("--props-window", type=int, default=7, help="Days ahead props are posted/fetched. Default 7.")
    parser.add_argument("--lines-window", type=int, default=5, help="Days ahead game lines are fetched. Default 5.")
    parser.add_argument("--stale-hours", type=float, default=None,
                        help="Override the declared props cadence (services/freshness_contract.py CLOCK B) "
                             "uniformly, for what-if analysis. Default: use the contract per sport.")
    args = parser.parse_args()

    requested = [s.strip().upper() for s in args.sports.split(",") if s.strip()]
    unknown = [s for s in requested if s not in SPORTS]
    if unknown:
        print(f"[FAIL] unknown sport(s): {', '.join(unknown)} (known: {', '.join(SPORTS)})")
        return 2

    report = build_report(requested, args.props_window, args.lines_window, args.stale_hours)
    thr_note = (f"override stale>{args.stale_hours:.0f}h" if args.stale_hours is not None
                else "stale = freshness_contract props cadence")

    print("=" * 78)
    print("BANKROLL KINGS - FEED AVAILABILITY (zero-network)")
    print("=" * 78)
    print(f"Eastern today: {report['eastern_today']}   props window: {args.props_window}d   "
          f"lines window: {args.lines_window}d   {thr_note}")
    print("-" * 78)
    pw = args.props_window
    for r in report["rows"]:
        print(f"{r['sport']:<6} verdict={r['verdict']}")
        print(f"       schedule: {r['schedule_file']} ({r['schedule_note']}) | "
              f"events next2d={r['events_next_2d']} next{pw}d={r[f'events_next_{pw}d']}")
        print(f"       lines:    {r['lines_file']} age={_fmt_age(r['lines_age_h'])} | "
              f"props: {r['props_file']} age={_fmt_age(r['props_age_h'])} (props stale>{r['props_stale_hours']:.0f}h)")
        print(f"       -> {r['rationale']}")
        print()

    if report["probe_justified"]:
        print("PAID PROBE JUSTIFIED (narrow, ONE sport at a time), in this order:")
        for s in report["probe_justified"]:
            print(f"   - {s}")
        print("Everything else: do NOT spend (no in-window events, or already fresh).")
    else:
        print("No sport justifies a paid fetch right now (none have in-window events with stale props).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
