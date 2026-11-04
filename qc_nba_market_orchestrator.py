"""QC: NBA market orchestrator (v5) -- lines then props, ONE receipt, shared ensure API with bk-daily.

REAL processes: this file re-invoked as
  --stage-child  the production stage entry (fetch_game_lines.main / fetch_player_props.main -> the publishers,
                 real kernel locks) with a STUB provider at the HTTP boundary that appends "<stage> <pid>" to a
                 counter file per request (free /events included) and can hold the lock (sleep) or fail;
  --orch-child   services.nba_market.run_market_refresh (the orchestrator) whose stage children are the above;
  --daily-child  refresh_nba_daily.main (bk-daily) reduced to its two NBA market steps, same stage children.
Every child blocks all non-loopback network. Temp dirs only (BK_RUNTIME_DIR = a qc_* temp dir); the real
checkout's NBA data/receipts are asserted byte-identical at the end.

Proves:
  (1) ordering: lines stage completes before the props stage starts; ONE receipt (schema, both stages, exit
      codes, timings, credits, receipt hashes that match the files on disk), written atomically (no temp left).
  (2) lines failure -> props NOT attempted (SKIPPED_BLOCKED_BY_LINES), ZERO props requests, non-zero exit.
  (3) fresh lines + props -> both REUSED_FRESH, ZERO requests, exit 0.
  (4) lock contention followed by a valid receipt: bk-daily overlapping a running orchestrator ->
      REUSED_FRESH_AFTER_LOCK for lines, exactly one lines + one props request in total (no duplicate paid
      call), props file written once.
  (5) lock contention WITHOUT a valid receipt (holder failed) -> NO_FRESH_AFTER_LOCK, exit 1, zero own
      requests, never OK/PASS; props SKIPPED_BLOCKED_BY_LINES.
  (6) missed timer / no concurrent catch-up: timer Persistent=false; two concurrent orchestrators -> one does
      the work, the other SKIPPED_LOCKED (75) with ZERO requests and the shared receipt untouched by it.
  (7) stage timeout: an overrunning stage child is killed -> PROVIDER_ERROR / exit 124, the kernel releases
      the lock (the next run acquires and publishes).
  (8) timeout contract: one table, step timeouts == lock wait + exec budget, service TimeoutStartSec ==
      SERVICE_TIMEOUT_SECONDS, measured values recorded with their audit source.
  (9) shared API: bk-daily's two NBA steps ARE the canonical stage commands; ensure_* run them by default.
 (10) units: v4 bk-nba-lines.* / bk-nba-props.* and refresh_nba_lines.py are gone; the orchestrator units
      carry the TIMER-ENABLEMENT BLOCKER.
Exit 0 on pass, 1 otherwise.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
FAILS: list[str] = []
NOTES: list[str] = []
SKIPS: list[str] = []
PLAYERS = ("Qcmkt Alpha", "Qcmkt Bravo", "Qcmkt Charlie", "Qcmkt Delta", "Qcmkt Echo")
EVENT_ID, HOME, AWAY = "mktgame", "Home M", "Away M"


def check(cond, msg):
    (NOTES if cond else FAILS).append(msg)


# ------------------------------------------------------------------------------------------------ children
def _block_network():
    loop = ("127.0.0.1", "::1", "localhost")
    real_gai, real_connect = socket.getaddrinfo, socket.socket.connect

    def gai(host, *a, **k):
        if str(host) not in loop:
            raise OSError(f"network blocked in QC child: {host}")
        return real_gai(host, *a, **k)

    def connect(self, addr):
        host = addr[0] if isinstance(addr, tuple) else addr
        if str(host) not in loop:
            raise OSError(f"network blocked in QC child: {addr}")
        return real_connect(self, addr)
    socket.getaddrinfo, socket.socket.connect = gai, connect


def _commence():
    return (datetime.now(timezone.utc) + timedelta(hours=20)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _lines_payload():
    lu = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return [{"id": EVENT_ID, "commence_time": _commence(), "home_team": HOME, "away_team": AWAY,
             "bookmakers": [{"key": "draftkings", "title": "DraftKings", "last_update": lu, "markets": [
                 {"key": "h2h", "outcomes": [{"name": HOME, "price": -140}, {"name": AWAY, "price": 120}]}]}]}]


def _props_payload():
    lu = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    books = []
    for key, title in (("draftkings", "DraftKings"), ("fanduel", "FanDuel")):
        markets = []
        for mk, base in (("player_points", 20.5), ("player_rebounds", 6.5), ("player_assists", 4.5)):
            outs = []
            for i, p in enumerate(PLAYERS):
                outs += [{"name": "Over", "description": p, "price": -115, "point": base + i},
                         {"name": "Under", "description": p, "price": -105, "point": base + i}]
            markets.append({"key": mk, "last_update": lu, "outcomes": outs})
        books.append({"key": key, "title": title, "last_update": lu, "markets": markets})
    return {"id": EVENT_ID, "bookmakers": books}


def stage_child(argv) -> int:
    stage, base, counter, hold, stage_args = argv[0], Path(argv[1]), Path(argv[2]), float(argv[3]), argv[4:]
    _block_network()
    sys.path.insert(0, str(HERE))
    fail = os.environ.get("QC_STUB_FAIL_STAGE") == stage

    def record():
        with open(counter, "a", encoding="utf-8") as fh:
            fh.write(f"{stage} {os.getpid()}\n")
        time.sleep(hold)
        if fail:
            raise RuntimeError("qc stub provider error")

    no_net = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("network disabled in QC child"))  # noqa: E731
    if stage == "lines":
        import fetch_game_lines as fg

        def get_json(url):
            record()
            return _lines_payload()
        fg.BASE_DIR, fg.get_json, fg.urlopen = base, get_json, no_net
        fg._QUOTA.print_receipt = lambda **k: (True, {})
        fg.SPORT_OUTPUTS["basketball_nba"] = {
            "odds": base / "data" / "odds" / "NBA_Odds.csv",
            "schedules": base / "data" / "schedules" / "NBA_Odds.csv",
            "schedule_alias": base / "data" / "schedules" / "NBA_Schedule.csv"}
        return int(fg.main(list(stage_args) + ["--api-key", "qc-offline", "--skip-line-movement"]))
    import fetch_player_props as fp

    def get_json_p(url):
        record()
        return _props_payload() if "/odds" in url else [
            {"id": EVENT_ID, "commence_time": _commence(), "home_team": HOME, "away_team": AWAY}]
    fp.BASE_DIR, fp.get_json, fp.urlopen = base, get_json_p, no_net
    fp._QUOTA.print_receipt = lambda **k: (True, {})
    fp.SPORT_OUTPUTS["basketball_nba"] = base / "data" / "props" / "NBA_Props.csv"
    return int(fp.main(list(stage_args) + ["--api-key", "qc-offline"]))


def _stage_cmd(stage, caller, base, counter, hold):
    from services import nba_market
    canonical = nba_market.stage_command(stage, caller)
    return [sys.executable, str(Path(__file__).resolve()), "--stage-child", stage, str(base), str(counter),
            str(hold), *canonical[2:]]


def _holds(spec: str) -> dict:
    out = {"lines": 0.0, "props": 0.0}
    for part in filter(None, spec.split(",")):
        k, v = part.split("=")
        out[k] = float(v)
    return out


def orch_child(argv) -> int:
    base, counter, holds, receipt = Path(argv[0]), Path(argv[1]), _holds(argv[2]), Path(argv[3])
    _block_network()
    sys.path.insert(0, str(HERE))
    from services import nba_market
    caller = "qc_orchestrator"
    rc, rec = nba_market.run_market_refresh(
        base_dir=base, caller=caller, receipt_path=receipt,
        command_for=lambda s: _stage_cmd(s, caller, base, counter, holds[s]))
    print(f"ORCH rc={rc} result={rec.get('result')}", flush=True)
    return rc


def daily_child(argv) -> int:
    base, counter, holds = Path(argv[0]), Path(argv[1]), _holds(argv[2])
    _block_network()
    sys.path.insert(0, str(HERE))
    import refresh_nba_daily as nba
    from services import nba_market_budget as budget
    nba.BASE_DIR, nba.PROPS_ARTIFACT = base, base / "data" / "props" / "NBA_Props.csv"
    nba.STEPS = [("game_lines", _stage_cmd("lines", "nba_daily", base, counter, holds["lines"]),
                  budget.stage_timeout("lines")),
                 ("player_props", _stage_cmd("props", "nba_daily", base, counter, holds["props"]),
                  budget.stage_timeout("props"))]
    return int(nba.main())


# ------------------------------------------------------------------------------------------------ parent
def _sha(p: Path):
    try:
        return hashlib.sha256(Path(p).read_bytes()).hexdigest()
    except OSError:
        return None


def _calls(counter: Path, stage: str | None = None) -> int:
    try:
        lines = [l.split() for l in counter.read_text(encoding="utf-8").splitlines() if l.strip()]
    except OSError:
        return 0
    return len([l for l in lines if stage is None or l[0] == stage])


def _order(counter: Path) -> list[str]:
    try:
        return [l.split()[0] for l in counter.read_text(encoding="utf-8").splitlines() if l.strip()]
    except OSError:
        return []


def _wait_calls(counter, n, timeout=90.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if _calls(counter) >= n:
            return True
        time.sleep(0.05)
    return False


def _env(root: Path, extra=None) -> dict:
    env = dict(os.environ)
    for k in ("BK_NBA_LINES_LOCK_PATH", "BK_NBA_PROPS_LOCK_PATH", "BK_NBA_MARKET_LOCK_PATH"):
        env.pop(k, None)
    env["BK_RUNTIME_DIR"] = str(root / "rt")
    env["PYTHONIOENCODING"] = "utf-8"
    env.update(extra or {})
    return env


def _spawn(mode, root, *args, extra=None):
    return subprocess.Popen([sys.executable, "-X", "utf8", str(Path(__file__).resolve()), mode, *map(str, args)],
                            cwd=str(HERE), env=_env(root, extra), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace")


def _run(mode, root, *args, extra=None, timeout=300):
    p = _spawn(mode, root, *args, extra=extra)
    out, _ = p.communicate(timeout=timeout)
    return p.returncode, out


def _receipt(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _stages(rec):
    return {s["stage"]: s for s in rec.get("stages", [])}


def _never_ok(out: str) -> bool:
    return not any(t in out for t in ("[OK]", "[PASS] game_lines", "[UPDATED]", "[REUSED"))


@contextlib.contextmanager
def _workspace(prefix):
    with tempfile.TemporaryDirectory(prefix=f"qc_nba_market_{prefix}_") as td:
        root = Path(td)
        base = root / "base"
        for sub in ("data/odds", "data/schedules", "data/props", "data/tracking"):
            (base / sub).mkdir(parents=True)
        yield root, base, root / "counter.txt", root / "receipt" / "last_nba_market_refresh.json"


def qc_ordering_receipt_reuse():
    with _workspace("order") as (root, base, counter, receipt):
        rc, out = _run("--orch-child", root, base, counter, "lines=0.5,props=0.5", receipt)
        rec = _receipt(receipt)
        st = _stages(rec)
        lines, props = st.get("lines", {}), st.get("props", {})
        check(rc == 0 and rec.get("result") == "COMPLETE" and lines.get("outcome") == "UPDATED"
              and props.get("outcome") == "UPDATED", f"(1) orchestrator lines UPDATED then props UPDATED, exit 0 "
              f"(rc={rc}, {lines.get('outcome')}/{props.get('outcome')})" + ("" if rc == 0 else f" tail={out[-1500:]!r}"))
        order = _order(counter)
        check(order and order[0] == "lines" and "props" in order and order.index("props") > max(
            i for i, s in enumerate(order) if s == "lines"), f"(1) every lines request precedes every props request ({order})")
        check(bool(lines.get("ended_at_utc")) and bool(props.get("started_at_utc"))
              and lines["ended_at_utc"] <= props["started_at_utc"], "(1) lines stage ended before props stage started")
        need = {"schema", "run_id", "caller", "started_at_utc", "ended_at_utc", "seconds", "result", "exit_code",
                "stages", "timeouts"}
        stage_need = {"stage", "ran", "outcome", "exit_code", "detail", "started_at_utc", "ended_at_utc", "seconds",
                      "timeout_seconds", "lock_wait_seconds", "credits", "publisher_receipt", "fetch_receipt"}
        check(need <= set(rec) and rec.get("schema") == "nba_market_refresh_v1"
              and all(stage_need <= set(s) for s in rec.get("stages", [])) and len(rec.get("stages", [])) == 2,
              "(1) ONE receipt covers both stages: outcomes, exit codes, timings, credits, receipt hashes, timeouts")
        hashes_ok = all(s.get(k) and s[k]["sha256"] == _sha(base / s[k]["path"])
                        for s in (lines, props) for k in ("publisher_receipt", "fetch_receipt"))
        check(hashes_ok, "(1) every stage receipt hash in the orchestrator receipt matches the file on disk")
        check(not [p for p in receipt.parent.iterdir() if p.name != receipt.name],
              "(1) receipt written atomically (no temp file left beside it)")
        check(all(s["credits"].get("source") == "odds_quota_ledger" for s in (lines, props)),
              "(1) credits recorded per stage from the quota ledger (never guessed)")

        n = _calls(counter)
        rc2, out2 = _run("--orch-child", root, base, counter, "", receipt)
        st2 = _stages(_receipt(receipt))
        check(rc2 == 0 and st2.get("lines", {}).get("outcome") == "REUSED_FRESH"
              and st2.get("props", {}).get("outcome") == "REUSED_FRESH" and _calls(counter) == n,
              f"(3) fresh lines + props both reused: REUSED_FRESH x2, ZERO requests (rc={rc2})"
              + ("" if rc2 == 0 else f" tail={out2[-800:]!r}"))


def qc_lines_failure_blocks_props():
    with _workspace("linesfail") as (root, base, counter, receipt):
        rc, out = _run("--orch-child", root, base, counter, "", receipt, extra={"QC_STUB_FAIL_STAGE": "lines"})
        st = _stages(_receipt(receipt))
        props = st.get("props", {})
        check(rc != 0 and st.get("lines", {}).get("outcome") not in ("UPDATED", "REUSED_FRESH", "REUSED_FRESH_AFTER_LOCK")
              and props.get("ran") is False and props.get("outcome") == "SKIPPED_BLOCKED_BY_LINES"
              and _calls(counter, "props") == 0 and not (base / "data/props/NBA_Props.csv").exists(),
              f"(2) lines failure -> props NOT attempted, ZERO props requests, nothing written, exit {rc} "
              f"(lines {st.get('lines', {}).get('outcome')})")
        check(_receipt(receipt).get("result") == "FAILED_AT_LINES" and "[UPDATED]" not in out,
              "(2) receipt says FAILED_AT_LINES; never OK")


def qc_daily_overlaps_orchestrator():
    with _workspace("overlap") as (root, base, counter, receipt):
        a = _spawn("--orch-child", root, base, counter, "lines=8", receipt)
        check(_wait_calls(counter, 1), "(4) orchestrator holds the lines lock mid-request")
        d_rc, d_out = _run("--daily-child", root, base, counter, "")
        a_out, _ = a.communicate(timeout=300)
        side = json.loads((base / "data/tracking/_child_outcomes_nba_daily.json").read_text(encoding="utf-8"))
        outs = side.get("outcomes", {})
        check(a.returncode == 0 and d_rc == 0 and outs.get("game_lines") == "REUSED_FRESH_AFTER_LOCK"
              and outs.get("player_props") in ("UPDATED", "REUSED_FRESH", "REUSED_FRESH_AFTER_LOCK"),
              f"(4) contention + valid receipt: bk-daily lines REUSED_FRESH_AFTER_LOCK, props {outs.get('player_props')} "
              f"(orch rc={a.returncode}, daily rc={d_rc})" + ("" if d_rc == 0 else f" tail={d_out[-1500:]!r}"))
        check(_calls(counter, "lines") == 1 and _calls(counter, "props") == 2,
              f"(4) no duplicate paid call: 1 lines request, 1 props run (/events + /odds = 2) in total "
              f"(lines={_calls(counter, 'lines')}, props={_calls(counter, 'props')})")
        pf = _receipt(base / "data/tracking/_last_nba_props_fetch.json")
        check(pf.get("outcome") == "UPDATED" and pf.get("outputs", {}).get("props", {}).get("sha256_after")
              == _sha(base / "data/props/NBA_Props.csv"), "(4) props file written once and matches its single receipt")


def qc_contention_without_receipt():
    with _workspace("nofresh") as (root, base, counter, receipt):
        a = _spawn("--orch-child", root, base, counter, "lines=8", receipt, extra={"QC_STUB_FAIL_STAGE": "lines"})
        check(_wait_calls(counter, 1), "(5) failing orchestrator holds the lines lock")
        d_rc, d_out = _run("--daily-child", root, base, counter, "")
        a.communicate(timeout=300)
        side = json.loads((base / "data/tracking/_child_outcomes_nba_daily.json").read_text(encoding="utf-8"))
        outs = side.get("outcomes", {})
        check(d_rc != 0 and outs.get("game_lines") == "NO_FRESH_AFTER_LOCK"
              and outs.get("player_props") == "SKIPPED_BLOCKED_BY_LINES" and _calls(counter) == 1
              and _never_ok(d_out), f"(5) contention without a valid receipt: NO_FRESH_AFTER_LOCK, exit {d_rc}, zero own "
                                    f"requests, props skipped, never OK ({outs})")


def qc_concurrent_orchestrators():
    with _workspace("concurrent") as (root, base, counter, receipt):
        a = _spawn("--orch-child", root, base, counter, "lines=8", receipt)
        check(_wait_calls(counter, 1), "(6) orchestrator A is running (lines request in flight)")
        receipt_b = root / "receipt_b" / "last.json"
        b_rc, b_out = _run("--orch-child", root, base, counter, "", receipt_b)
        a_alive = a.poll() is None
        n_while = _calls(counter)
        a_out, _ = a.communicate(timeout=300)
        check(b_rc == 75 and "[SKIPPED_LOCKED]" in b_out and n_while == 1 and a_alive and not receipt_b.exists(),
              f"(6) second concurrent orchestrator: SKIPPED_LOCKED exit {b_rc}, ZERO requests, wrote no receipt "
              f"(A still running: {a_alive})" + ("" if b_rc == 75 else f" tail={b_out[-800:]!r}"))
        rec = _receipt(receipt)
        check(a.returncode == 0 and rec.get("caller") == "qc_orchestrator" and rec.get("result") == "COMPLETE",
              f"(6) the running orchestrator did the work alone and owns the one receipt (rc={a.returncode})")


def qc_stage_timeout():
    sys.path.insert(0, str(HERE))
    from services import nba_market
    with _workspace("timeout") as (root, base, counter, receipt):
        saved = os.environ.get("BK_RUNTIME_DIR")
        os.environ["BK_RUNTIME_DIR"] = str(root / "rt")
        try:
            st = nba_market.ensure_nba_lines("qc_timeout", base_dir=base, timeout=4,
                                             command=_stage_cmd("lines", "qc_timeout", base, counter, 60))
        finally:
            if saved is None:
                os.environ.pop("BK_RUNTIME_DIR", None)
            else:
                os.environ["BK_RUNTIME_DIR"] = saved
        check(st["timed_out"] and st["outcome"] == "PROVIDER_ERROR" and st["exit_code"] == 124
              and not (base / "data/odds/NBA_Odds.csv").exists(),
              f"(7) an overrunning stage is killed at its timeout: PROVIDER_ERROR exit 124, nothing published")
        rc, out = _run("--orch-child", root, base, counter, "", receipt)
        check(rc == 0, f"(7) the killed stage left no stale lock: the next run acquired and published (rc={rc})"
              + ("" if rc == 0 else f" tail={out[-800:]!r}"))


def qc_timeout_contract():
    from services import nba_market_budget as b
    import refresh_nba_daily as nba
    steps = {l: t for l, _, t in nba.STEPS}
    step_t = {"lines": steps.get("game_lines"), "props": steps.get("player_props")}
    check(b.invariant_violations(step_t) == [], f"(8) invariant step_timeout >= lock_wait + exec_budget holds "
                                                f"({b.invariant_violations(step_t)})")
    for stage in ("lines", "props"):
        check(step_t[stage] >= b.LOCK_WAIT_SECONDS + b.execution_seconds(stage),
              f"(8) bk-daily {stage} step timeout {step_t[stage]} >= lock wait {b.LOCK_WAIT_SECONDS} + exec "
              f"{b.execution_seconds(stage)}")
    check((b.LOCK_WAIT_SECONDS, b.LINES_EXECUTION_SECONDS, b.PROPS_EXECUTION_SECONDS, b.LINES_STAGE_TIMEOUT,
           b.PROPS_STAGE_TIMEOUT, b.SERVICE_TIMEOUT_SECONDS) == (30, 30, 60, 60, 90, 180),
          "(8) measured contract: wait 30 / lines 30 / props 60 -> steps 60 / 90, service 180")
    check(b.PROVISIONAL is False and b.AUDIT["audit_date"] == "2026-11-04" and b.AUDIT.get("owner_approved") == "2026-11-04" and b.AUDIT["lines"]["n"] == 40
          and b.AUDIT["props"]["max"] == 2.8 and all(b.execution_seconds(s) >= b.AUDIT[s]["max"] for s in ("lines", "props")),
          "(8) values carry their audit source (n, p95, max, 2026-11-04) and exceed the observed max")
    service = (HERE / "ops" / "bk-nba-market-refresh.service").read_text(encoding="utf-8")
    ts = [l.split("=", 1)[1].strip() for l in service.splitlines() if l.startswith("TimeoutStartSec=")]
    check(ts == [str(b.SERVICE_TIMEOUT_SECONDS)], f"(8) unit TimeoutStartSec == SERVICE_TIMEOUT_SECONDS ({ts})")
    from services import nba_market
    for stage in ("lines", "props"):
        cmd = nba_market.stage_command(stage, "x")
        check(cmd[cmd.index("--lock-wait-seconds") + 1] == str(b.LOCK_WAIT_SECONDS),
              f"(8) {stage} stage command passes the table's lock wait")
    src = [p for p in ("refresh_nba_daily.py", "services/nba_market.py", "refresh_nba_market.py")
           if any(tok in (HERE / p).read_text(encoding="utf-8") for tok in ("WAIT_SECONDS = 120", "\"--lock-wait-seconds\", \"120\""))]
    check(not src, f"(8) no hard-coded v4 lock wait / step timeout left outside the table ({src})")


def qc_shared_api():
    import refresh_nba_daily as nba
    from services import nba_market
    cmds = {l: c for l, c, _ in nba.STEPS}
    check(cmds.get("game_lines") == nba_market.stage_command("lines", "nba_daily")
          and cmds.get("player_props") == nba_market.stage_command("props", "nba_daily"),
          "(9) bk-daily's NBA lines/props steps ARE the canonical ensure stage commands")
    for stage in ("lines", "props"):
        cmd = nba_market.stage_command(stage, "c")
        check("--allow-reuse" in cmd and "--no-fetch-after-lock" in cmd and cmd[cmd.index("--days") + 1] == "5"
              and cmd[cmd.index("--sport") + 1] == "basketball_nba",
              f"(9) {stage} stage policy: reuse under the lock, never fetch after a failed holder, five-day window")
    seen = []

    class _R:
        returncode = 75
    saved = nba_market.subprocess.run
    nba_market.subprocess.run = lambda command, timeout=None, **k: seen.append((command, timeout)) or _R()
    try:
        with tempfile.TemporaryDirectory() as td:
            st = nba_market.ensure_nba_lines("qc_default", base_dir=td)
    finally:
        nba_market.subprocess.run = saved
    from services import nba_market_budget as b
    check(seen and seen[0][0] == nba_market.stage_command("lines", "qc_default") and seen[0][1] == b.LINES_STAGE_TIMEOUT
          and st["outcome"] == "SKIPPED_LOCKED", "(9) ensure_nba_lines runs the canonical command with the table "
                                                 "timeout by default; exit 75 -> SKIPPED_LOCKED")


def qc_units():
    timer = (HERE / "ops" / "bk-nba-market-refresh.timer").read_text(encoding="utf-8")
    service = (HERE / "ops" / "bk-nba-market-refresh.service").read_text(encoding="utf-8")
    keys = lambda text, k: [l.split("=", 1)[1].strip() for l in text.splitlines() if l.startswith(k + "=")]  # noqa: E731
    check(keys(timer, "Persistent") == ["false"], f"(6) missed runs stay missed: Persistent=false ({keys(timer, 'Persistent')})")
    check(keys(timer, "OnCalendar") == ["*-*-* 00/4:15:00"], "(10) orchestrator fires at :15 past every fourth UTC hour")
    check(keys(service, "Type") == ["oneshot"] and keys(service, "ExecStart") == [
        "/opt/bankrollkings/venv/bin/python refresh_nba_market.py"],
        "(10) one oneshot service runs the single orchestrator entrypoint (systemd: one instance at a time)")
    for name, text in (("timer", timer), ("service", service)):
        check("TIMER-ENABLEMENT BLOCKER" in text and "SCHEDULE_UNAVAILABLE" in text and "NO_GAMES_SCHEDULED" in text
              and "NOT installed" in text, f"(10) orchestrator {name} carries the TIMER-ENABLEMENT BLOCKER")
    gone = [p for p in ("ops/bk-nba-lines.service", "ops/bk-nba-lines.timer", "ops/bk-nba-props.service",
                        "ops/bk-nba-props.timer", "refresh_nba_lines.py") if (HERE / p).exists()]
    check(not gone, f"(10) v4 two-timer proposal removed ({gone or 'none left'})")


_REPO_GUARD = ("data/odds/NBA_Odds.csv", "data/props/NBA_Props.csv", "data/tracking/_last_nba_lines_publish.json",
               "data/tracking/_last_nba_props_publish.json", "data/tracking/_last_nba_props_fetch.json",
               "data/tracking/_last_game_lines_fetch_basketball_nba.json")


def main() -> int:
    sys.path.insert(0, str(HERE))
    guard = {p: _sha(HERE / p) for p in _REPO_GUARD}
    for fn in (qc_timeout_contract, qc_shared_api, qc_units, qc_ordering_receipt_reuse, qc_lines_failure_blocks_props,
               qc_daily_overlaps_orchestrator, qc_contention_without_receipt, qc_concurrent_orchestrators,
               qc_stage_timeout):
        try:
            fn()
        except Exception as exc:  # a crash is a failure, never a pass
            import traceback
            FAILS.append(f"{fn.__name__} crashed: {exc!r}\n{traceback.format_exc()}")
    check({p: _sha(HERE / p) for p in _REPO_GUARD} == guard,
          "the real checkout's NBA odds/props files and receipts are byte-identical (temp dirs only)")
    print("=" * 64)
    print("QC: NBA MARKET ORCHESTRATOR (lines -> props, one receipt, shared ensure API)")
    print("=" * 64)
    for n in NOTES:
        print(f"[OK]   {n}")
    for s in SKIPS:
        print(f"[SKIP] {s}")
    for f in FAILS:
        print(f"[FAIL] {f}")
    print(f"\n{len(NOTES)} passed, {len(FAILS)} failed, {len(SKIPS)} skipped (platform: {sys.platform})")
    return 1 if FAILS else 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--stage-child":
        raise SystemExit(stage_child(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "--orch-child":
        raise SystemExit(orch_child(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "--daily-child":
        raise SystemExit(daily_child(sys.argv[2:]))
    raise SystemExit(main())
