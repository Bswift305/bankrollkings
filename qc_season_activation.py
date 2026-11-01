"""QC: the governed season state + the daily operator's PRE-EXECUTION season gate (F2v2, Nov 2026).

Incident: prod bk-daily (`run_daily.py --sports nba,wnba,mlb --continue-on-error`) failed every day
off-season. season_utils.active_sports() called a sport active whenever its props file had ANY row, so
stale MLB/WNBA rows kept them "active"; their steps ran, made provider calls that returned 0 rows, the
strong validator (correctly, never weakened) rejected the empty slice, and the step FAILed. Relabeling
the failure as SKIP after the fact was rejected: an authoritatively off-season sport must not run its
provider-calling steps at all.

This QC proves, with synthetic fixtures in a temp dir, a fixed Eastern "today", a RECORDING STUB RUNNER
(no subprocess), no network and no app import:
  * season_state() = ACTIVE / OFF_SEASON / UNKNOWN from schedule + calendar evidence, never props;
  * OFF_SEASON sport => zero step executions (the stub records every call);
  * ACTIVE runs; UNKNOWN (missing / undatable schedule) runs (fail-open);
  * empty props + in-window events => ACTIVE (no bootstrap trap);
  * stale props + no events => OFF_SEASON;
  * the Eastern boundary (a 01:00 UTC game belongs to the previous Eastern date);
  * the calendar re-opens a sport whose on-disk schedule is frozen (no deadlock);
  * precedence: schedule evidence supersedes the calendar (ACTIVE outside the window and past its
    coverage); absence evidence never skips inside a window; an EXPIRED calendar is UNKNOWN (fail-open);
  * the governed calendar (season_calendar.py): provenance present, structure sound, coverage contract
    fires exactly at the 60-day look-ahead (injected 'today' + synthetic calendar), unverified reported;
  * NFL preseason pre-skip unchanged; football steps are not pre-gated;
  * --continue-on-error semantics; prod-shaped fixture (NFL/NCAAF/NBA active, MLB/WNBA off-season).
Prints [ok]/[FAIL] per case; exits 1 on any failure.
"""
from __future__ import annotations

import contextlib
import csv
import io
import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

import run_daily
import season_utils as su
from services import timeutils

TODAY = date(2026, 11, 8)  # NFL/NCAAF/NBA in season; MLB + WNBA past their audited windows (end Nov 3)
RESULTS: list[tuple[bool, str]] = []
DAILY_SPORTS = {"nba", "wnba", "mlb"}


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


def schedule(base: Path, sport: str, offsets: list[int], today: date = TODAY,
             rel: str | None = None) -> None:
    rel = rel or f"data/schedules/{sport}_Schedule.csv"
    _write(base / rel, ["Date", "Time", "Away", "Home"],
           [[(today + timedelta(days=d)).isoformat(), "19:00", "A", "H"] for d in offsets])


def odds(base: Path, sport: str, offsets: list[int], today: date = TODAY) -> None:
    for rel in (f"data/odds/{sport}_Odds.csv", f"data/schedules/{sport}_Odds.csv"):
        _write(base / rel, ["Date", "Time", "Away", "Home", "LastUpdated"],
               [[(today + timedelta(days=d)).isoformat(), "19:00", "A", "H", "2026-10-28 09:00"]
                for d in offsets])


def state(base: Path, sport: str, today: date = TODAY):
    return su.season_state(sport, today=today, base_dir=base)


def case(fn) -> None:
    with tempfile.TemporaryDirectory() as td:
        su._EVENT_DATE_MEMO.clear()
        fn(Path(td))


def prod_fixture(b: Path) -> None:
    """Shaped like prod in early Nov 2026: stale MLB/WNBA props + last-season schedules; live NFL/NCAAF/NBA."""
    for s in ("MLB", "WNBA", "NFL", "NCAAF", "NBA"):
        props(b, s)
    schedule(b, "MLB", [-6, -5, -4]); odds(b, "MLB", [-31])        # WS ended; lines 89-96h stale
    schedule(b, "WNBA", [-95]); odds(b, "WNBA", [-95])              # Finals long over
    schedule(b, "NFL", [0, 3, 7]); odds(b, "NFL", [0, 3])
    schedule(b, "NCAAF", [2, 5]); odds(b, "NCAAF", [2])
    schedule(b, "NBA", [0, 1, 2]); odds(b, "NBA", [0, 1])


class Recorder:
    """Stub runner: records every execution; never spawns a process or touches the network."""

    def __init__(self, fail_labels=()):
        self.calls: list[tuple[str, list[str]]] = []
        self.fail_labels = set(fail_labels)

    def __call__(self, label, command, timeout):
        self.calls.append((label, list(command)))
        return (label not in self.fail_labels), f"stub output for {label}"


def run_ops(states, recorder, preseason_open=False, continue_on_error=True, sports=DAILY_SPORTS):
    steps = run_daily._active_refresh_steps(sports)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        lines, outcomes, failed = run_daily.execute_steps(
            steps, states, recorder, preseason_open=preseason_open, continue_on_error=continue_on_error)
    return steps, lines, outcomes, failed, buf.getvalue()


MLB_ONLY = ("MLB daily refresh", "MLB featured results", "MLB lineups")
WNBA_ONLY = ("WNBA game lines", "WNBA player props", "WNBA player logs", "WNBA featured results",
             "WNBA calibration", "Runtime snapshots")


def main() -> int:
    # ---- state machine -------------------------------------------------------------------------
    def c_stale(b):
        props(b, "MLB")
        schedule(b, "MLB", [-31, -30]); odds(b, "MLB", [-31])
        st = state(b, "MLB")
        check(st.state == su.OFF_SEASON, f"stale props + only past events, outside calendar -> OFF_SEASON ({st.reason})")
    case(c_stale)

    def c_boot(b):
        _write(b / "data/props/MLB_Props.csv", ["Player", "Stat", "Line"], [])  # header only
        schedule(b, "MLB", [2])
        st = state(b, "MLB")
        check(st.state == su.ACTIVE, f"EMPTY props + in-window event -> ACTIVE (no bootstrap trap) ({st.reason})")
    case(c_boot)

    def c_noprops(b):
        schedule(b, "NBA", [1])  # no props file at all
        st = state(b, "NBA")
        check(st.state == su.ACTIVE, "MISSING props file + in-window event -> ACTIVE (props is not an input)")
    case(c_noprops)

    def c_missing(b):
        props(b, "MLB")
        st = state(b, "MLB")
        check(st.state == su.UNKNOWN, f"no schedule/lines artifact, outside calendar -> UNKNOWN ({st.reason})")
    case(c_missing)

    def c_undatable(b):
        _write(b / "data/schedules/MLB_Schedule.csv", ["Away", "Home"], [["A", "H"]])
        _write(b / "data/odds/MLB_Odds.csv", ["Date", "Away", "Home"], [["not-a-date", "A", "H"]])
        st = state(b, "MLB")
        check(st.state == su.UNKNOWN, "schedule with no date column / unparseable dates -> UNKNOWN (never OFF_SEASON)")
    case(c_undatable)

    def c_mixed_unknown(b):
        schedule(b, "MLB", [-10])  # determinate, no in-window events
        _write(b / "data/odds/MLB_Odds.csv", ["Away", "Home"], [["A", "H"]])  # undatable sibling
        st = state(b, "MLB")
        check(st.state == su.UNKNOWN, "one determinate-empty + one undatable artifact -> UNKNOWN (cannot prove no events)")
    case(c_mixed_unknown)

    def c_headeronly(b):
        _write(b / "data/schedules/WNBA_Schedule.csv", ["Date", "Away", "Home"], [])
        (b / "data/schedules").mkdir(parents=True, exist_ok=True)
        (b / "data/schedules/WNBA_Odds.csv").write_text("\n", encoding="utf-8")  # empty-frame to_csv
        st = state(b, "WNBA")
        check(st.state == su.OFF_SEASON, "header-only / blank provider artifacts (provider listed no events) -> OFF_SEASON")
    case(c_headeronly)

    def c_union(b):
        schedule(b, "MLB", [-20])  # stale alias
        odds(b, "MLB", [3])        # fresh lines list an event
        st = state(b, "MLB")
        check(st.state == su.ACTIVE, "a stale alias cannot hide an in-window event in another artifact (union)")
    case(c_union)

    def c_calendar(b):
        props(b, "MLB")
        schedule(b, "MLB", [-140], today=date(2026, 3, 12)); odds(b, "MLB", [-140], today=date(2026, 3, 12))
        st = state(b, "MLB", today=date(2026, 3, 12))
        check(st.state == su.ACTIVE, f"NO DEADLOCK: frozen last-season schedule, Mar 12 -> calendar re-opens MLB ACTIVE ({st.reason})")
        st2 = state(b, "MLB", today=date(2026, 3, 9))
        check(st2.state == su.OFF_SEASON, "Mar 9 (before the MLB envelope), frozen schedule -> still OFF_SEASON")
    case(c_calendar)

    def c_midseason_outage(b):
        schedule(b, "WNBA", [-12], today=date(2026, 7, 20)); odds(b, "WNBA", [-12], today=date(2026, 7, 20))
        st = state(b, "WNBA", today=date(2026, 7, 20))
        check(st.state == su.ACTIVE, "mid-season >7d feed outage (files stale) stays ACTIVE inside the calendar -> refresh keeps retrying")
    case(c_midseason_outage)

    def c_tail(b):
        schedule(b, "MLB", [0, 1], today=date(2026, 11, 10))
        st = state(b, "MLB", today=date(2026, 11, 10))
        check(st.state == su.ACTIVE and "events scheduled" in st.reason,
              f"P1: postseason running past the calendar window stays ACTIVE while games are listed ({st.reason})")
    case(c_tail)

    check(su.in_season_window("NBA", date(2027, 1, 15)) is True
          and su.in_season_window("NBA", date(2026, 7, 15)) is False
          and su.in_season_window("NFL", date(2027, 2, 10)) is True
          and su.in_season_window("NCAAMB", TODAY) is None,
          "calendar envelopes wrap the new year (NBA Jan in, Jul out; NFL Feb in); undeclared sport -> None")

    def c_nocal(b):
        schedule(b, "NCAAMB", [-30])
        st = state(b, "NCAAMB")
        check(st.state == su.UNKNOWN, "sport with no declared calendar -> UNKNOWN (fail-open), never OFF_SEASON")
    case(c_nocal)

    # ---- governed calendar: precedence (schedule evidence supersedes the calendar) ----------------
    def c_inwindow_absence(b):
        # Fresh, readable artifacts listing ZERO upcoming events while inside the window (e.g. a World
        # Series that ended in 5): documented decision -- absence never skips inside the window.
        _write(b / "data/schedules/MLB_Schedule.csv", ["Date", "Away", "Home"], [])
        odds(b, "MLB", [-4], today=date(2026, 11, 1))
        st = state(b, "MLB", today=date(2026, 11, 1))
        check(st.state == su.ACTIVE and "calendar holds ACTIVE" in st.reason,
              f"P2: inside window + readable zero-event evidence -> ACTIVE, absence never skips ({st.reason})")
        st2 = state(b, "MLB", today=date(2026, 11, 4))
        check(st2.state == su.OFF_SEASON,
              f"... the day after the audited window end (Nov 3) the same evidence -> OFF_SEASON ({st2.reason})")
    case(c_inwindow_absence)

    def c_wnba_finals_g7(b):
        # The pre-audit envelope ended Oct 20, eleven days before the official last possible Finals game.
        schedule(b, "WNBA", [-20], today=date(2026, 10, 31)); odds(b, "WNBA", [-20], today=date(2026, 10, 31))
        st = state(b, "WNBA", today=date(2026, 10, 31))
        check(st.state == su.ACTIVE,
              f"WNBA Finals G7 day (2026-10-31) with a frozen schedule -> ACTIVE via the audited calendar ({st.reason})")
    case(c_wnba_finals_g7)

    def c_evidence_outside(b):
        schedule(b, "NBA", [3], today=date(2026, 8, 1))
        st = state(b, "NBA", today=date(2026, 8, 1))
        check(st.state == su.ACTIVE and "events scheduled" in st.reason,
              "P1: schedule evidence of an in-window event OUTSIDE the calendar window -> ACTIVE (evidence wins)")
    case(c_evidence_outside)

    FAR = date(2029, 6, 1)  # beyond every calendar entry's coverage

    def c_expired_evidence(b):
        schedule(b, "MLB", [2], today=FAR)
        st = state(b, "MLB", today=FAR)
        check(st.state == su.ACTIVE, "P1: calendar EXPIRED but schedule lists an in-window event -> ACTIVE")
    case(c_expired_evidence)

    def c_expired_absence(b):
        schedule(b, "MLB", [-200], today=FAR); odds(b, "MLB", [-200], today=FAR)
        st = state(b, "MLB", today=FAR)
        check(st.state == su.UNKNOWN and "no season calendar entry covers" in st.reason,
              f"P3: calendar EXPIRED + readable zero-event schedule -> UNKNOWN, never OFF_SEASON ({st.reason})")
        states = su.season_states(today=FAR, base_dir=b)
        rec = Recorder()
        _, _, outcomes, _, _ = run_ops(states, rec)
        check(set(MLB_ONLY) <= {l for l, _ in rec.calls},
              "P3: expired-calendar UNKNOWN MLB -> its steps RUN (fail-open)")
    case(c_expired_absence)

    def c_unverified_reason(b):
        schedule(b, "WNBA", [-30], today=date(2027, 6, 1))
        st = state(b, "WNBA", today=date(2027, 6, 1))
        check(st.state == su.ACTIVE and "UNVERIFIED" in st.reason,
              f"an unverified (conservative) entry still bootstraps, and says so in the reason ({st.reason})")
    case(c_unverified_reason)

    # ---- governed calendar: provenance + coverage contract ---------------------------------------
    import season_calendar as sc
    check(sc.validate_calendar() == [], f"real calendar is structurally sound: {sc.validate_calendar() or 'no problems'}")
    check(all(sc.SEASON_CALENDAR.get(s) for s in su.GOVERNED_SPORTS),
          "every governed sport has calendar entries")
    ents = [e for es in sc.SEASON_CALENDAR.values() for e in es]
    check(all(e.retrieved and e.official for e in ents)
          and all(e.sources for e in ents if e.verified_through is not None),
          "provenance: every entry has a retrieval date + official-date record; every verified claim cites a URL")
    check(all(u.startswith("https://") for e in ents for u in e.sources),
          "provenance: source URLs are https")

    D = date
    syn = {"XL": (
        sc.SeasonEntry("XL", "S1", covers_from=D(2030, 1, 1), window_start=D(2030, 3, 1),
                       window_end=D(2030, 10, 31), verified_through=D(2030, 10, 31),
                       official={"x": "y"}, sources=("https://example.invalid/s1",), retrieved=D(2029, 12, 1)),
        sc.SeasonEntry("XL", "S2", covers_from=D(2030, 11, 1), window_start=D(2031, 3, 1),
                       window_end=D(2031, 10, 31), verified_through=None,
                       official={"x": "unpublished"}, retrieved=D(2029, 12, 1)),
    )}
    fire_unv = D(2030, 11, 1) - timedelta(days=60)   # 2030-09-02
    fire_lapse = D(2031, 11, 1) - timedelta(days=60)  # 2031-09-02
    a = sc.coverage_status("XL", fire_unv - timedelta(days=1), calendar=syn)
    z = sc.coverage_status("XL", fire_unv, calendar=syn)
    check(a["ok"] and not z["ok"] and z["unverified_fire"] == fire_unv and not z["lapse"],
          f"coverage: unverified next season fires EXACTLY at first_unverified - 60d ({fire_unv}), not a day earlier")
    check(any("S2" in u for u in z["unverified_entries"]), "coverage: the unverified entry is reported by name")
    l0 = sc.coverage_status("XL", fire_lapse - timedelta(days=1), calendar=syn)
    l1 = sc.coverage_status("XL", fire_lapse, calendar=syn)
    check(not l0["lapse"] and l1["lapse"] and l1["uncovered_fire"] == fire_lapse,
          f"coverage: an uncovered date (calendar expiry) becomes a LAPSE exactly 60d ahead ({fire_lapse})")
    check(sc.coverage_status("XL", D(2030, 6, 1), lookahead_days=200, calendar=syn)["ok"] is False
          and sc.coverage_status("XL", D(2030, 6, 1), lookahead_days=10, calendar=syn)["ok"] is True,
          "coverage: the look-ahead is honoured (injected horizon)")
    bad = {"XL": (syn["XL"][0], sc.SeasonEntry("XL", "S2", covers_from=D(2030, 11, 5),
                                               window_start=D(2031, 3, 1), window_end=D(2031, 10, 31),
                                               verified_through=D(2031, 10, 31), official={"x": "y"},
                                               retrieved=None))}
    probs = sc.validate_calendar(bad)
    check(any("gap" in p for p in probs) and any("no retrieval date" in p for p in probs)
          and any("no source URL" in p for p in probs),
          f"validate_calendar flags coverage gaps, missing retrieval date, verification without a source ({len(probs)} problems)")
    real = {s: sc.coverage_status(s, D(2026, 11, 1)) for s in su.GOVERNED_SPORTS}
    check(not real["WNBA"]["ok"] and all(real[s]["ok"] for s in ("NBA", "MLB", "NFL", "NCAAF"))
          and not any(r["lapse"] for r in real.values()),
          "real calendar on 2026-11-01: only WNBA (2027 unpublished) is unverified in the 60d horizon; no lapse")

    # ---- Eastern boundary ------------------------------------------------------------------------
    check(timeutils.event_eastern_date("2026-11-09T01:00:00Z") == date(2026, 11, 8),
          "event_eastern_date: 2026-11-09T01:00Z -> 2026-11-08 Eastern (previous Eastern date)")
    check(timeutils.event_eastern_date("2026-11-08") == date(2026, 11, 8)
          and timeutils.event_eastern_date("") is None and timeutils.event_eastern_date("nan") is None,
          "event_eastern_date: naive dates are already-Eastern; blanks -> None")

    def c_boundary(b):
        _write(b / "data/schedules/MLB_Schedule.csv", ["commence_time", "Away", "Home"],
               [["2026-11-16T01:00:00Z", "A", "H"]])  # 8pm ET Nov 15 = last day of [Nov 8, Nov 15]
        st = state(b, "MLB")
        check(st.state == su.ACTIVE, f"01:00 UTC Nov 16 game counts on Nov 15 Eastern -> inside the 7d window -> ACTIVE ({st.detail})")
    case(c_boundary)

    def c_boundary_out(b):
        _write(b / "data/schedules/MLB_Schedule.csv", ["commence_time", "Away", "Home"],
               [["2026-11-16T06:00:00Z", "A", "H"]])  # 1am ET Nov 16 -> outside the window
        st = state(b, "MLB")
        check(st.state == su.OFF_SEASON, "06:00 UTC Nov 16 game is Nov 16 Eastern -> outside the window -> OFF_SEASON")
    case(c_boundary_out)

    # ---- mtime-keyed memo (app.py request path) -------------------------------------------------
    def c_memo(b):
        p = b / "data/schedules/MLB_Schedule.csv"
        schedule(b, "MLB", [-10])
        first = state(b, "MLB").state
        schedule(b, "MLB", [2])
        st = os.stat(p)
        os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
        second = state(b, "MLB").state
        check(first == su.OFF_SEASON and second == su.ACTIVE,
              "memo is keyed by file mtime/size: a rewritten schedule is re-read (OFF_SEASON -> ACTIVE)")
    case(c_memo)

    # ---- prod-shaped fixture ---------------------------------------------------------------------
    def c_prod(b):
        prod_fixture(b)
        states = su.season_states(today=TODAY, base_dir=b)
        want = {"NFL": su.ACTIVE, "NCAAF": su.ACTIVE, "NBA": su.ACTIVE,
                "MLB": su.OFF_SEASON, "WNBA": su.OFF_SEASON}
        got = {s: st.state for s, st in states.items()}
        check(got == want, f"prod-shaped fixture states: {got}")
        for s, st in states.items():
            print(f"       {s}: {st.state} -- {st.reason}")
        check(su.active_sports(today=TODAY, base_dir=b) == {"NFL", "NCAAF", "NBA"},
              "active_sports() (SKIP-vs-FAIL callers + app.py) = {NFL, NCAAF, NBA}")

        rec = Recorder()
        steps, lines, outcomes, failed, out = run_ops(states, rec)
        ran = {lbl for lbl, _ in rec.calls}
        cmds = [" ".join(c) for _, c in rec.calls]
        leaked = [l for l in MLB_ONLY + WNBA_ONLY if l in ran]
        check(not leaked, f"OFF_SEASON MLB/WNBA: ZERO executions of their steps (leaked: {leaked or 'none'})")
        provider_scripts = ("refresh_mlb_daily", "fetch_mlb_lineups", "fetch_wnba_game_lines",
                            "fetch_wnba_player_props", "refresh_wnba_player_logs", "refresh_mlb_featured",
                            "refresh_wnba_featured", "calibrate_wnba")
        hits = [c for c in cmds if any(p in c for p in provider_scripts)]
        check(not hits, "no recorded command invokes an MLB/WNBA fetch/refresh script")
        skip_lines = [ln for ln in out.splitlines() if ln.startswith("[SKIP (off-season: ")]
        check(any(ln.endswith("] MLB daily refresh") for ln in skip_lines)
              and any(ln.endswith("] WNBA player props") for ln in skip_lines),
              f"visible '[SKIP (off-season: <reason>)] <label>' lines ({len(skip_lines)} printed)")
        sk = {o["label"]: o for o in outcomes if o["status"] == "SKIP (off-season)"}
        check(set(MLB_ONLY + WNBA_ONLY) <= set(sk) and all(o.get("reason") for o in sk.values()),
              "each skipped step records a SKIP (off-season) outcome with its reason")
        check("NBA daily refresh" in ran, "ACTIVE NBA: 'NBA daily refresh' executed")
        arch = [c for lbl, c in rec.calls if lbl == "WNBA candidate archive"]
        check(bool(arch) and arch[0][arch[0].index("--sports") + 1] == "nba",
              "multi-sport WNBA-block archive still runs, narrowed to --sports nba (NBA archiving not starved)")
        check("Football player props" in ran and "NFL first-half lines" in ran and "Power ratings" in ran,
              "football + cross-sport steps run unchanged")
        check(not failed and not any(o["status"] == "FAIL" for o in outcomes),
              "prod-shaped run: no FAIL outcomes (no empty-slice failures from off-season sports)")
        check("NFL preseason lines" not in ran
              and any(o["label"] == "NFL preseason lines" and o["status"] == "SKIP (out of preseason window)"
                      for o in outcomes),
              "NFL preseason pre-skip unchanged (Nov: SKIP (out of preseason window), not run)")
    case(c_prod)

    # ---- ACTIVE / UNKNOWN run; failures stay real ----------------------------------------------
    def c_active_all(b):
        for s, offs in (("MLB", [1]), ("WNBA", [1]), ("NBA", [1]), ("NFL", [1]), ("NCAAF", [1])):
            schedule(b, s, offs)
        states = su.season_states(today=TODAY, base_dir=b)
        rec = Recorder()
        _, _, outcomes, _, _ = run_ops(states, rec)
        ran = {lbl for lbl, _ in rec.calls}
        check(set(MLB_ONLY + WNBA_ONLY) <= ran, "all ACTIVE: every MLB/WNBA step executes")
        arch = [c for lbl, c in rec.calls if lbl == "WNBA candidate archive"]
        check(bool(arch) and arch[0][arch[0].index("--sports") + 1] == "wnba,nba,mlb",
              "all ACTIVE: archive --sports argument untouched")
    case(c_active_all)

    def c_unknown_runs(b):
        prod_fixture(b)
        for rel in ("data/schedules/MLB_Schedule.csv", "data/schedules/MLB_Odds.csv", "data/odds/MLB_Odds.csv"):
            (b / rel).unlink()
        states = su.season_states(today=TODAY, base_dir=b)
        check(states["MLB"].state == su.UNKNOWN, "MLB schedule removed -> UNKNOWN")
        rec = Recorder(fail_labels={"MLB daily refresh"})
        _, _, outcomes, failed, _ = run_ops(states, rec)
        ran = {lbl for lbl, _ in rec.calls}
        check(set(MLB_ONLY) <= ran, "UNKNOWN MLB: steps RUN (fail-open; refresh attempted)")
        st = next(o["status"] for o in outcomes if o["label"] == "MLB daily refresh")
        check(st == "FAIL" and failed, "UNKNOWN MLB failure is a real FAIL (never relabelled SKIP)")
        check(not (set(WNBA_ONLY) & ran), "WNBA (still OFF_SEASON) remains un-run alongside")
    case(c_unknown_runs)

    def c_continue(b):
        prod_fixture(b)
        states = su.season_states(today=TODAY, base_dir=b)
        rec = Recorder(fail_labels={"All-sport injuries"})
        _, _, outcomes, failed, _ = run_ops(states, rec, continue_on_error=False)
        check(failed and rec.calls[-1][0] == "All-sport injuries",
              "without --continue-on-error the operator stops at the first FAIL")
        rec2 = Recorder(fail_labels={"All-sport injuries"})
        _, _, outcomes2, failed2, _ = run_ops(states, rec2, continue_on_error=True)
        check(failed2 and "Power ratings" in {l for l, _ in rec2.calls},
              "with --continue-on-error later steps still run after a FAIL")
    case(c_continue)

    def c_preseason_open(b):
        prod_fixture(b)
        states = su.season_states(today=TODAY, base_dir=b)
        rec = Recorder()
        run_ops(states, rec, preseason_open=True)
        check("NFL preseason lines" in {l for l, _ in rec.calls}, "preseason window open -> 'NFL preseason lines' runs")
    case(c_preseason_open)

    def c_football_not_pregated(b):
        schedule(b, "NFL", [-60], today=date(2026, 4, 1)); odds(b, "NFL", [-60], today=date(2026, 4, 1))
        states = su.season_states(today=date(2026, 4, 1), base_dir=b)
        check(states["NFL"].state == su.OFF_SEASON, "NFL in April with a frozen February schedule -> OFF_SEASON")
        rec = Recorder(fail_labels={"NFL current rosters"})
        _, _, outcomes, failed, _ = run_ops(states, rec)
        check("NFL current rosters" in {l for l, _ in rec.calls},
              "football steps are NOT pre-gated (still run off-season, as before)")
        st = next(o["status"] for o in outcomes if o["label"] == "NFL current rosters")
        check(st == "SKIP (off-season)", "... and an OFF_SEASON football failure keeps the post-hoc SKIP relabel")
    case(c_football_not_pregated)

    # ---- the other callers share the governed state --------------------------------------------
    import inspect
    import run_all_scorecards
    import run_bk_edge_engine_pipeline
    check(run_all_scorecards.active_sports is su.active_sports
          and run_bk_edge_engine_pipeline.active_sports is su.active_sports,
          "run_all_scorecards + run_bk_edge_engine_pipeline use season_utils.active_sports (governed)")
    src = Path(__file__).resolve().parent.joinpath("run_prelaunch_scorecard.py").read_text(encoding="utf-8")
    body = src.split("def _active_sports", 1)[1].split("\ndef ", 1)[0]
    check("season_utils import active_sports" in body and "_Props.csv" not in body,
          "run_prelaunch_scorecard._active_sports delegates to the governed state (no private props copy)")
    gate_src = inspect.getsource(su.season_state)
    check("_Props" not in gate_src and "props" not in gate_src.split('"""')[-1].lower(),
          "season_state() body never reads a props file")

    n_fail = sum(1 for ok, _ in RESULTS if not ok)
    print()
    print(f"Season activation QC: {len(RESULTS) - n_fail} ok, {n_fail} FAIL")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
