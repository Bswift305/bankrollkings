"""
QC: line-movement status persistence boundary (services.linemove_status + refresh_line_movement_snapshots).

Owner review of d2187e5 (2026-11-07): the runner's summary was a best-effort checkout file. This QC proves the
successor's contract adversarially:

  L  location      under the governed runtime root (<BK_RUNTIME_DIR>/status/line_movement), contained; nothing
                   is written to the checkout's data/tracking; an un-isolated QC process is refused (never raises
                   out of Run Status).
  S  success       all children OK -> runner exit 0; invocation + summary share a valid 32-hex invocation_id;
                   POSIX: dir 0700, files 0600, nlink 1, owned by euid, even under umask 000; Run Status clean.
  W  write fail    summary publication failure -> exit 2 even when every child succeeded; PUBLICATION_FAILED
                   marker -> Run Status DEGRADED at once.
  R  stale residue an older HEALTHY summary is never reported as the current run: a newer invocation without
                   its summary is in-progress inside the grace window and DEGRADED after it.
  B  begin fail    the invocation marker cannot be published -> exit 2 with ZERO children run (tripwire).
  A  replace fail  atomic replace failure -> exit 2, no temp residue.
  F  fsync fail    file fsync failure and directory fsync failure -> exit 2.
  I  ids           malformed invocation ids refused on publish and DEGRADED on read; summary without marker;
                   summary bound to another invocation.
  P  POSIX         symlinked status dir, symlinked / hard-linked / 0644 / foreign-owned summary -> refused,
                   never written through; Run Status DEGRADED on the unsafe file; a loose dir we own is repaired.
  G  legacy        a planted HEALTHY data/tracking/Last_LineMovement_Summary.json is completely ignored (no runtime
                   source names it; it cannot mask a governed failure) and is deliberately left untouched.
  K  killed run    SIGKILL (and SIGTERM on POSIX) after the start marker, before the bound summary: Run Status is
                   in-progress inside the grace window and DEGRADED after it -- never healthy from an older summary.
  X  crash         an unexpected exception in the runner exits 2 (never Python's 1 = SuccessExitStatus=1 success).
Exit 0 on pass, 1 otherwise. POSIX-only cases are reported as skipped on Windows (skips are not passes).
"""
from __future__ import annotations

import sys as _qc_sys  # noqa: E402
from pathlib import Path as _QcPath  # noqa: E402
_qc_sys.path.insert(0, str(_QcPath(__file__).resolve().parent))  # noqa: E402
from services.qc_runtime import isolate_runtime as _isolate_runtime  # noqa: E402
_isolate_runtime()  # per-run temp BK_RUNTIME_DIR: a QC never resolves the production runtime

import contextlib
import io
import json
import os
import stat
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent
import generate_run_status as grs  # noqa: E402
import refresh_line_movement_snapshots as rlm  # noqa: E402
from services import linemove_status as ls  # noqa: E402
from services import receipt_io  # noqa: E402
from services.run_receipts import STAGE_RUN_ENV  # noqa: E402

POSIX = os.name != "nt"
PLATFORM = "linux" if sys.platform.startswith("linux") else sys.platform
SPORT = "basketball_wnba"
PASSED: list[str] = []
FAILED: list[str] = []
SKIPPED: list[str] = []


def check(cond, msg):
    (PASSED if cond else FAILED).append(msg)


def skip(msg):
    SKIPPED.append(msg)


@contextlib.contextmanager
def patched(obj, **kw):
    saved = {k: getattr(obj, k) for k in kw}
    for k, v in kw.items():
        setattr(obj, k, v)
    try:
        yield
    finally:
        for k, v in saved.items():
            setattr(obj, k, v)


def sdir() -> Path:
    return ls.status_dir_spec()[0]


def clean():
    d = sdir()
    if d.is_symlink():
        d.unlink()
    elif d.exists():
        for f in d.iterdir():
            if f.is_dir() and not f.is_symlink():
                continue
            f.unlink()
        if POSIX:
            os.chmod(str(d), 0o700)


def child(root: Path, name: str, code: int = 0, outcome: str = "UPDATED") -> list[str]:
    rp = root / "data" / "tracking" / f"_last_game_lines_fetch_{SPORT}.json"
    p = root / f"{name}.py"
    p.write_text("import json, os, sys, pathlib\n"
                 f"rp = pathlib.Path({str(rp)!r}); rp.parent.mkdir(parents=True, exist_ok=True)\n"
                 f"rp.write_text(json.dumps({{'stage_run_id': os.environ.get({STAGE_RUN_ENV!r}), "
                 f"'outcome': {outcome!r}, 'exit_code': {code}}}), encoding='utf-8')\n"
                 f"sys.exit({code})\n", encoding="utf-8")
    return [sys.executable, str(p)]


def tripwire(root: Path) -> tuple[list[str], Path]:
    sentinel = root / "TRIPWIRE.CALLED"
    p = root / "tripwire.py"
    p.write_text(f"import pathlib\npathlib.Path({str(sentinel)!r}).write_text('called')\n", encoding="utf-8")
    return [sys.executable, str(p)], sentinel


def run(root: Path, cmd: list[str]) -> tuple[int, str]:
    buf = io.StringIO()
    with patched(rlm, BASE_DIR=root, STEPS=[("WNBA game lines", cmd, 60, SPORT)]), contextlib.redirect_stdout(buf):
        rc = rlm._entry()
    return rc, buf.getvalue()


def signals(now=None):
    return ls.read_signals(now)


def overall():
    with patched(grs, _classify=lambda *a, **k: "FRESH", _odds_family_signals=lambda: ([], []),
                 _operator_signals=lambda: ([], {})):
        return grs.build_run_status()["overall"]


def read(name):
    p = sdir() / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def tmp_residue():
    d = sdir()
    return [f.name for f in d.iterdir() if f.name.endswith(".tmp")] if d.exists() else []


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="qc_lmstatus_"))
    ok_cmd = child(root, "ok_child")

    # ---- L. location ----------------------------------------------------------------------------------
    d, rt = ls.status_dir_spec()
    check(Path(d) == Path(os.environ["BK_RUNTIME_DIR"]) / "status" / "line_movement" and Path(rt) == Path(os.environ["BK_RUNTIME_DIR"]),
          f"L status dir is <BK_RUNTIME_DIR>/status/line_movement ({d})")
    tracking_before = sorted(p.name for p in (REPO / "data" / "tracking").glob("*LineMovement_Summary*")) \
        if (REPO / "data" / "tracking").exists() else []
    clean()
    rc, out = run(root, ok_cmd)
    tracking_after = sorted(p.name for p in (REPO / "data" / "tracking").glob("*LineMovement_Summary*")) \
        if (REPO / "data" / "tracking").exists() else []
    check(tracking_after == tracking_before, "L nothing written to the checkout's data/tracking")
    from services.process_lock import is_within
    check(is_within(sdir() / ls.SUMMARY_FILE, os.environ["BK_RUNTIME_DIR"]), "L summary resolves inside the runtime root")
    saved_env = os.environ.pop("BK_RUNTIME_DIR")
    try:
        r, info = ls.read_signals()
        check(r and "refused" in r[0] and info.get("reported") is None,
              f"L un-isolated QC: Run Status reports 'location refused' instead of raising ({r})")
    finally:
        os.environ["BK_RUNTIME_DIR"] = saved_env

    # ---- S. success --------------------------------------------------------------------------------------
    inv, summ = read(ls.INVOCATION_FILE), read(ls.SUMMARY_FILE)
    check(rc == 0 and inv and summ and ls.is_valid_invocation_id(inv["invocation_id"])
          and inv["invocation_id"] == summ["invocation_id"] and summ["exit_code"] == 0,
          f"S all OK -> exit 0, marker + summary share a valid invocation_id (rc={rc})")
    r, info = signals()
    check(r == [] and info.get("invocation_id") == summ["invocation_id"] and overall() == "GREEN",
          f"S Run Status clean and bound to this invocation ({r})")
    check(tmp_residue() == [], "S no temp residue")
    if POSIX:
        old_umask = os.umask(0)
        try:
            clean()
            rc2, _ = run(root, ok_cmd)
        finally:
            os.umask(old_umask)
        dst = os.lstat(str(sdir()))
        check(rc2 == 0 and stat.S_IMODE(dst.st_mode) == 0o700, f"S POSIX dir mode 0700 under umask 000 ({oct(dst.st_mode)})")
        for n in (ls.INVOCATION_FILE, ls.SUMMARY_FILE):
            st = os.lstat(str(sdir() / n))
            check(stat.S_ISREG(st.st_mode) and stat.S_IMODE(st.st_mode) == 0o600 and st.st_nlink == 1
                  and st.st_uid == os.geteuid(), f"S POSIX {n}: regular, 0600, nlink 1, owner euid ({oct(st.st_mode)})")
        calls = []
        real_fsync_dir = ls._fsync_dir
        with patched(ls, _fsync_dir=lambda p: (calls.append(str(p)), real_fsync_dir(p))[1]):
            clean()
            rc3, _ = run(root, ok_cmd)
        check(rc3 == 0 and len(calls) == 2 and all(os.path.samefile(c, str(sdir())) for c in calls),
              f"S POSIX parent directory fsync'd after each publish ({len(calls)} calls)")
    else:
        skip("S POSIX modes / umask / directory fsync")

    # ---- W + R. write failure, stale-success residue ---------------------------------------------------
    clean()
    run(root, ok_cmd)                                   # an older HEALTHY summary exists
    healthy_id = read(ls.SUMMARY_FILE)["invocation_id"]
    real_publish = ls.publish

    def fail_summary(name, payload):
        if name == ls.SUMMARY_FILE:
            raise ls.StatusPublicationError("injected summary write failure")
        return real_publish(name, payload)
    with patched(ls, publish=fail_summary):
        rc, out = run(root, ok_cmd)
    inv = read(ls.INVOCATION_FILE)
    check(rc == 2 and "NOT published" in out, f"W summary write failure -> exit 2 though every child succeeded (rc={rc})")
    check(inv["state"] == ls.STATE_PUBLICATION_FAILED and inv["invocation_id"] != healthy_id,
          "W the new invocation is marked PUBLICATION_FAILED")
    r, _ = signals()
    check(r and "failed to publish" in r[0] and overall() == "DEGRADED",
          f"R/W Run Status DEGRADED immediately; the older healthy summary is NOT current ({r})")
    # both the summary and the failure marker fail -> marker stays RUNNING with the NEW id
    clean()
    run(root, ok_cmd)
    healthy_id = read(ls.SUMMARY_FILE)["invocation_id"]
    with patched(ls, publish=fail_summary, mark_publication_failed=lambda i, e: False):
        rc, _ = run(root, ok_cmd)
    inv = read(ls.INVOCATION_FILE)
    started = datetime.fromisoformat(inv["started_at"])
    r_in, i_in = signals(started + timedelta(seconds=60))
    r_late, _ = signals(started + timedelta(seconds=ls.RUNNING_GRACE_SECONDS + 1))
    check(rc == 2 and inv["state"] == ls.STATE_RUNNING and inv["invocation_id"] != healthy_id,
          "R marker names the NEW invocation even when the failure marker cannot be written")
    check(r_in == [] and i_in.get("in_progress") and i_in.get("summary_invocation_id") == healthy_id
          and i_in.get("invocation_id") != healthy_id,
          "R inside the grace window: in-progress, the older healthy summary is not adopted as current")
    check(r_late and "no published summary" in r_late[0],
          f"R after the grace window: DEGRADED (older healthy summary never reported as current) ({r_late})")
    check(tmp_residue() == [], "W/R no temp residue")

    # ---- B. begin failure -> no child runs ----------------------------------------------------------------
    clean()
    trip, sentinel = tripwire(root)
    real_pub = ls.publish
    with patched(ls, publish=lambda n, p: (_ for _ in ()).throw(ls.StatusPublicationError("injected")) if n == ls.INVOCATION_FILE else real_pub(n, p)):
        rc, out = run(root, trip)
    check(rc == 2 and not sentinel.exists(), f"B marker publish failure -> exit 2, ZERO children run (rc={rc})")
    with patched(ls, begin=lambda i: (_ for _ in ()).throw(TypeError("non-OSError in begin"))):
        rc, _ = run(root, trip)
    check(rc == 2 and not sentinel.exists(), "B a non-OSError while binding the invocation -> exit 2, no child")

    # ---- A. atomic replace failure -------------------------------------------------------------------------
    def bad_replace(tmp, path, budget_seconds=0):
        raise OSError("injected replace failure")
    clean()
    with patched(receipt_io, replace_with_retry=bad_replace):
        rc, out = run(root, ok_cmd)
    check(rc == 2 and tmp_residue() == [], f"A atomic replace failure -> exit 2, temp cleaned (rc={rc}, {tmp_residue()})")
    clean()
    run(root, ok_cmd)
    calls = {"n": 0}
    real_replace = receipt_io.replace_with_retry

    def replace_fail_second(tmp, path, budget_seconds=5.0):   # marker ok, summary replace fails
        calls["n"] += 1
        if calls["n"] == 2:
            raise PermissionError("injected summary replace failure")
        return real_replace(tmp, path, budget_seconds)
    with patched(receipt_io, replace_with_retry=replace_fail_second):
        rc, _ = run(root, ok_cmd)
    r, _ = signals()
    check(rc == 2 and r and overall() == "DEGRADED", f"A summary replace failure -> exit 2, Run Status DEGRADED ({r})")

    # ---- F. fsync failures ---------------------------------------------------------------------------------
    clean()

    def bad_fsync(fd):
        raise OSError("injected fsync failure")
    with patched(ls.os, fsync=bad_fsync):
        rc, _ = run(root, ok_cmd)
    check(rc == 2 and tmp_residue() == [], f"F file fsync failure -> exit 2, no residue (rc={rc})")
    clean()
    run(root, ok_cmd)
    n = {"c": 0}

    def dir_fsync_fail_on_summary(p):
        n["c"] += 1
        if n["c"] == 2:
            raise OSError("injected directory fsync failure")
    with patched(ls, _fsync_dir=dir_fsync_fail_on_summary):
        rc, _ = run(root, ok_cmd)
    check(rc == 2, f"F directory fsync failure on the summary -> exit 2 (rc={rc})")
    r, _ = signals()
    check(r and overall() == "DEGRADED", f"F Run Status DEGRADED after a directory fsync failure ({r})")

    # ---- I. invocation ids -----------------------------------------------------------------------------------
    clean()
    for bad in ("abc", "", None, "A" * 32, "g" * 32, "a" * 33, 123):
        try:
            ls.publish(ls.SUMMARY_FILE, {"invocation_id": bad})
            check(False, f"I publish refused invocation_id {bad!r}")
        except ls.StatusPublicationError:
            check(True, f"I publish refused invocation_id {bad!r}")
    d = sdir()
    d.mkdir(parents=True, exist_ok=True)
    for bad in ("XYZ", "", None):
        (d / ls.INVOCATION_FILE).write_text(json.dumps({"invocation_id": bad, "state": "RUNNING"}), encoding="utf-8")
        if POSIX:
            os.chmod(str(d / ls.INVOCATION_FILE), 0o600)
        r, _ = signals()
        check(r and "invalid invocation_id" in r[0], f"I marker with invocation_id {bad!r} -> DEGRADED ({r})")
    clean()
    (d / ls.SUMMARY_FILE).write_text(json.dumps({"invocation_id": "a" * 32, "steps": [], "exit_code": 0}), encoding="utf-8")
    if POSIX:
        os.chmod(str(d / ls.SUMMARY_FILE), 0o600)
    r, _ = signals()
    check(r and "without an invocation marker" in r[0], f"I summary without a marker -> DEGRADED ({r})")
    (d / ls.INVOCATION_FILE).write_text(json.dumps({"invocation_id": "b" * 32, "state": "RUNNING",
                                                    "started_at": "2020-01-01T00:00:00+00:00"}), encoding="utf-8")
    if POSIX:
        os.chmod(str(d / ls.INVOCATION_FILE), 0o600)
    r, _ = signals()
    check(r and "no published summary" in r[0], f"I summary bound to ANOTHER invocation -> DEGRADED ({r})")

    # ---- P. POSIX path attacks ------------------------------------------------------------------------------
    if POSIX:
        outside = root / "outside.json"
        outside.write_text('{"untouched": true}', encoding="utf-8")
        # symlinked summary
        clean(); run(root, ok_cmd)
        (sdir() / ls.SUMMARY_FILE).unlink()
        os.symlink(str(outside), str(sdir() / ls.SUMMARY_FILE))
        r, _ = signals()
        check(r and "unsafe" in r[0], f"P symlinked summary -> Run Status DEGRADED ({r})")
        rc, _ = run(root, ok_cmd)
        check(rc == 2 and outside.read_text(encoding="utf-8") == '{"untouched": true}',
              "P publish refuses a symlinked summary; the link target is never written")
        # hard-linked summary
        clean(); run(root, ok_cmd)
        os.link(str(sdir() / ls.SUMMARY_FILE), str(root / "alias.json"))
        r, _ = signals()
        rc, _ = run(root, ok_cmd)
        check(r and "hard link" in r[0] and rc == 2, f"P hard-linked summary -> DEGRADED and publish refused ({r}, rc={rc})")
        os.unlink(str(root / "alias.json"))
        # wrong mode
        clean(); run(root, ok_cmd)
        os.chmod(str(sdir() / ls.SUMMARY_FILE), 0o644)
        r, _ = signals()
        rc, _ = run(root, ok_cmd)
        check(r and "looser than 0600" in r[0] and rc == 2, f"P 0644 summary -> DEGRADED and publish refused ({rc})")
        # wrong owner (simulated euid)
        clean(); run(root, ok_cmd)
        with patched(ls.os, geteuid=lambda: os.getuid() + 4242):
            r, _ = signals()
            try:
                ls.publish(ls.SUMMARY_FILE, {"invocation_id": "c" * 32})
                refused = False
            except ls.StatusPublicationError:
                refused = True
        check(r and "owned by uid" in r[0] and refused, f"P foreign-owned summary -> DEGRADED and publish refused ({r})")
        # symlinked status directory
        clean()
        target_dir = root / "elsewhere"
        target_dir.mkdir()
        os.rmdir(str(sdir()))
        os.symlink(str(target_dir), str(sdir()))
        rc, _ = run(root, ok_cmd)
        check(rc == 2 and not any(target_dir.iterdir()), "P symlinked status directory -> refused, exit 2, nothing written through")
        os.unlink(str(sdir()))
        # loose directory we own -> repaired to 0700
        os.makedirs(str(sdir()), exist_ok=True)
        os.chmod(str(sdir()), 0o755)
        rc, _ = run(root, ok_cmd)
        check(rc == 0 and stat.S_IMODE(os.lstat(str(sdir())).st_mode) == 0o700, "P loose directory we own is repaired to 0700")
    else:
        skip("P POSIX symlink / hard-link / mode / owner / directory-symlink attacks")

    # ---- G. planted legacy checkout summary is completely ignored (and left untouched) ----------------------
    legacy_name = "Last_LineMovement_Summary.json"
    for src in ("refresh_line_movement_snapshots.py", "generate_run_status.py", "services/linemove_status.py"):
        check(legacy_name not in (REPO / src).read_text(encoding="utf-8"),
              f"G {src} no longer references the legacy {legacy_name}")
    legacy = root / "data" / "tracking" / legacy_name
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy_body = json.dumps({"finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                              "exit_code": 0, "steps": [{"label": "WNBA game lines", "status": "OK"}],
                              "failed_steps": []})
    legacy.write_text(legacy_body, encoding="utf-8")
    os.utime(str(legacy), (1_700_000_000, 1_700_000_000))
    with patched(grs, BASE_DIR=root, TRACKING_DIR=root / "data" / "tracking"):
        clean()
        r_empty, i_empty = signals()
        check(r_empty == [] and i_empty.get("reported") is False,
              "G empty governed store + healthy legacy file -> 'not reported' (the legacy file is not read)")
        with patched(ls, publish=fail_summary):
            rc, _ = run(root, ok_cmd)
        r, _ = signals()
        check(rc == 2 and r and "failed to publish" in r[0] and overall() == "DEGRADED",
              f"G healthy legacy file cannot mask a governed publication failure ({r})")
    check(legacy.read_text(encoding="utf-8") == legacy_body and int(os.stat(str(legacy)).st_mtime) == 1_700_000_000,
          "G the legacy checkout summary is deliberately left untouched (bytes + mtime unchanged)")

    # ---- K. forced termination after the start marker, before the bound summary -----------------------------
    sleeper = root / "sleeper.py"
    sleeper.write_text("import time\ntime.sleep(15)\n", encoding="utf-8")
    wrapper = root / "runner_wrapper.py"
    wrapper.write_text(
        "import sys, pathlib\n"
        f"sys.path.insert(0, {str(REPO)!r})\n"
        "import refresh_line_movement_snapshots as rlm\n"
        f"rlm.BASE_DIR = pathlib.Path({str(root)!r})\n"
        f"rlm.STEPS = [('WNBA game lines', [sys.executable, {str(sleeper)!r}], 60, {SPORT!r})]\n"
        "raise SystemExit(rlm._entry())\n", encoding="utf-8")
    import subprocess
    import time
    kinds = [("SIGKILL", "kill")] + ([("SIGTERM", "terminate")] if POSIX else [])
    for label, method in kinds:
        clean()
        run(root, ok_cmd)                                  # an older HEALTHY bound summary
        healthy_id = read(ls.SUMMARY_FILE)["invocation_id"]
        proc = subprocess.Popen([sys.executable, str(wrapper)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                env=dict(os.environ), **({"start_new_session": True} if POSIX else {}))
        deadline = time.monotonic() + 30
        inv = None
        while time.monotonic() < deadline:
            inv = read(ls.INVOCATION_FILE) if (sdir() / ls.INVOCATION_FILE).exists() else None
            if inv and inv.get("invocation_id") != healthy_id:
                break
            time.sleep(0.1)
        getattr(proc, method)()
        rc = proc.wait(timeout=30)
        if POSIX:
            try:
                os.killpg(proc.pid, 9)                     # the sleeping child too
            except OSError:
                pass
        summ = read(ls.SUMMARY_FILE)
        if label == "SIGTERM":
            check(rc == 2, f"K SIGTERM: the runner exits 2 (systemd would count a SIGTERM death as clean) (rc={rc})")
        check(inv is not None and inv.get("invocation_id") != healthy_id and inv.get("state") == ls.STATE_RUNNING
              and summ["invocation_id"] == healthy_id,
              f"K {label}: the killed run left its RUNNING marker and no bound summary (runner rc={rc})")
        started = datetime.fromisoformat(inv["started_at"])
        r_in, i_in = signals(started + timedelta(seconds=30))
        r_late, i_late = signals(started + timedelta(seconds=ls.RUNNING_GRACE_SECONDS + 1))
        check(r_in == [] and i_in.get("in_progress") and i_in.get("invocation_id") != healthy_id,
              f"K {label}: inside the grace window it is 'in progress' -- the older healthy summary is not adopted")
        check(r_late and "no published summary" in r_late[0] and i_late.get("invocation_id") == inv["invocation_id"],
              f"K {label}: after the grace window Run Status is DEGRADED, never healthy from the older summary ({r_late})")
    if not POSIX:
        skip("K SIGTERM forced termination")

    # ---- X. crash ---------------------------------------------------------------------------------------------
    with patched(rlm, main=lambda: (_ for _ in ()).throw(RuntimeError("boom"))), contextlib.redirect_stdout(io.StringIO()), \
            contextlib.redirect_stderr(io.StringIO()):
        rc = rlm._entry()
    check(rc == 2, f"X unexpected exception in the runner -> exit 2, never Python's 1 (rc={rc})")
    with patched(rlm, main=lambda: 1), contextlib.redirect_stdout(io.StringIO()):
        rc = rlm._entry()
    check(rc == 2, "X a stray 1 from main() is mapped to 2 at the process boundary")

    print("=" * 72)
    print("QC: LINE-MOVEMENT STATUS PERSISTENCE (governed, durable, mandatory, bound)")
    print("=" * 72)
    for m in PASSED:
        print(f"[OK]   {m}")
    for m in SKIPPED:
        print(f"[SKIP] {m}: POSIX only -- runs on Linux")
    for m in FAILED:
        print(f"[FAIL] {m}")
    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed, {len(SKIPPED)} skipped (platform: {PLATFORM}"
          + ("; skips are not passes -- they run on Linux)" if SKIPPED else ")"))
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
