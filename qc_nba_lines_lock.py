"""QC: single NBA game-lines publisher + shared kernel lock (2026-11, Gap 3) -- REAL two-process contention.

Spawns real OS processes (this file re-invoked with --child) that run the production entry point
(fetch_game_lines.main -> services.nba_lines_publisher.publish -> fetch_game_lines.run_fetch) against a STUB
provider. The stub counts paid-request attempts by appending to a counter file and can hold the lock open
by sleeping inside the "request". Every child blocks all non-loopback network itself.

Proves:
  (1) contention: while process A holds the lock mid-request, process B exits 75 SKIPPED_LOCKED, made ZERO
      provider calls, wrote ZERO bytes (outputs, fetch receipt, publisher receipt all byte-identical), and
      never printed OK/PASS; A then publishes (exactly one request, one publish).
  (2) serialization + reuse: B waiting on the lock (bounded wait) acquires after A releases; with
      --allow-reuse it records REUSED_FRESH and makes zero requests; without it, it fetches.
  (3) release on exit: after A exits normally, a new process acquires immediately.
  (4) release on crash: a process killed while holding the lock (mid-request) leaves no stale lock; the
      next process acquires immediately and publishes.
  (5) lock unavailable (unopenable path) -> exit 76, zero requests, nothing written.
  (6) defense in depth: fetch_game_lines.run_fetch refuses an NBA fetch when the lock is not held.
  (7) reuse_check rules: outside window / future / sha mismatch / non-publish receipt never reuse.
  (8) refresh_nba_daily: exit 75 -> SKIPPED_LOCKED (dependents skipped, DEGRADED); a fresh REUSED_FRESH
      publisher receipt -> REUSED_FRESH (full chain). Both callers use the same entry (fetch_game_lines.py).

OFFLINE: temp dirs only; BK_NBA_LINES_LOCK_PATH points into a temp dir. Exit 0 on pass, 1 otherwise.
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


def check(cond, msg):
    (NOTES if cond else FAILS).append(msg)


# ------------------------------------------------------------------------------------------------ child
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


def child_main(argv) -> int:
    base, counter, hold, extra = Path(argv[0]), Path(argv[1]), float(argv[2]), argv[3:]
    _block_network()
    sys.path.insert(0, str(HERE))
    import fetch_game_lines as fg
    commence = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    lu = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = [{"id": "lockgame", "commence_time": commence, "home_team": "Home L", "away_team": "Away L",
                "bookmakers": [{"key": "draftkings", "title": "DraftKings", "last_update": lu, "markets": [
                    {"key": "h2h", "outcomes": [{"name": "Home L", "price": -140}, {"name": "Away L", "price": 120}]}]}]}]

    def stub_get_json(url):
        with open(counter, "a", encoding="utf-8") as fh:   # one line per paid-request attempt
            fh.write(f"{os.getpid()}\n")
        time.sleep(hold)
        return payload

    def no_network(*a, **k):
        raise RuntimeError("network disabled in QC child")
    fg.BASE_DIR, fg.get_json, fg.urlopen = base, stub_get_json, no_network
    fg._QUOTA.print_receipt = lambda **k: (True, {})
    out = {k: base / f"nba_{k}.csv" for k in ("odds", "sched", "alias")}
    args = ["--api-key", "qc-offline", "--sport", "basketball_nba", "--bookmakers", "draftkings",
            "--output", str(out["odds"]), "--schedules-output", str(out["sched"]),
            "--schedule-alias-output", str(out["alias"]), "--skip-line-movement"] + list(extra)
    return int(fg.main(args))


# ------------------------------------------------------------------------------------------------ parent
def _snapshot(base: Path) -> dict:
    snap = {}
    for p in sorted(base.rglob("*")):
        if p.is_file() and p.name != "counter.txt":
            snap[str(p.relative_to(base))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return snap


def _calls(counter: Path) -> int:
    try:
        return len([l for l in counter.read_text(encoding="utf-8").splitlines() if l.strip()])
    except OSError:
        return 0


def _spawn(base, counter, hold, *extra):
    env = dict(os.environ)
    return subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--child", str(base), str(counter),
                             str(hold), *extra], cwd=str(HERE), env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True)


def _wait_calls(counter, n, timeout=60.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if _calls(counter) >= n:
            return True
        time.sleep(0.05)
    return False


def qc_two_process():
    with tempfile.TemporaryDirectory(prefix="qc_nba_lines_lock_") as td:
        root = Path(td)
        base, lockdir = root / "base", root / "locks"
        base.mkdir()
        os.environ["BK_NBA_LINES_LOCK_PATH"] = str(lockdir / "nba_game_lines.lock")
        counter = root / "counter.txt"

        # (1) contention: A holds the lock inside its (stub) paid request; B is refused.
        a = _spawn(base, counter, 6.0, "--caller", "qc_A")
        check(_wait_calls(counter, 1), "A acquired the lock and entered its request")
        before = _snapshot(base)
        b = _spawn(base, counter, 0.0, "--caller", "qc_B")
        b_out, _ = b.communicate(timeout=120)
        a_alive = a.poll() is None
        after_b = _snapshot(base)
        check(b.returncode == 75 and "SKIPPED_LOCKED" in b_out,
              f"B contended: exit {b.returncode} SKIPPED_LOCKED")
        check(_calls(counter) == 1, f"B made ZERO provider calls (total calls while A holds = {_calls(counter)})")
        check(after_b == before, "B wrote NOTHING: outputs, fetch receipt and publisher receipt byte-identical")
        check(not any(tok in b_out.split() for tok in ("OK", "[OK]", "PASS", "[PASS]")) and "UPDATED" not in b_out,
              "B's output never says OK / PASS / UPDATED")
        check(a_alive, "A was still holding the lock while B was refused (real overlap, not sequential)")
        a_out, _ = a.communicate(timeout=120)
        rec = json.loads((base / "data/tracking/_last_game_lines_fetch_basketball_nba.json").read_text(encoding="utf-8"))
        pub = json.loads((base / "data/tracking/_last_nba_lines_publish.json").read_text(encoding="utf-8"))
        check(a.returncode == 0 and rec.get("outcome") == "UPDATED" and pub.get("caller") == "qc_A"
              and pub.get("outcome") == "UPDATED" and _calls(counter) == 1,
              f"A (winner) made exactly one request and published once (exit {a.returncode}, calls {_calls(counter)})")

        # (3) release on normal exit: immediate acquisition, no wait.
        t0 = time.monotonic()
        c = _spawn(base, counter, 0.0, "--caller", "qc_C")
        c_out, _ = c.communicate(timeout=120)
        check(c.returncode == 0 and _calls(counter) == 2,
              f"lock released when the winner exited: next process acquired and fetched (exit {c.returncode})")

        # (2) serialization + reuse: B2 waits for A2's lock, then REUSES A2's verified publish (no call).
        a2 = _spawn(base, counter, 3.0, "--caller", "qc_A2")
        check(_wait_calls(counter, 3), "A2 holds the lock mid-request")
        b2 = _spawn(base, counter, 0.0, "--caller", "nba_daily", "--allow-reuse", "--lock-wait-seconds", "60")
        b2_out, _ = b2.communicate(timeout=180)
        a2.communicate(timeout=120)
        pub2 = json.loads((base / "data/tracking/_last_nba_lines_publish.json").read_text(encoding="utf-8"))
        check(b2.returncode == 0 and "REUSED_FRESH" in b2_out and _calls(counter) == 3
              and pub2.get("outcome") == "REUSED_FRESH" and pub2.get("paid_requests") == 0
              and float(pub2.get("lock_waited_seconds") or 0) > 0,
              f"serialized: the waiting bk-daily caller acquired after A2 and REUSED_FRESH with zero calls "
              f"(waited {pub2.get('lock_waited_seconds')}s, calls {_calls(counter)})")

        # (4) release on crash: kill a holder mid-request; the next process acquires at once.
        k = _spawn(base, counter, 60.0, "--caller", "qc_killed")
        check(_wait_calls(counter, 4), "victim holds the lock mid-request")
        snap_k = _snapshot(base)
        k.kill()
        k.communicate(timeout=60)
        check(_snapshot(base) == snap_k, "the killed holder left every published file byte-identical (no partial publish)")
        d = _spawn(base, counter, 0.0, "--caller", "qc_after_crash")
        d_out, _ = d.communicate(timeout=120)
        check(d.returncode == 0 and _calls(counter) == 5 and "SKIPPED_LOCKED" not in d_out,
              f"no stale lock after a crash: the next process acquired without waiting (exit {d.returncode})")

        # (5) unopenable lock path -> 76, zero calls, nothing written.
        blocker = root / "not_a_dir"
        blocker.write_text("x", encoding="utf-8")
        os.environ["BK_NBA_LINES_LOCK_PATH"] = str(blocker / "sub" / "nba_game_lines.lock")
        snap_u = _snapshot(base)
        u = _spawn(base, counter, 0.0, "--caller", "qc_unavailable")
        u_out, _ = u.communicate(timeout=120)
        check(u.returncode == 76 and "LOCK_UNAVAILABLE" in u_out and _calls(counter) == 5 and _snapshot(base) == snap_u,
              f"unopenable lock path -> exit {u.returncode} LOCK_UNAVAILABLE, zero calls, nothing written")
        os.environ["BK_NBA_LINES_LOCK_PATH"] = str(lockdir / "nba_game_lines.lock")
        if FAILS:
            for name, out in (("A", a_out), ("B", b_out), ("C", c_out), ("B2", b2_out), ("D", d_out), ("U", u_out)):
                FAILS.append(f"child {name} output tail: {out[-600:]!r}")


def qc_in_process():
    import fetch_game_lines as fg
    from services import nba_lines_publisher as pubm
    calls = []
    saved = (fg.get_json, fg.urlopen)
    fg.get_json = lambda url: calls.append(url) or []
    fg.urlopen = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("network disabled"))
    try:
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            rc = fg.run_fetch(fg.parse_args(["--api-key", "qc-offline", "--sport", "basketball_nba"]))
    finally:
        fg.get_json, fg.urlopen = saved
    check(rc == 1 and not calls and "REFUSED" in buf.getvalue(),
          "run_fetch refuses an NBA fetch outside the publisher (no lock): zero calls, nothing written")
    check(not pubm.lock_is_held(), "lock_is_held() is False outside publish()")
    from services.odds_quota import QuotaRecorder
    with contextlib.redirect_stdout(io.StringIO()) as qbuf:
        QuotaRecorder().print_receipt(endpoint_family="game_lines", sport="basketball_nba", status="fetch error")
    check(": OK" not in qbuf.getvalue() and "not a success" in qbuf.getvalue(),
          "a failed fetch's cost-receipt line never prints OK")

    # lock path resolution: env override > BK_RUNTIME_DIR > POSIX default; never inside the checkout on prod
    saved_env = {k: os.environ.get(k) for k in ("BK_NBA_LINES_LOCK_PATH", "BK_RUNTIME_DIR")}
    try:
        os.environ.pop("BK_NBA_LINES_LOCK_PATH", None)
        os.environ["BK_RUNTIME_DIR"] = "/opt/bankrollkings-runtime"
        p1 = pubm.lock_path()
        os.environ.pop("BK_RUNTIME_DIR", None)
        p2 = pubm.lock_path()
    finally:
        for k, v in saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    check(p1.as_posix() == "/opt/bankrollkings-runtime/locks/nba_game_lines.lock",
          f"lock path follows BK_RUNTIME_DIR ({p1.as_posix()})")
    check((os.name == "nt" and ".runtime" in p2.as_posix()) or
          p2.as_posix() == "/opt/bankrollkings-runtime/locks/nba_game_lines.lock",
          f"unset BK_RUNTIME_DIR -> POSIX default outside the checkout (Windows dev: gitignored .runtime) ({p2.as_posix()})")


def qc_reuse_rules():
    from services import nba_lines_publisher as pubm
    now = datetime(2026, 11, 3, 18, 0, tzinfo=timezone.utc)
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        (base / "data/tracking").mkdir(parents=True)
        f = base / "nba_odds.csv"
        f.write_text("a,b\n1,2\n", encoding="utf-8")
        sha = hashlib.sha256(f.read_bytes()).hexdigest()

        def put(**kw):
            r = {"outcome": "UPDATED", "exit_code": 0, "published": True, "contract": "game_lines_event_v1",
                 "run_id": "r1", "fetch_end": (now - timedelta(minutes=30)).isoformat(),
                 "outputs": {"odds": {"sha256_after": sha}}}
            r.update(kw)
            (base / "data/tracking/_last_game_lines_fetch_basketball_nba.json").write_text(json.dumps(r), encoding="utf-8")
        put()
        check(pubm.reuse_check(base, {"odds": f}, now=now)[0], "reuse: a verified publish 30 min ago is reusable")
        put(fetch_end=(now - timedelta(minutes=pubm.REUSE_WINDOW_MINUTES + 1)).isoformat())
        check(not pubm.reuse_check(base, {"odds": f}, now=now)[0], "reuse: older than the window -> fetch")
        put(fetch_end=(now + timedelta(minutes=5)).isoformat())
        check(not pubm.reuse_check(base, {"odds": f}, now=now)[0], "reuse: a future publish time -> fetch")
        put(fetch_end="2026-11-03T17:30:00")
        check(not pubm.reuse_check(base, {"odds": f}, now=now)[0], "reuse: a naive (zone-unknown) time -> fetch")
        put(outputs={"odds": {"sha256_after": "0" * 64}})
        check(not pubm.reuse_check(base, {"odds": f}, now=now)[0], "reuse: file on disk differs from the publish -> fetch")
        put(outcome="SCHEDULE_UNAVAILABLE", exit_code=1, published=False)
        check(not pubm.reuse_check(base, {"odds": f}, now=now)[0], "reuse: a non-publish receipt is never reused")
        put(contract="GAME_LINES_SPEC whole-file")
        check(not pubm.reuse_check(base, {"odds": f}, now=now)[0], "reuse: only an event-contract publish is reused")
        check(pubm.REUSE_WINDOW_MINUTES * 60 < 6 * 3600 / 2,
              f"reuse window ({pubm.REUSE_WINDOW_MINUTES} min) is well under the 6h executable-price rule")


class _Fake:
    def __init__(self, code):
        self.returncode = code


def qc_nba_daily():
    import refresh_nba_daily as nba
    cmd = next(c for l, c, _ in nba.STEPS if l == "game_lines")
    check("fetch_game_lines.py" in cmd and "--allow-reuse" in cmd and "--lock-wait-seconds" in cmd
          and "nba_daily" in cmd, "bk-daily's NBA lines step runs the shared publisher entry with reuse + bounded lock wait")

    def drive(lines_rc, pub_outcome):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            (base / "data/tracking").mkdir(parents=True)
            (base / "data/props").mkdir(parents=True)
            saved = (nba.BASE_DIR, nba.PROPS_ARTIFACT, nba.subprocess.run)
            ran = []

            def fake_run(command, timeout=None, **kw):
                joined = " ".join(map(str, command))
                label = next(l for l, c, _ in nba.STEPS if next(x for x in c if str(x).endswith(".py")) in joined)
                ran.append(label)
                if label == "game_lines" and pub_outcome:
                    (base / "data/tracking/_last_nba_lines_publish.json").write_text(
                        json.dumps({"outcome": pub_outcome, "exit_code": lines_rc, "detail": "qc"}), encoding="utf-8")
                if label == "game_lines":
                    return _Fake(lines_rc)
                if label == "player_props":
                    (base / "data/tracking/_last_props_fetch_basketball_nba.json").write_text(
                        json.dumps({"events_found": 0}), encoding="utf-8")
                return _Fake(0)
            nba.BASE_DIR, nba.PROPS_ARTIFACT = base, base / "data/props/NBA_Props.csv"
            nba.subprocess.run = fake_run
            try:
                with contextlib.redirect_stdout(io.StringIO()) as buf:
                    rc = nba.main()
            finally:
                nba.BASE_DIR, nba.PROPS_ARTIFACT, nba.subprocess.run = saved
            side = json.loads((base / "data/tracking/_child_outcomes_nba_daily.json").read_text(encoding="utf-8"))
            return rc, ran, side.get("outcomes", {}), buf.getvalue()

    rc, ran, outs, text = drive(75, None)
    check(rc != 0 and outs.get("game_lines") == "SKIPPED_LOCKED" and "player_props" not in ran
          and outs.get("player_props") == "SKIPPED_BLOCKED_BY_LINES" and "[PASS] game_lines" not in text,
          f"nba_daily: publisher exit 75 -> SKIPPED_LOCKED, dependents skipped, DEGRADED ({outs.get('game_lines')})")
    rc, ran, outs, text = drive(0, "REUSED_FRESH")
    check(rc == 0 and outs.get("game_lines") == "REUSED_FRESH" and "player_props" in ran,
          f"nba_daily: fresh REUSED_FRESH publisher receipt -> REUSED_FRESH, full chain runs (rc={rc})")
    rc, ran, outs, text = drive(76, None)
    check(rc != 0 and outs.get("game_lines") == "LOCK_UNAVAILABLE", "nba_daily: exit 76 -> LOCK_UNAVAILABLE (alerting)")


def qc_four_hourly_entry():
    """Cadence (a): the 4-hourly job is the SAME publisher entry, never reuses, same books/window as bk-daily."""
    try:
        import refresh_nba_lines as job
    except ImportError:
        NOTES.append("4-hourly entry (refresh_nba_lines.py) not present on this revision -- skipped")
        return
    import fetch_game_lines as fg
    import refresh_nba_daily as nba
    args = fg.parse_args(job.build_args())
    daily = fg.parse_args([str(x) for x in next(c for l, c, _ in nba.STEPS if l == "game_lines")[2:]])
    check(args.sport == "basketball_nba" and args.caller == "nba_lines_4h" and not args.allow_reuse
          and args.bookmakers == daily.bookmakers and args.days == daily.days,
          "4-hourly job: same entry + books + window as bk-daily, caller nba_lines_4h, never reuses")
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        commence = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        lu = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        payload = [{"id": "fourh", "commence_time": commence, "home_team": "H", "away_team": "A", "bookmakers": [
            {"key": "draftkings", "title": "DraftKings", "last_update": lu, "markets": [
                {"key": "h2h", "outcomes": [{"name": "H", "price": -140}, {"name": "A", "price": 120}]}]}]}]
        calls = []
        saved = (fg.BASE_DIR, fg.get_json, fg.urlopen, fg._QUOTA.print_receipt, dict(fg.SPORT_OUTPUTS["basketball_nba"]))
        fg.BASE_DIR, fg.urlopen = base, (lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no network")))
        fg.get_json = lambda url: calls.append(1) or payload
        fg._QUOTA.print_receipt = lambda **k: (True, {})
        fg.SPORT_OUTPUTS["basketball_nba"].update(odds=base / "NBA_o.csv", schedules=base / "NBA_s.csv", schedule_alias=base / "NBA_a.csv")
        try:
            with contextlib.redirect_stdout(io.StringIO()) as buf:
                rc = job.main(["--skip-line-movement"])
        finally:
            fg.BASE_DIR, fg.get_json, fg.urlopen, fg._QUOTA.print_receipt = saved[:4]
            fg.SPORT_OUTPUTS["basketball_nba"].clear()
            fg.SPORT_OUTPUTS["basketball_nba"].update(saved[4])
        pp = base / "data/tracking/_last_nba_lines_publish.json"
        pub = json.loads(pp.read_text(encoding="utf-8")) if pp.exists() else {}
        ok = (rc == 0 and len(calls) == 1 and pub.get("caller") == "nba_lines_4h" and pub.get("outcome") == "UPDATED"
              and (base / "NBA_o.csv").exists())
        check(ok, f"4-hourly entry publishes through the shared publisher: one request, receipt caller nba_lines_4h "
                  f"(rc={rc})" + ("" if ok else f" output tail: {buf.getvalue()[-800:]!r}"))
        check("published" in buf.getvalue(), "4-hourly entry reports its outcome")


def main() -> int:
    for fn in (qc_in_process, qc_reuse_rules, qc_nba_daily, qc_four_hourly_entry, qc_two_process):
        try:
            fn()
        except Exception as exc:  # a crash is a failure, never a pass
            import traceback
            FAILS.append(f"{fn.__name__} crashed: {exc!r}\n{traceback.format_exc()}")
    print("=" * 64)
    print("QC: NBA LINES SINGLE PUBLISHER + SHARED LOCK (two-process)")
    print("=" * 64)
    for n in NOTES:
        print(f"[OK]   {n}")
    for f in FAILS:
        print(f"[FAIL] {f}")
    print(f"\n{len(NOTES)} passed, {len(FAILS)} failed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--child":
        raise SystemExit(child_main(sys.argv[2:]))
    os.environ.setdefault("BK_NBA_LINES_LOCK_PATH",
                          str(Path(tempfile.mkdtemp(prefix="qc_nba_lines_lock_default_")) / "nba_game_lines.lock"))
    raise SystemExit(main())
