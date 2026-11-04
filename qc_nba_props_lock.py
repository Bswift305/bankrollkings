"""QC: single NBA player-props publisher + its OWN kernel lock (2026-11, NBA v4 owner update) -- real processes.

Spawns real OS processes (this file re-invoked with --child) that run the production entry point
(fetch_player_props.main -> services.nba_props_publisher.publish -> fetch_player_props.run_fetch) against a
STUB provider at the HTTP boundary (fetch_player_props.get_json: the free /events listing AND the paid
/events/{id}/odds calls both count). The stub can hold the lock open by sleeping inside a request, or fail.
Every child blocks all non-loopback network itself.

Proves:
  (1) contention: while A holds the PROPS lock mid-request, B exits 75 SKIPPED_LOCKED, made ZERO provider
      calls (not even /events), wrote ZERO bytes, never printed OK/PASS/UPDATED; A publishes UPDATED.
  (2) uncontended reuse -> REUSED_FRESH (zero calls); a waiter that acquired after A2 re-reads the props
      receipt + file sha under the lock -> REUSED_FRESH_AFTER_LOCK (zero calls).
  (3) after a FAILED holder the waiter never says OK: --no-fetch-after-lock -> NO_FRESH_AFTER_LOCK (exit 1,
      zero calls); default -> fetches under the lock.
  (4) lines-after-props ordering: no verified lines publish, a stale one, or an NBA_Odds.csv whose sha no
      longer matches its receipt -> SKIPPED_BLOCKED_BY_LINES, exit 1, ZERO calls, nothing written.
  (5) crash release: a holder killed mid-request leaves no stale lock and no partial publish.
  (6) location enforcement: override outside the runtime/qc temp root, lock dir symlinked outside, lock file
      symlinked outside -> exit 76 LOCK_UNAVAILABLE, ZERO calls.
  (7) separate locks: the props lock path differs from the lines lock path, and a held LINES lock does not
      block a props publish (props never take the lines lock).
  (8) defense in depth: run_fetch refuses NBA props outside the publisher; football/WNBA are unaffected.
  (9) refresh_nba_daily: the props step runs the publisher entry with reuse + bounded wait; 75 / 76 /
      REUSED_* / NO_FRESH_AFTER_LOCK / SKIPPED_BLOCKED_BY_LINES classify correctly (benign vs alerting).
POSIX dir 0700 / file 0600 enforcement is the shared services/process_lock code (qc_nba_lines_lock unit
checks); here the props canonical lock's modes are checked on POSIX and [SKIP]ped with a reason on Windows.
OFFLINE: temp dirs only. Exit 0 on pass, 1 otherwise.
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
PLAYERS = ("Qcprops Alpha", "Qcprops Bravo", "Qcprops Charlie", "Qcprops Delta", "Qcprops Echo")


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


def _event():
    commence = (datetime.now(timezone.utc) + timedelta(hours=20)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"id": "propsgame", "commence_time": commence, "home_team": "Home P", "away_team": "Away P"}


def _odds_payload():
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
    return {"id": "propsgame", "bookmakers": books}


def child_main(argv) -> int:
    base, counter, hold, extra = Path(argv[0]), Path(argv[1]), float(argv[2]), argv[3:]
    _block_network()
    sys.path.insert(0, str(HERE))
    import fetch_player_props as fp

    def stub_get_json(url):
        with open(counter, "a", encoding="utf-8") as fh:   # one line per provider request (free or paid)
            fh.write(f"{os.getpid()}\n")
        time.sleep(hold)
        if os.environ.get("QC_STUB_FAIL") == "1":
            raise RuntimeError("qc stub provider error")
        return _odds_payload() if "/odds" in url else [_event()]
    fp.BASE_DIR, fp.get_json = base, stub_get_json
    fp.urlopen = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("network disabled in QC child"))
    fp._QUOTA.print_receipt = lambda **k: (True, {})
    out = base / "data" / "props" / "NBA_Props.csv"
    args = ["--api-key", "qc-offline", "--sport", "basketball_nba", "--bookmakers", "draftkings,fanduel",
            "--days", "5", "--output", str(out)] + list(extra)
    return int(fp.main(args))


# ------------------------------------------------------------------------------------------------ parent
def _sha(p: Path):
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest()
    except OSError:
        return None


def _snapshot(base: Path) -> dict:
    return {str(p.relative_to(base)): _sha(p) for p in sorted(base.rglob("*")) if p.is_file()}


def _calls(counter: Path) -> int:
    try:
        return len([l for l in counter.read_text(encoding="utf-8").splitlines() if l.strip()])
    except OSError:
        return 0


def _wait_calls(counter, n, timeout=60.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if _calls(counter) >= n:
            return True
        time.sleep(0.05)
    return False


def _spawn(base, counter, hold, *extra, env_extra=None):
    env = dict(os.environ)
    env.update(env_extra or {})
    return subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--child", str(base), str(counter),
                             str(hold), *extra], cwd=str(HERE), env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True)


def _seed_lines(base: Path, age_minutes: float = 10.0) -> None:
    """A receipt-verified NBA lines publish (the props event list) inside `base`."""
    odds = base / "data" / "odds" / "NBA_Odds.csv"
    odds.parent.mkdir(parents=True, exist_ok=True)
    odds.write_text("GameID,Away,Home,Book,LastUpdated\npropsgame,Away P,Home P,DraftKings,x\n", encoding="utf-8")
    rec = base / "data" / "tracking" / "_last_game_lines_fetch_basketball_nba.json"
    rec.parent.mkdir(parents=True, exist_ok=True)
    rec.write_text(json.dumps({
        "outcome": "UPDATED", "exit_code": 0, "published": True, "contract": "game_lines_event_v1",
        "run_id": "qc-lines-run", "fetch_end": (datetime.now(timezone.utc) - timedelta(minutes=age_minutes)).isoformat(),
        "outputs": {"odds": {"sha256_after": _sha(odds)}}}), encoding="utf-8")


def _pub(base):
    p = base / "data" / "tracking" / "_last_nba_props_publish.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _never_ok(out: str) -> bool:
    return not any(t in out for t in ("[OK]", "[PASS]", "[UPDATED]", "[REUSED"))


def qc_contention_reuse_crash():
    with tempfile.TemporaryDirectory(prefix="qc_nba_props_lock_") as td:
        root = Path(td)
        base = root / "base"
        base.mkdir()
        _seed_lines(base)
        counter = root / "counter.txt"
        env = {"BK_NBA_PROPS_LOCK_PATH": str(root / "locks" / "nba_player_props.lock")}

        a = _spawn(base, counter, 4.0, "--caller", "qc_A", env_extra=env)
        check(_wait_calls(counter, 1), "A acquired the props lock and entered its /events request")
        before = _snapshot(base)
        b = _spawn(base, counter, 0.0, "--caller", "qc_B", env_extra=env)
        b_out, _ = b.communicate(timeout=120)
        a_alive = a.poll() is None
        check(b.returncode == 75 and "[SKIPPED_LOCKED]" in b_out, f"B contended: exit {b.returncode} SKIPPED_LOCKED")
        check(_calls(counter) == 1, f"B made ZERO provider calls, not even the free /events ({_calls(counter)} total)")
        check(_snapshot(base) == before, "B wrote NOTHING (props file, receipts byte-identical)")
        check(_never_ok(b_out), "B's output never says OK / PASS / UPDATED / REUSED")
        check(a_alive, "A was still holding the props lock while B was refused (real overlap)")
        a_out, _ = a.communicate(timeout=120)
        pub = _pub(base)
        n_after_a = _calls(counter)
        check(a.returncode == 0 and pub.get("outcome") == "UPDATED" and pub.get("caller") == "qc_A"
              and (base / "data/props/NBA_Props.csv").exists() and pub.get("lines_run_id") == "qc-lines-run",
              f"A published UPDATED against the verified lines event list (exit {a.returncode}, calls {n_after_a})"
              + ("" if a.returncode == 0 else f" tail={a_out[-900:]!r}"))

        r = _spawn(base, counter, 0.0, "--caller", "nba_daily", "--allow-reuse", "--lock-wait-seconds", "60",
                   env_extra=env)
        r_out, _ = r.communicate(timeout=120)
        check(r.returncode == 0 and "[REUSED_FRESH]" in r_out and _pub(base).get("outcome") == "REUSED_FRESH"
              and _pub(base).get("lock_contended") is False and _calls(counter) == n_after_a,
              "uncontended reuse: REUSED_FRESH, zero calls")

        a2 = _spawn(base, counter, 3.0, "--caller", "qc_A2", env_extra=env)
        check(_wait_calls(counter, n_after_a + 1), "A2 holds the props lock mid-request")
        b2 = _spawn(base, counter, 0.0, "--caller", "nba_daily", "--allow-reuse", "--lock-wait-seconds", "60",
                    env_extra=env)
        b2_out, _ = b2.communicate(timeout=180)
        a2.communicate(timeout=120)
        n_after_a2 = _calls(counter)
        p2 = _pub(base)
        check(b2.returncode == 0 and "[REUSED_FRESH_AFTER_LOCK]" in b2_out and p2.get("outcome") == "REUSED_FRESH_AFTER_LOCK"
              and p2.get("lock_contended") is True and p2.get("paid_requests") == 0
              and _calls(counter) == n_after_a2,
              f"waiter re-read receipt + sha under the props lock: REUSED_FRESH_AFTER_LOCK, zero own calls "
              f"(waited {p2.get('lock_waited_seconds')}s)")

        k = _spawn(base, counter, 60.0, "--caller", "qc_killed", env_extra=env)
        check(_wait_calls(counter, n_after_a2 + 1), "victim holds the props lock mid-request")
        snap_k = _snapshot(base)
        k.kill()
        k.communicate(timeout=60)
        check(_snapshot(base) == snap_k, "killed holder left every file byte-identical (no partial publish)")
        d = _spawn(base, counter, 0.0, "--caller", "qc_after_crash", env_extra=env)
        d_out, _ = d.communicate(timeout=120)
        check(d.returncode == 0 and "SKIPPED_LOCKED" not in d_out,
              f"no stale props lock after a crash: next process acquired at once and published (exit {d.returncode})")


def qc_failed_holder():
    with tempfile.TemporaryDirectory(prefix="qc_nba_props_nofresh_") as td:
        root = Path(td)
        base = root / "base"
        base.mkdir()
        _seed_lines(base)
        counter = root / "counter.txt"
        env = {"BK_NBA_PROPS_LOCK_PATH": str(root / "locks" / "nba_player_props.lock")}
        h = _spawn(base, counter, 3.0, "--caller", "qc_fail_holder", env_extra={**env, "QC_STUB_FAIL": "1"})
        check(_wait_calls(counter, 1), "failing props holder holds the lock")
        w = _spawn(base, counter, 0.0, "--caller", "nba_daily", "--allow-reuse", "--lock-wait-seconds", "60",
                   "--no-fetch-after-lock", env_extra=env)
        w_out, _ = w.communicate(timeout=180)
        h.communicate(timeout=120)
        n = _calls(counter)
        check(w.returncode == 1 and "[NO_FRESH_AFTER_LOCK]" in w_out and _pub(base).get("outcome") == "NO_FRESH_AFTER_LOCK"
              and not (base / "data/props/NBA_Props.csv").exists() and _never_ok(w_out),
              f"after a FAILED holder: NO_FRESH_AFTER_LOCK exit {w.returncode}, nothing published, never OK")
        h2 = _spawn(base, counter, 3.0, "--caller", "qc_fail_holder2", env_extra={**env, "QC_STUB_FAIL": "1"})
        check(_wait_calls(counter, n + 1), "second failing props holder holds the lock")
        w2 = _spawn(base, counter, 0.0, "--caller", "nba_daily", "--allow-reuse", "--lock-wait-seconds", "60",
                    env_extra=env)
        w2_out, _ = w2.communicate(timeout=180)
        h2.communicate(timeout=120)
        check(w2.returncode == 0 and _pub(base).get("outcome") == "UPDATED" and _pub(base).get("lock_contended") is True,
              f"default waiter after a FAILED holder fetches normally under the props lock (exit {w2.returncode})")


def qc_lines_prerequisite():
    for label, prep in (
            ("no verified lines publish", lambda b: None),
            ("lines publish older than the prerequisite window",
             lambda b: _seed_lines(b, age_minutes=200)),
            ("NBA_Odds.csv changed since its receipt (sha mismatch)",
             lambda b: (_seed_lines(b), (b / "data/odds/NBA_Odds.csv").write_text("GameID,Away,Home\nx,a,b\n",
                                                                                  encoding="utf-8")))):
        with tempfile.TemporaryDirectory(prefix="qc_nba_props_lines_") as td:
            root = Path(td)
            base = root / "base"
            base.mkdir()
            prep(base)
            counter = root / "counter.txt"
            snap = _snapshot(base)
            p = _spawn(base, counter, 0.0, "--caller", "qc_prereq",
                       env_extra={"BK_NBA_PROPS_LOCK_PATH": str(root / "locks" / "nba_player_props.lock")})
            out, _ = p.communicate(timeout=120)
            pub_path = "data/tracking/_last_nba_props_publish.json"
            after = {k: v for k, v in _snapshot(base).items() if k != pub_path.replace("/", os.sep)}
            check(p.returncode == 1 and "[SKIPPED_BLOCKED_BY_LINES]" in out and _calls(counter) == 0
                  and after == snap and _pub(base).get("outcome") == "SKIPPED_BLOCKED_BY_LINES",
                  f"lines prerequisite ({label}) -> SKIPPED_BLOCKED_BY_LINES, ZERO calls, props untouched "
                  f"(exit {p.returncode})" + ("" if p.returncode == 1 else f" tail={out[-500:]!r}"))


def _try_symlink(target: Path, link: Path, is_dir: bool):
    try:
        os.symlink(str(target), str(link), target_is_directory=is_dir)
        return None
    except (OSError, NotImplementedError) as exc:
        return f"cannot create symlinks here ({exc!r})"


def qc_location_and_separation():
    from services import nba_lines_publisher as lp
    from services import nba_props_publisher as pp
    from services.process_lock import ExclusiveLock
    with tempfile.TemporaryDirectory(prefix="qc_nba_props_loc_") as td, \
            tempfile.TemporaryDirectory(prefix="bkx_props_outside_") as otd:
        root, outside = Path(td), Path(otd)
        base = root / "base"
        base.mkdir()
        _seed_lines(base)
        counter = root / "counter.txt"

        def run(label, env, expect_rc, note):
            c0, snap = _calls(counter), _snapshot(base)
            p = _spawn(base, counter, 0.0, "--caller", label, env_extra=env)
            out, _ = p.communicate(timeout=120)
            okk = p.returncode == expect_rc and (expect_rc == 0 or (_calls(counter) == c0 and _snapshot(base) == snap
                                                                   and "LOCK_UNAVAILABLE" in out))
            check(okk, f"{note} (exit {p.returncode}, calls +{_calls(counter) - c0})" + ("" if okk else f" tail={out[-400:]!r}"))

        none = {"BK_NBA_PROPS_LOCK_PATH": ""}
        rt = root / "rt"
        # (7) separation: hold the LINES lock under the same runtime root; props still publish.
        saved = {k: os.environ.get(k) for k in ("BK_RUNTIME_DIR", "BK_NBA_LINES_LOCK_PATH", "BK_NBA_PROPS_LOCK_PATH")}
        try:
            os.environ["BK_RUNTIME_DIR"] = str(rt)
            os.environ.pop("BK_NBA_LINES_LOCK_PATH", None)
            os.environ.pop("BK_NBA_PROPS_LOCK_PATH", None)
            lpath, lroot, _ = lp.lock_spec()
            ppath, proot, _ = pp.lock_spec()
            check(lpath != ppath and lpath.parent == ppath.parent and ppath.name == "nba_player_props.lock",
                  f"props lock is its OWN file next to the lines lock ({ppath.name} vs {lpath.name})")
            held = ExclusiveLock(lpath, label="qc lines holder", root=lroot)
            check(held.acquire(), "parent holds the NBA LINES lock")
            try:
                run("qc_props_while_lines_locked", {**none, "BK_RUNTIME_DIR": str(rt)}, 0,
                    "a held LINES lock does not block a props publish (props never take the lines lock)")
            finally:
                held.release()
            if os.name != "nt":
                import stat as st_
                check(st_.S_IMODE(os.stat(ppath.parent).st_mode) == 0o700 and st_.S_IMODE(os.stat(ppath).st_mode) == 0o600,
                      "props lock dir 0700 / lock file 0600 on POSIX")
            else:
                SKIPS.append("props lock dir 0700 / file 0600 mode check: Windows has no POSIX modes -- runs on Linux")
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

        run("qc_override_outside", {"BK_RUNTIME_DIR": str(root / "rt_x"),
                                    "BK_NBA_PROPS_LOCK_PATH": str(outside / "locks" / "p.lock")}, 76,
            "props override outside the runtime root / qc temp root -> LOCK_UNAVAILABLE, zero calls")
        (outside / "dir_target").mkdir()
        rt2 = root / "rt_dirlink"
        rt2.mkdir()
        why = _try_symlink(outside / "dir_target", rt2 / "locks", True)
        if why:
            SKIPS.append(f"props lock-dir symlink escape: {why}")
        else:
            run("qc_dir_link", {**none, "BK_RUNTIME_DIR": str(rt2)}, 76,
                "props lock dir symlinked outside -> LOCK_UNAVAILABLE, zero calls")
        victim = outside / "victim.txt"
        victim.write_text("keep", encoding="utf-8")
        rt3 = root / "rt_filelink"
        (rt3 / "locks").mkdir(parents=True)
        if os.name != "nt":
            os.chmod(rt3 / "locks", 0o700)
        why = _try_symlink(victim, rt3 / "locks" / "nba_player_props.lock", False)
        if why:
            SKIPS.append(f"props lock-file symlink escape: {why}")
        else:
            run("qc_file_link", {**none, "BK_RUNTIME_DIR": str(rt3)}, 76,
                "props lock FILE symlinked outside -> LOCK_UNAVAILABLE, zero calls")
            check(victim.read_text(encoding="utf-8") == "keep", "symlink target outside untouched")


def qc_in_process():
    import fetch_player_props as fp
    from services import nba_props_publisher as pp
    calls = []
    saved = (fp.get_json, fp.urlopen)
    fp.get_json = lambda url: calls.append(url) or []
    fp.urlopen = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("network disabled"))
    try:
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            rc = fp.run_fetch(fp.parse_args(["--api-key", "qc-offline", "--sport", "basketball_nba"]))
    finally:
        fp.get_json, fp.urlopen = saved
    check(rc == 1 and not calls and "REFUSED" in buf.getvalue(),
          "run_fetch refuses NBA props outside the publisher (no lock): zero calls")
    check(not pp.lock_is_held(), "props lock_is_held() is False outside publish()")
    check(fp.NBA_PROPS_PUBLISHER_SPORTS == frozenset({"basketball_nba"}),
          "only NBA props route through the props publisher (WNBA / MLB / football unchanged)")
    check(pp.REUSE_WINDOW_MINUTES * 60 < 6 * 3600 / 2 and pp.LINES_PREREQ_MAX_AGE_MINUTES < 6 * 60,
          "props reuse window (90 min) and lines prerequisite (120 min) sit well inside the 6h rule")


class _Fake:
    def __init__(self, code):
        self.returncode = code


def qc_nba_daily():
    import refresh_nba_daily as nba
    from services import run_outcomes as ro
    cmd = next(c for l, c, _ in nba.STEPS if l == "player_props")
    check("fetch_player_props.py" in cmd and "--allow-reuse" in cmd and "--lock-wait-seconds" in cmd
          and "nba_daily" in cmd and "--days" in cmd and cmd[cmd.index("--days") + 1] == "5",
          "bk-daily's NBA props step runs the props publisher entry with reuse + bounded wait, full 5-day window")
    labels = [l for l, _, _ in nba.STEPS]
    check(labels.index("game_lines") < labels.index("player_props"), "props run AFTER lines in bk-daily")

    def drive(props_rc, pub_outcome):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            (base / "data/tracking").mkdir(parents=True)
            (base / "data/props").mkdir(parents=True)
            saved = (nba.BASE_DIR, nba.PROPS_ARTIFACT, nba.subprocess.run)

            def fake_run(command, timeout=None, **kw):
                joined = " ".join(map(str, command))
                label = next(l for l, c, _ in nba.STEPS if next(x for x in c if str(x).endswith(".py")) in joined)
                if label == "player_props":
                    (base / "data/tracking/_last_props_fetch_basketball_nba.json").write_text(
                        json.dumps({"events_found": 3, "rows_fetched": 0, "provider_error_count": 0,
                                    "markets_present_anywhere": ["player_points"]}), encoding="utf-8")
                    if pub_outcome:
                        (base / "data/tracking/_last_nba_props_publish.json").write_text(
                            json.dumps({"outcome": pub_outcome, "detail": "qc"}), encoding="utf-8")
                    return _Fake(props_rc)
                return _Fake(0)
            nba.BASE_DIR, nba.PROPS_ARTIFACT = base, base / "data/props/NBA_Props.csv"
            nba.subprocess.run = fake_run
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    rc = nba.main()
            finally:
                nba.BASE_DIR, nba.PROPS_ARTIFACT, nba.subprocess.run = saved
            side = json.loads((base / "data/tracking/_child_outcomes_nba_daily.json").read_text(encoding="utf-8"))
            return rc, side.get("outcomes", {}).get("player_props")

    for props_rc, pub, want, benign in ((75, None, "SKIPPED_LOCKED", False), (76, None, "LOCK_UNAVAILABLE", False),
                                        (0, "REUSED_FRESH", "REUSED_FRESH", True),
                                        (0, "REUSED_FRESH_AFTER_LOCK", "REUSED_FRESH_AFTER_LOCK", True),
                                        (1, "NO_FRESH_AFTER_LOCK", "NO_FRESH_AFTER_LOCK", False),
                                        (1, "SKIPPED_BLOCKED_BY_LINES", "SKIPPED_BLOCKED_BY_LINES", False)):
        rc, got = drive(props_rc, pub)
        check(got == want and (rc == 0) is benign and ro.is_alerting(got) is (not benign),
              f"nba_daily props step: exit {props_rc}{' + receipt ' + pub if pub else ''} -> {got} "
              f"({'benign' if benign else 'alerting, run DEGRADED'}; rc={rc})")


def main() -> int:
    for fn in (qc_in_process, qc_nba_daily, qc_lines_prerequisite, qc_contention_reuse_crash, qc_failed_holder,
               qc_location_and_separation):
        try:
            fn()
        except Exception as exc:  # a crash is a failure, never a pass
            import traceback
            FAILS.append(f"{fn.__name__} crashed: {exc!r}\n{traceback.format_exc()}")
    print("=" * 64)
    print("QC: NBA PLAYER-PROPS SINGLE PUBLISHER + OWN LOCK (two-process)")
    print("=" * 64)
    for n in NOTES:
        print(f"[OK]   {n}")
    for s in SKIPS:
        print(f"[SKIP] {s}")
    for f in FAILS:
        print(f"[FAIL] {f}")
    print(f"\n{len(NOTES)} passed, {len(FAILS)} failed, {len(SKIPS)} skipped (platform: {sys.platform}; "
          "skips are not passes -- they run on Linux)")
    return 1 if FAILS else 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--child":
        raise SystemExit(child_main(sys.argv[2:]))
    os.environ.setdefault("BK_NBA_PROPS_LOCK_PATH",
                          str(Path(tempfile.mkdtemp(prefix="qc_nba_props_lock_default_")) / "nba_player_props.lock"))
    raise SystemExit(main())
