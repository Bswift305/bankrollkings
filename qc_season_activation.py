"""QC: season activation requires props rows AND scheduled events in the forward window.

Incident (Nov 2026): prod bk-daily failed every day because season_utils.active_sports() called a sport
active whenever data/props/<SPORT>_Props.csv had ANY row. Stale off-season rows never expire, so MLB and
WNBA stayed "active"; their refreshes then (correctly) failed the empty-slice validator (0 rows < min 1)
and, being "in season", were reported FAIL instead of SKIP (off-season). The validator is NOT weakened;
activation now also needs at least one event in [Eastern today, today + 7d] from the schedule/lines
artifacts. Missing/undatable schedule falls back to the old props-rows behaviour so an in-season sport is
never silently dropped.

Pure/offline: synthetic fixtures in a temp dir, fixed Eastern "today", no network, no app import.
Prints [ok]/[FAIL] per case; exits 1 on any failure.
"""
from __future__ import annotations

import csv
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

import season_utils as su
from services import timeutils

TODAY = date(2026, 11, 1)  # Sunday; NFL + NBA in season, MLB + WNBA over
RESULTS: list[tuple[bool, str]] = []


def check(cond: bool, desc: str) -> None:
    RESULTS.append((bool(cond), desc))
    print(f"[{'ok' if cond else 'FAIL'}] {desc}")


def _write(path: Path, header: list[str], rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        if header:
            w.writerow(header)
        w.writerows(rows)


def props(base: Path, sport: str, rows: int = 3) -> None:
    _write(base / f"data/props/{sport}_Props.csv", ["Player", "Stat", "Line"],
           [[f"P{i}", "PTS", "20.5"] for i in range(rows)])


def schedule(base: Path, sport: str, offsets: list[int], rel: str | None = None) -> None:
    rel = rel or f"data/schedules/{sport}_Schedule.csv"
    _write(base / rel, ["Date", "Time", "Away", "Home"],
           [[(TODAY + timedelta(days=d)).isoformat(), "19:00", "A", "H"] for d in offsets])


def commence(base: Path, sport: str, values: list[str]) -> None:
    _write(base / f"data/schedules/{sport}_Schedule.csv", ["commence_time", "Away", "Home"],
           [[v, "A", "H"] for v in values])


def act(base: Path, sport: str, **kw) -> tuple[bool, str]:
    return su.sport_activation(sport, today=TODAY, base_dir=base, **kw)


def case(fn) -> None:
    with tempfile.TemporaryDirectory() as td:
        su._EVENT_DATE_MEMO.clear()
        fn(Path(td))


def main() -> int:
    # 1. Stale props rows + only past events (the prod MLB/WNBA state) -> inactive.
    def c1(b):
        props(b, "MLB")
        schedule(b, "MLB", [-31, -30])
        _write(b / "data/odds/MLB_Odds.csv", ["Date", "Away", "Home"], [["2026-10-01", "A", "H"]])
        a, why = act(b, "MLB")
        check(not a, f"stale props + only past events -> inactive ({why})")
    case(c1)

    # 2. Events in window -> active.
    def c2(b):
        props(b, "NBA")
        schedule(b, "NBA", [0, 1, 2])
        check(act(b, "NBA")[0], "props + events today..+2d -> active")
    case(c2)

    # 3. Events only beyond the window -> inactive; window edge is inclusive.
    def c3(b):
        props(b, "WNBA")
        schedule(b, "WNBA", [8, 30, 200])
        check(not act(b, "WNBA")[0], "events only at +8d/+30d/+200d (beyond 7d) -> inactive")
        schedule(b, "WNBA", [7])
        su._EVENT_DATE_MEMO.clear()
        check(act(b, "WNBA")[0], "event exactly at today+7 -> active (inclusive edge)")
        check(not act(b, "WNBA", window_days=6)[0], "same event with window_days=6 -> inactive")
    case(c3)

    # 4. No schedule/lines file at all -> documented fallback to props-rows behaviour (active).
    def c4(b):
        props(b, "NFL")
        a, why = act(b, "NFL")
        check(a and "fallback" in why, f"schedule missing -> props-only fallback keeps sport active ({why})")
        ok, detail = su.events_in_window("NFL", TODAY, base_dir=b)
        check(ok is None, f"events_in_window reports UNKNOWN (None) when no schedule exists ({detail})")
    case(c4)

    # 4b. Schedule present but undatable (rows, no date column / unparseable dates) -> fallback, not drop.
    def c4b(b):
        props(b, "NBA")
        _write(b / "data/schedules/NBA_Schedule.csv", ["Away", "Home"], [["A", "H"]])
        check(act(b, "NBA")[0], "schedule rows with no date column -> UNKNOWN -> props fallback (active)")
        _write(b / "data/schedules/NBA_Schedule.csv", ["Date", "Away", "Home"], [["TBD", "A", "H"]])
        su._EVENT_DATE_MEMO.clear()
        check(act(b, "NBA")[0], "unparseable dates -> UNKNOWN -> props fallback (active)")
    case(c4b)

    # 4c. Header-only / blank schedule = the fetchers' off-season output -> determinate, inactive.
    def c4c(b):
        props(b, "MLB")
        _write(b / "data/schedules/MLB_Schedule.csv", ["Date", "Time", "Away", "Home"], [])
        check(not act(b, "MLB")[0], "header-only schedule (provider had no events) -> inactive")
        (b / "data/schedules/MLB_Schedule.csv").write_text("\r\n", encoding="utf-8")
        su._EVENT_DATE_MEMO.clear()
        check(not act(b, "MLB")[0], "blank (2-byte) schedule file -> inactive")
    case(c4c)

    # 5. Empty props -> inactive regardless of schedule.
    def c5(b):
        _write(b / "data/props/NBA_Props.csv", ["Player", "Stat", "Line"], [])
        schedule(b, "NBA", [0, 1])
        check(not act(b, "NBA")[0], "header-only props + in-window events -> inactive")
        (b / "data/props/NBA_Props.csv").write_text("", encoding="utf-8")
        check(not act(b, "NBA")[0], "zero-byte props + in-window events -> inactive")
        (b / "data/props/NBA_Props.csv").unlink()
        check(not act(b, "NBA")[0], "missing props + in-window events -> inactive")
    case(c5)

    # 6. Eastern-date boundary: 01:00 UTC belongs to the PREVIOUS Eastern date.
    check(timeutils.event_eastern_date("2026-11-09T01:00:00Z") == date(2026, 11, 8),
          "event_eastern_date: 2026-11-09T01:00Z -> 2026-11-08 (Eastern)")
    check(timeutils.event_eastern_date("2026-11-02T01:00:00+00:00") == date(2026, 11, 1),
          "event_eastern_date: 2026-11-02T01:00+00:00 -> 2026-11-01 (Eastern)")
    check(timeutils.event_eastern_date("2026-11-01") == date(2026, 11, 1),
          "event_eastern_date: naive 'YYYY-MM-DD' is taken as already-Eastern")
    check(timeutils.event_eastern_date("") is None and timeutils.event_eastern_date("nan") is None,
          "event_eastern_date: blank/nan -> None")

    def c6(b):
        props(b, "NBA")
        commence(b, "NBA", ["2026-11-09T01:00:00Z"])  # Nov 8 8pm ET = today+7 -> in window
        check(act(b, "NBA")[0], "game at today+8 01:00 UTC is today+7 Eastern -> active (UTC date would miss)")
        commence(b, "NBA", ["2026-11-01T01:00:00Z"])  # Oct 31 9pm ET -> yesterday
        su._EVENT_DATE_MEMO.clear()
        check(not act(b, "NBA")[0], "game at today 01:00 UTC is YESTERDAY Eastern -> inactive (UTC date would count it)")
    case(c6)

    # 7. Union of sources: an empty schedule alias must not hide games in the game-lines feed.
    def c7(b):
        props(b, "NBA")
        _write(b / "data/schedules/NBA_Schedule.csv", ["Date", "Away", "Home"], [])
        schedule(b, "NBA", [1], rel="data/odds/NBA_Odds.csv")
        check(act(b, "NBA")[0], "header-only NBA_Schedule.csv but data/odds/NBA_Odds.csv has a game -> active")
    case(c7)

    # 8. Full prod reproduction: NFL + NBA (real events) stay active; MLB + WNBA (stale props) drop.
    def c8(b):
        for s in ("NBA", "WNBA", "MLB", "NFL", "NCAAF"):
            props(b, s)
        schedule(b, "NFL", [0, 4, 7])
        schedule(b, "NBA", [0, 1, 2, 3])
        schedule(b, "NCAAF", [2, 5, 6])
        schedule(b, "WNBA", [-96])
        _write(b / "data/schedules/MLB_Schedule.csv", [], [])
        schedule(b, "MLB", [-31], rel="data/odds/MLB_Odds.csv")
        got = su.active_sports(today=TODAY, base_dir=b)
        check(got == {"NFL", "NBA", "NCAAF"}, f"prod repro: active_sports == {{NFL, NBA, NCAAF}} (got {sorted(got)})")
        # Default 'today' is the Eastern clock from services.timeutils, never datetime.now().
        orig = timeutils.eastern_today
        timeutils.eastern_today = lambda: TODAY
        try:
            check(su.active_sports(base_dir=b) == got, "default today comes from timeutils.eastern_today()")
        finally:
            timeutils.eastern_today = orig
        # Memo invalidates on change: MLB posts games -> reactivates without a restart.
        schedule(b, "MLB", [0, 1, 2, 3, 4, 5])
        check("MLB" in su.active_sports(today=TODAY, base_dir=b), "schedule rewrite invalidates memo -> MLB reactivates")
    case(c8)

    # 9. NFL preseason gate is independent and unchanged.
    check(not su.nfl_preseason_active(date(2026, 11, 1)) and su.nfl_preseason_active(date(2026, 8, 15)),
          "nfl_preseason_active unchanged (closed Nov 1, open Aug 15)")

    # 10. report_feed_availability shares the source lists + Eastern parser (no divergent copy).
    import report_feed_availability as rfa
    shared = all(rfa.SPORTS[s]["schedule"] == list(su.SCHEDULE_SOURCES[s])
                 and rfa.SPORTS[s]["lines"] == list(su.LINES_SOURCES[s]) for s in rfa.SPORTS)
    check(shared, "report_feed_availability.SPORTS schedule/lines lists come from season_utils")
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "X_Schedule.csv"
        _write(p, ["commence_time", "Away", "Home"], [["2026-11-09T01:00:00Z", "A", "H"]])
        counts, _note = rfa._upcoming_counts(p, TODAY, [7])
        check(counts.get(7) == 1, f"report counts the 01:00 UTC game on its Eastern date (got {counts})")

    # 11. Callers import the shared gate (no forked props-only copy).
    import run_daily, run_all_scorecards, run_bk_edge_engine_pipeline  # noqa: E401
    check(all(m.active_sports is su.active_sports for m in (run_daily, run_all_scorecards, run_bk_edge_engine_pipeline)),
          "run_daily / run_all_scorecards / run_bk_edge_engine_pipeline use season_utils.active_sports")
    src = Path(__file__).resolve().parent.joinpath("run_prelaunch_scorecard.py").read_text(encoding="utf-8")
    check("from season_utils import active_sports" in src,
          "run_prelaunch_scorecard._active_sports delegates to season_utils.active_sports")

    failed = [d for ok, d in RESULTS if not ok]
    print("=" * 60)
    print(f"SEASON ACTIVATION QC: {len(RESULTS) - len(failed)} ok, {len(failed)} FAIL")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
