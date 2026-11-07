"""QC: governed NBA no-game result (2026-11, Gap 1 of the NBA game-lines v3 correction).

Proves:
  (1) run_outcomes vocabulary: NO_GAMES_SCHEDULED / REUSED_FRESH benign; SCHEDULE_UNAVAILABLE /
      SKIPPED_LOCKED alerting; an UNKNOWN outcome string is alerting (fail closed).
  (2) the schedule authority audit result is encoded: no authoritative independent NBA schedule source is
      registered, so the verdict is always SCHEDULE_UNAVAILABLE; the governed service date is the EASTERN
      calendar date (a UTC 01:30 instant is still "yesterday" in ET); a naive instant is refused.
  (3) an empty NBA provider response is NEVER a benign no-game result: fetch_game_lines records
      SCHEDULE_UNAVAILABLE (exit 1), files byte-identical, the schedule verdict consulted BEFORE the provider
      call and stored in the receipt; NO_GAMES_SCHEDULED is never emitted. WNBA scope unchanged.
  (4) refresh_nba_daily records SCHEDULE_UNAVAILABLE for that receipt (no VALIDATION_FAILED mislabel),
      degrades, and skips lines-dependent steps; an OLD receipt never classifies a new run.
  (5) line-movement classification: SCHEDULE_UNAVAILABLE -> FAILED; receipt-proven NO_GAMES_SCHEDULED ->
      benign skip; exit 0 with a fresh non-UPDATED receipt -> FAILED (never OK).

OFFLINE: stub provider, temp dirs, faked subprocesses; the publisher lock path is pointed at a temp dir.
No network, no credits, no real data file read or written. Exit 0 on pass, 1 otherwise.
"""
from __future__ import annotations

import sys as _qc_sys  # noqa: E402
from pathlib import Path as _QcPath  # noqa: E402
_qc_sys.path.insert(0, str(_QcPath(__file__).resolve().parent))  # noqa: E402
from services.qc_runtime import isolate_runtime as _isolate_runtime  # noqa: E402
_isolate_runtime()  # per-run temp BK_RUNTIME_DIR: a QC never resolves the production runtime

import contextlib
import hashlib
import io
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

FAILS: list[str] = []
NOTES: list[str] = []
_LOCK_TMP = tempfile.TemporaryDirectory(prefix="qc_nba_no_game_lock_")
os.environ["BK_NBA_LINES_LOCK_PATH"] = str(Path(_LOCK_TMP.name) / "nba_game_lines.lock")


def check(cond, msg):
    (NOTES if cond else FAILS).append(msg)


def _sha(p):
    try:
        return hashlib.sha256(Path(p).read_bytes()).hexdigest()
    except OSError:
        return None


class _Fake:
    def __init__(self, code):
        self.returncode = code


def qc_vocabulary():
    from services import run_outcomes as ro
    check(not ro.is_alerting(ro.NO_GAMES_SCHEDULED) and not ro.is_alerting(ro.REUSED_FRESH),
          "NO_GAMES_SCHEDULED and REUSED_FRESH are benign")
    check(ro.is_alerting(ro.SCHEDULE_UNAVAILABLE) and ro.is_alerting(ro.SKIPPED_LOCKED),
          "SCHEDULE_UNAVAILABLE and SKIPPED_LOCKED are alerting")
    check(ro.is_alerting("SOME_UNCLASSIFIED_OUTCOME") and ro.is_alerting(""),
          "an unknown / empty outcome string is alerting (fail closed)")
    check(not (ro.BENIGN & ro.ALERTING), "BENIGN and ALERTING are disjoint")
    check(ro.BENIGN_LINES_NONPUBLISH == frozenset({ro.NO_GAMES_SCHEDULED})
          and ro.NO_ACTIVE_EVENTS not in ro.BENIGN_LINES_NONPUBLISH
          and ro.SCHEDULE_UNAVAILABLE not in ro.BENIGN_LINES_NONPUBLISH,
          "benign lines non-publish = {NO_GAMES_SCHEDULED} (governed-only); NO_ACTIVE_EVENTS + SCHEDULE_UNAVAILABLE excluded")
    check(ro.GOVERNED_SCHEDULE_CONTRACTS == {} and not ro.governed_lines_nonpublish(
              {"outcome": ro.NO_GAMES_SCHEDULED, "schedule_contract": "anything"}),
          "no schedule contract is governed, so no lines no-game claim is benign on this branch")
    _, degraded = ro.aggregate_parent({"game_lines": ro.SCHEDULE_UNAVAILABLE})
    check(degraded, "a SCHEDULE_UNAVAILABLE child degrades its parent")


def qc_authority():
    from services import nba_schedule_authority as sa
    from services.run_outcomes import SCHEDULE_UNAVAILABLE, VALIDATION_FAILED
    check(sa.AUTHORITATIVE_SOURCES == (), "audit: no authoritative independent NBA schedule source is registered")
    rejected = {name for name, _ in sa.REJECTED_SOURCES}
    check({"data/schedules/NBA_Schedule.csv", "data/odds/NBA_Odds.csv", "app.load_schedule",
           "fetch_schedule.py", "odds_api:/events"} <= rejected,
          "circular / gated / same-provider sources are explicitly rejected as authority")
    v = sa.schedule_verdict(now=datetime(2026, 11, 4, 1, 30, tzinfo=timezone.utc))
    check(v["status"] == SCHEDULE_UNAVAILABLE and v["reason_code"] == "NO_AUTHORITATIVE_SOURCE"
          and v["source"] is None, f"verdict without a source is SCHEDULE_UNAVAILABLE ({v['status']})")
    check(v["service_date"] == "2026-11-03",
          f"governed service date is Eastern: 2026-11-04T01:30Z -> {v['service_date']} (8:30pm ET Nov 3)")
    check(sa.governed_service_date(datetime(2026, 3, 8, 6, 59, tzinfo=timezone.utc)) == "2026-03-08"
          and sa.governed_service_date(datetime(2026, 3, 8, 4, 59, tzinfo=timezone.utc)) == "2026-03-07",
          "service date is DST-aware around the spring-forward night")
    try:
        sa.governed_service_date(datetime(2026, 11, 4, 1, 30))
        refused = False
    except ValueError:
        refused = True
    check(refused, "a naive instant is refused for the service date (never the ambient zone)")
    check(sa.zero_event_outcome(v) == (SCHEDULE_UNAVAILABLE, "NO_AUTHORITATIVE_SOURCE"),
          "provider zero + unavailable schedule -> SCHEDULE_UNAVAILABLE")
    check(sa.zero_event_outcome({"status": sa.GAMES_SCHEDULED})[0] == VALIDATION_FAILED,
          "provider zero + schedule expects games -> fail closed (VALIDATION_FAILED)")
    for verdict in ({"status": "NO_GAMES_SCHEDULED", "reason_code": "x"}, None, {}):
        check(sa.zero_event_outcome(verdict)[0] != "NO_GAMES_SCHEDULED",
              f"post-provider classification never emits NO_GAMES_SCHEDULED (verdict={verdict})")
    check("NO_GAMES_SCHEDULED" not in _code_tokens(sa.__file__),
          "the authority module has no code path that references NO_GAMES_SCHEDULED (docstrings aside)")


def _code_tokens(path):
    """Names + non-docstring string constants used in a module's CODE (docstrings excluded)."""
    import ast
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    docs = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body \
                and isinstance(node.body[0], ast.Expr) and isinstance(getattr(node.body[0], "value", None), ast.Constant):
            docs.add(id(node.body[0].value))
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            out.add(node.id)
        elif isinstance(node, ast.alias):
            out.add(node.name)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs:
            out.add(node.value)
    return out


def _event(eid, commence):
    lu = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    home, away = f"Home {eid}", f"Away {eid}"
    return {"id": eid, "commence_time": commence, "home_team": home, "away_team": away, "bookmakers": [
        {"key": "draftkings", "title": "DraftKings", "last_update": lu, "markets": [
            {"key": "h2h", "outcomes": [{"name": home, "price": -140}, {"name": away, "price": 120}]}]}]}


def _run_fetch(fg, base, sport, payload, order):
    out = {k: base / f"{sport}_{k}.csv" for k in ("odds", "sched", "alias")}
    import services.nba_schedule_authority as sa
    real_verdict = sa.schedule_verdict

    def fake_get_json(url):
        order.append("provider")
        return payload

    def spy_verdict(*a, **k):
        order.append("schedule_verdict")
        return real_verdict(*a, **k)

    def no_network(*a, **k):
        raise RuntimeError("network disabled in QC")

    saved = (fg.BASE_DIR, fg.get_json, fg.urlopen, fg._QUOTA.print_receipt, list(sys.argv), sa.schedule_verdict)
    fg.BASE_DIR, fg.get_json, fg.urlopen = base, fake_get_json, no_network
    fg._QUOTA.print_receipt = lambda **k: (True, {})
    sa.schedule_verdict = spy_verdict
    sys.argv = ["fetch_game_lines.py", "--api-key", "qc-offline", "--sport", sport,
                "--bookmakers", "draftkings", "--output", str(out["odds"]),
                "--schedules-output", str(out["sched"]), "--schedule-alias-output", str(out["alias"]),
                "--skip-line-movement"]
    try:
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            rc = fg.main()
    finally:
        fg.BASE_DIR, fg.get_json, fg.urlopen, fg._QUOTA.print_receipt = saved[0], saved[1], saved[2], saved[3]
        sys.argv[:] = saved[4]
        sa.schedule_verdict = saved[5]
    rp = base / "data" / "tracking" / f"_last_game_lines_fetch_{sport}.json"
    receipt = json.loads(rp.read_text(encoding="utf-8")) if rp.exists() else {}
    return rc, out, receipt, buf.getvalue()


def qc_fetcher():
    import fetch_game_lines as fg
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        fut = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        order: list[str] = []
        rc0, out, rec0, _ = _run_fetch(fg, base, "basketball_nba", [_event("g1", fut)], order)
        check(rc0 == 0 and rec0.get("outcome") == "UPDATED", f"setup: an NBA slate publishes ({rec0.get('outcome')})")
        before = {k: _sha(p) for k, p in out.items()}
        order.clear()
        rc, out, rec, text = _run_fetch(fg, base, "basketball_nba", [], order)
        check(rc == 1 and rec.get("outcome") == "SCHEDULE_UNAVAILABLE" and rec.get("published") is False,
              f"NBA provider returned zero events -> exit 1, receipt SCHEDULE_UNAVAILABLE ({rec.get('outcome')})")
        check({k: _sha(p) for k, p in out.items()} == before,
              "SCHEDULE_UNAVAILABLE leaves all three NBA lines files byte-identical (no stale rewrite, no wipe)")
        check(order[:2] == ["schedule_verdict", "provider"],
              f"the schedule verdict is consulted BEFORE the provider call (order={order})")
        sv = rec.get("schedule_verdict") or {}
        check(sv.get("status") == "SCHEDULE_UNAVAILABLE" and sv.get("reason_code") == "NO_AUTHORITATIVE_SOURCE",
              "receipt records the schedule verdict (SCHEDULE_UNAVAILABLE / NO_AUTHORITATIVE_SOURCE)")
        check("NO_ACTIVE_EVENTS" not in json.dumps(rec) and "NO_GAMES_SCHEDULED" not in json.dumps(rec),
              "an empty NBA answer is never recorded as NO_ACTIVE_EVENTS or NO_GAMES_SCHEDULED")
        check("NOT a benign skip" in text, "operator output says the empty answer is not a benign skip")
        check("NO_GAMES_SCHEDULED" not in _code_tokens(fg.__file__),
              "fetch_game_lines has no NO_GAMES_SCHEDULED path (no authoritative source exists)")
        order.clear()
        rcw, _, recw, _ = _run_fetch(fg, base, "basketball_wnba", [], order)
        check(rcw == 1 and recw.get("outcome") == "NO_ACTIVE_EVENTS" and "schedule_verdict" not in order,
              "scope: WNBA (not event-aware) keeps NO_ACTIVE_EVENTS and never consults the NBA schedule authority")


def qc_nba_daily():
    import refresh_nba_daily as nba

    from services.qc_run_receipts import lines_receipt, props_receipt, receipt_sandbox

    def drive(lines_rc, receipt_outcome, pre_existing=None, write_own=True):
        with tempfile.TemporaryDirectory() as td, receipt_sandbox():
            base = Path(td)
            (base / "data/tracking").mkdir(parents=True)
            (base / "data/props").mkdir(parents=True)
            rp = base / "data/tracking/_last_game_lines_fetch_basketball_nba.json"
            if pre_existing:
                rp.write_text(json.dumps({"outcome": pre_existing, "exit_code": 1}), encoding="utf-8")
                old = time.time() - 3600
                os.utime(rp, (old, old))
            saved = (nba.BASE_DIR, nba.PROPS_ARTIFACT, nba.subprocess.run)
            ran = []

            def fake_run(command, timeout=None, env=None, **kw):
                joined = " ".join(map(str, command))
                label = next(l for l, c, _ in nba.STEPS if next(x for x in c if str(x).endswith(".py")) in joined)
                ran.append(label)
                if label == "game_lines":
                    if receipt_outcome:
                        rp.write_text(json.dumps({"outcome": receipt_outcome, "exit_code": lines_rc}), encoding="utf-8")
                    if write_own:   # the publisher's own per-run receipt, via the REAL fetch-outcome mapping
                        lines_receipt(env, base, lines_rc, wrote_fetch_receipt=bool(receipt_outcome))
                    return _Fake(lines_rc)
                if label == "player_props":
                    (base / "data/tracking/_last_props_fetch_basketball_nba.json").write_text(
                        json.dumps({"events_found": 0}), encoding="utf-8")
                    props_receipt(env, base, 1, base / "data/props/NBA_Props.csv", advanced=False)
                    return _Fake(1)
                return _Fake(0)

            nba.BASE_DIR, nba.PROPS_ARTIFACT = base, base / "data/props/NBA_Props.csv"
            nba.subprocess.run = fake_run
            try:
                with contextlib.redirect_stdout(io.StringIO()) as buf:
                    rc = nba.main()
            finally:
                nba.BASE_DIR, nba.PROPS_ARTIFACT, nba.subprocess.run = saved
            side = json.loads((base / "data/tracking/_child_outcomes_nba_daily.json").read_text(encoding="utf-8"))
            return rc, ran, side.get("outcomes", {}), side.get("degraded"), buf.getvalue()

    rc, ran, outs, degraded, text = drive(1, "SCHEDULE_UNAVAILABLE")
    check(outs.get("game_lines") == "SCHEDULE_UNAVAILABLE" and rc != 0 and degraded
          and "player_props" not in ran and outs.get("player_props") == "SKIPPED_BLOCKED_BY_LINES",
          f"nba_daily: SCHEDULE_UNAVAILABLE recorded as such (not VALIDATION_FAILED), DEGRADED, props skipped ({outs.get('game_lines')})")
    check("[OK]" not in text and "[PASS] game_lines" not in text, "nba_daily never prints PASS/OK for the empty answer")
    rc, ran, outs, degraded, _ = drive(1, None, pre_existing="NO_ACTIVE_EVENTS")
    check(outs.get("game_lines") == "VALIDATION_FAILED" and rc != 0,
          "nba_daily: an OLD receipt cannot classify this run's failure (no fresh proof -> VALIDATION_FAILED)")
    rc, ran, outs, degraded, _ = drive(1, "NO_ACTIVE_EVENTS", write_own=False)
    check(outs.get("game_lines") == "RUN_RECEIPT_MISSING" and rc != 0 and degraded,
          "nba_daily: a shared/tokenless fetch receipt without this run's OWN receipt -> RUN_RECEIPT_MISSING "
          f"(never adopted) ({outs.get('game_lines')})")
    rc, ran, outs, degraded, _ = drive(1, "NO_ACTIVE_EVENTS")
    check(outs.get("game_lines") == "SCHEDULE_UNAVAILABLE",
          "nba_daily: a fresh NBA NO_ACTIVE_EVENTS receipt is treated as SCHEDULE_UNAVAILABLE, never benign")
    rc, ran, outs, degraded, _ = drive(0, "VALIDATION_FAILED")
    check(outs.get("game_lines") == "VALIDATION_FAILED" and rc != 0,
          "nba_daily: exit 0 with a fresh non-UPDATED receipt is not success")
    rc, ran, outs, degraded, _ = drive(0, "UPDATED")
    check(rc == 0 and outs.get("game_lines") == "UPDATED" and "player_props" in ran,
          "nba_daily: exit 0 + fresh UPDATED receipt -> UPDATED, full chain")


def qc_line_movement():
    import refresh_line_movement_snapshots as lm
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        (base / "data/tracking").mkdir(parents=True)
        saved = (lm.BASE_DIR, lm.subprocess.run)

        def drive(plan):
            def fake_run(command, cwd=None, timeout=None, env=None, **kw):
                joined = " ".join(map(str, command))
                sport = "baseball_mlb" if "mlb" in joined else "basketball_wnba"
                rc, outcome = plan[sport]
                if outcome:
                    (base / "data/tracking" / f"_last_game_lines_fetch_{sport}.json").write_text(
                        json.dumps({"outcome": outcome, "exit_code": rc,
                                    # the child stamps the runner's run token (identity, never mtime)
                                    "stage_run_id": (env or {}).get("BK_NBA_STAGE_RUN_ID")}),
                        encoding="utf-8")
                return _Fake(rc)
            lm.BASE_DIR, lm.subprocess.run = base, fake_run
            try:
                with contextlib.redirect_stdout(io.StringIO()) as buf:
                    rc = lm.main()
            finally:
                lm.BASE_DIR, lm.subprocess.run = saved
            return rc, buf.getvalue()

        rc, text = drive({"baseball_mlb": (1, "SCHEDULE_UNAVAILABLE"), "basketball_wnba": (0, "UPDATED")})
        check(rc == 1 and "outcome=SCHEDULE_UNAVAILABLE" in text and "All line-movement snapshots captured" not in text,
              "line-movement: SCHEDULE_UNAVAILABLE -> FAILED, never 'All ... captured'")
        rc, text = drive({"baseball_mlb": (1, "NO_GAMES_SCHEDULED"), "basketball_wnba": (0, "UPDATED")})
        check(rc == 1 and "SKIPPED (benign)" not in text,
              "line-movement: an UNGOVERNED NO_GAMES_SCHEDULED receipt -> FAILED (governed-only rule)")
        rc, text = drive({"baseball_mlb": (0, "VALIDATION_FAILED"), "basketball_wnba": (0, "UPDATED")})
        check(rc == 1 and "All line-movement snapshots captured" not in text,
              "line-movement: exit 0 with a fresh VALIDATION_FAILED receipt -> FAILED, never OK")


def qc_timer_blocker():
    """The proposed 4h NBA market orchestrator timer (v5: one timer for lines then props) stays a proposal:
    :15 past every fourth UTC hour, and the TIMER-ENABLEMENT BLOCKER (no independent schedule source ->
    SCHEDULE_UNAVAILABLE, never a fabricated NO_GAMES_SCHEDULED) is written into both unit headers and the
    contract doc."""
    here = Path(__file__).resolve().parent
    timer = (here / "ops" / "bk-nba-market-refresh.timer").read_text(encoding="utf-8")
    service = (here / "ops" / "bk-nba-market-refresh.service").read_text(encoding="utf-8")
    doc = (here / "docs" / "game_lines_event_contract.md").read_text(encoding="utf-8")
    cal = [l.strip() for l in timer.splitlines() if l.strip().startswith("OnCalendar=")]
    check(cal == ["OnCalendar=*-*-* 00/4:15:00"], f"timer fires at :15 past every fourth UTC hour ({cal})")
    for name, text in (("timer", timer), ("service", service), ("contract doc", doc)):
        check("TIMER-ENABLEMENT BLOCKER" in text and "SCHEDULE_UNAVAILABLE" in text and "NO_GAMES_SCHEDULED" in text,
              f"{name} carries the TIMER-ENABLEMENT BLOCKER (fail closed, never a fabricated no-game result)")


def main() -> int:
    for fn in (qc_vocabulary, qc_authority, qc_fetcher, qc_nba_daily, qc_line_movement, qc_timer_blocker):
        try:
            fn()
        except Exception as exc:  # a crash is a failure, never a pass
            import traceback
            FAILS.append(f"{fn.__name__} crashed: {exc!r}\n{traceback.format_exc()}")
    print("=" * 64)
    print("QC: GOVERNED NBA NO-GAME RESULT")
    print("=" * 64)
    for n in NOTES:
        print(f"[OK]   {n}")
    for f in FAILS:
        print(f"[FAIL] {f}")
    print(f"\n{len(NOTES)} passed, {len(FAILS)} failed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
