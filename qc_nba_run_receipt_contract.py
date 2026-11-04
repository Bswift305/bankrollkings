"""QC: NBA publisher RECEIPT-IDENTITY CONTRACT (owner decision 2026-11-04; services/run_receipts.py).

No governed NBA stage result may come from a tokenless or mtime-selected receipt. Proves, offline (temp dirs only):

  Behaviour (services/run_receipts + services/nba_market.classify_stage):
   B1 missing own receipt -> RUN_RECEIPT_MISSING (also when the shared `_last_*` file says UPDATED).
   B2 a receipt under this token's name carrying ANOTHER token -> RUN_RECEIPT_MISMATCH; wrong kind -> MISMATCH.
   B3 a tokenless legacy receipt (shared file, or a per-run file without stage_run_id) never decides an outcome.
   B4 concurrent writers (threads + processes, distinct tokens) each read back exactly their own receipt; a second
      write for the same token is refused (token reuse).
   B5 killed writer: a process killed after writing its temp file but before the replace leaves NO receipt
      (RUN_RECEIPT_MISSING, never a partial file adopted); a torn final file -> RUN_RECEIPT_MISSING; the orphan
      temp file is removed by retention.
   B6 unsafe tokens are rejected (length / charset / case / path tricks); an unsafe STAGE_RUN_ENV makes the real
      publisher refuse BEFORE any lock or request (zero provider calls, nothing written); no env token -> the
      publisher generates its own (standalone) and writes its own receipt.
   B7 containment: the receipt dir override outside the runtime root / qc temp is refused; a symlinked receipt
      file is refused (where the OS allows creating one); POSIX files are 0600 (Windows: SKIP).
   B8 retention: age AND count caps; the protected (current) token's receipt survives even when it is the oldest.
   B9 exit code alone never classifies: exit 75 without its own receipt -> RUN_RECEIPT_MISSING; exit 0 with an own
      receipt that is not a success outcome -> VALIDATION_FAILED; timeout -> PROVIDER_ERROR (caller-observed).
  Static (fails if any caller bypasses the contract):
   S1 services/nba_market.py has no mtime / shared-receipt / props_step_outcome path; classify_stage takes a
      REQUIRED stage_run_id.
   S2 refresh_nba_daily.py / refresh_nba_market.py never read `_last_nba_*_publish.json` and expose no mtime
      classifier wrappers.
   S3 only fetch_game_lines.py / fetch_player_props.py call the NBA publishers' publish(); each publish() takes its
      run token (run_receipts.begin) BEFORE the lock, and every receipt write goes through run_receipts.record.
   S4 no tracked file outside the publishers, QCs and docs references the shared `_last_nba_*_publish.json` files.
   S5 caller inventory: every tracked file that invokes fetch_game_lines.py / fetch_player_props.py is classified
      (GOVERNED / STANDALONE / NOT_NBA / TEXT_ONLY); an unclassified new caller fails the QC.
Exit 0 on pass, 1 otherwise.
"""
from __future__ import annotations

import sys as _qc_sys  # noqa: E402
from pathlib import Path as _QcPath  # noqa: E402
_qc_sys.path.insert(0, str(_QcPath(__file__).resolve().parent))  # noqa: E402
from services.qc_runtime import isolate_runtime as _isolate_runtime  # noqa: E402
_isolate_runtime()  # per-run temp BK_RUNTIME_DIR: a QC never resolves the production runtime

import ast
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

FAILS: list[str] = []
NOTES: list[str] = []
SKIPS: list[str] = []


def check(cond, msg):
    (NOTES if cond else FAILS).append(msg)


def _sandbox_env(td: Path):
    from services import run_receipts
    os.environ[run_receipts.RECEIPT_DIR_OVERRIDE_ENV] = str(td / "receipts")
    os.environ.pop(run_receipts.STAGE_RUN_ENV, None)


# ------------------------------------------------------------------------------------------------ children
def writer_child(argv) -> int:
    """--writer <token> <kind> <mode>: mode 'ok' writes normally; 'kill' dies after the temp file, before replace."""
    from services import run_receipts, receipt_io
    token, kind, mode = argv
    if mode == "kill":
        def die(*_a, **_k):
            os._exit(9)            # simulated SIGKILL between temp write and atomic replace
        receipt_io.replace_with_retry = die
    run_receipts.write(token, kind, {"outcome": "UPDATED", "exit_code": 0, "writer_pid": os.getpid()})
    return 0


# ------------------------------------------------------------------------------------------------ behaviour
def qc_behaviour(td: Path):
    from services import nba_market, run_receipts as rr
    _sandbox_env(td)
    base = td / "base"
    (base / "data/tracking").mkdir(parents=True)
    mine, theirs = "1" * 32, "2" * 32

    # B1
    (base / "data/tracking/_last_nba_lines_publish.json").write_text(
        json.dumps({"outcome": "UPDATED", "exit_code": 0}), encoding="utf-8")
    got = nba_market.classify_stage("lines", 0, False, mine)
    check(got[0] == "RUN_RECEIPT_MISSING", f"B1 no own receipt (shared file says UPDATED) -> RUN_RECEIPT_MISSING ({got[0]})")
    check(rr.read_own(mine, "props")[0] == "RUN_RECEIPT_MISSING", "B1 read_own: absent -> RUN_RECEIPT_MISSING")

    # B2
    d = Path(rr.receipt_dir_spec()[0])
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{mine}.lines.json").write_text(json.dumps({"outcome": "UPDATED", "stage_run_id": theirs,
                                                     "receipt_kind": "lines"}), encoding="utf-8")
    got = nba_market.classify_stage("lines", 0, False, mine)
    check(got[0] == "RUN_RECEIPT_MISMATCH", f"B2 own-named receipt carrying another token -> RUN_RECEIPT_MISMATCH ({got[0]})")
    (d / f"{mine}.lines.json").write_text(json.dumps({"outcome": "UPDATED", "stage_run_id": mine,
                                                     "receipt_kind": "props"}), encoding="utf-8")
    check(rr.read_own(mine, "lines")[0] == "RUN_RECEIPT_MISMATCH", "B2 wrong receipt kind -> RUN_RECEIPT_MISMATCH")

    # B3
    (d / f"{mine}.lines.json").write_text(json.dumps({"outcome": "UPDATED"}), encoding="utf-8")   # tokenless
    got = nba_market.classify_stage("lines", 0, False, mine)
    check(got[0] == "RUN_RECEIPT_MISMATCH",
          f"B3 a tokenless receipt (even under this run's name) never decides the outcome ({got[0]})")
    (d / f"{mine}.lines.json").unlink()

    # B9
    got = nba_market.classify_stage("lines", 75, False, mine)
    check(got[0] == "RUN_RECEIPT_MISSING", f"B9 exit 75 without its own receipt -> RUN_RECEIPT_MISSING ({got[0]})")
    rr.write(mine, "lines", {"outcome": "VALIDATION_FAILED", "exit_code": 1})
    got = nba_market.classify_stage("lines", 0, False, mine)
    check(got[0] == "VALIDATION_FAILED", f"B9 exit 0 + own non-success receipt -> VALIDATION_FAILED ({got[0]})")
    got = nba_market.classify_stage("lines", 1, False, mine)
    check(got[0] == "VALIDATION_FAILED" and got[2] is not None, "B9 exit 1 + own VALIDATION_FAILED -> VALIDATION_FAILED")
    check(nba_market.classify_stage("lines", None, True, mine)[0] == "PROVIDER_ERROR",
          "B9 timeout (caller-observed kill) -> PROVIDER_ERROR")
    t2 = "3" * 32
    rr.write(t2, "props", {"outcome": "NO_MARKETS_POSTED", "exit_code": 1})
    check(nba_market.classify_stage("props", 1, False, t2)[0] == "NO_MARKETS_POSTED",
          "B9 props: own benign-nonzero receipt (NO_MARKETS_POSTED, exit 1) is honoured")

    # B4 token reuse
    try:
        rr.write(mine, "lines", {"outcome": "UPDATED", "exit_code": 0})
        reused = False
    except FileExistsError:
        reused = True
    check(reused, "B4 a second receipt for the same token is refused (token reuse)")

    # B4 concurrent writers: 8 threads + 4 processes, distinct tokens, same directory
    toks = [f"{i:032x}" for i in range(0x100, 0x10c)]
    errs = []

    def tw(tok):
        try:
            rr.write(tok, "props", {"outcome": "UPDATED", "exit_code": 0, "who": tok})
        except Exception as exc:   # noqa: BLE001
            errs.append(repr(exc))
    ths = [threading.Thread(target=tw, args=(t,)) for t in toks[:8]]
    procs = [subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--writer", t, "props", "ok"],
                              cwd=str(HERE), env=dict(os.environ)) for t in toks[8:]]
    for th in ths:
        th.start()
    for th in ths:
        th.join()
    for p in procs:
        p.wait(120)
    ok = all(rr.read_own(t, "props")[0] == "OK" and rr.read_own(t, "props")[1]["stage_run_id"] == t for t in toks)
    check(not errs and ok and all(p.returncode == 0 for p in procs),
          f"B4 12 concurrent writers (8 threads + 4 processes) each read back exactly their own receipt ({errs[:2]})")

    # B5 killed writer
    kt = "4" * 32
    p = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--writer", kt, "lines", "kill"],
                       cwd=str(HERE), env=dict(os.environ))
    orphans = list(d.glob(f".{kt}.*.tmp"))
    check(p.returncode == 9 and rr.read_own(kt, "lines")[0] == "RUN_RECEIPT_MISSING" and orphans,
          f"B5 writer killed between temp write and replace: no receipt adopted (RUN_RECEIPT_MISSING), only an "
          f"orphan temp file left (rc={p.returncode}, orphans={len(orphans)})")
    (d / f"{'5' * 32}.lines.json").write_text('{"outcome": "UPD', encoding="utf-8")   # torn final file
    check(rr.read_own("5" * 32, "lines")[0] == "RUN_RECEIPT_MISSING", "B5 a torn receipt is never adopted")
    old = time.time() - 2 * rr.TMP_ORPHAN_SECONDS
    for o in orphans:
        os.utime(o, (old, old))
    rr.prune(protect=())
    check(not list(d.glob(f".{kt}.*.tmp")), "B5 retention removes the killed writer's orphan temp file")

    # B6 unsafe tokens
    bad = ["", "abc", "A" * 32, "g" * 32, "1" * 31, "1" * 33, "../" + "1" * 29, "1" * 30 + "/x", " " + "1" * 31]
    check(all(not rr.is_safe_token(b) for b in bad) and rr.is_safe_token("0123456789abcdef" * 2),
          "B6 only exactly-32 lowercase-hex tokens are safe")
    try:
        rr.receipt_path("../../evil" + "1" * 22, "lines")
        refused = False
    except rr.UnsafeRunToken:
        refused = True
    check(refused, "B6 an unsafe token can never name a receipt path (path traversal refused)")
    qc_publisher_token_paths(td)

    # B7 containment
    saved = os.environ[rr.RECEIPT_DIR_OVERRIDE_ENV]
    os.environ[rr.RECEIPT_DIR_OVERRIDE_ENV] = str(Path.home() / "bk_receipts_outside")
    try:
        rr.receipt_dir_spec()
        out_ok = False
    except Exception as exc:   # LockPathRejected
        out_ok = "refused" in str(exc)
    os.environ[rr.RECEIPT_DIR_OVERRIDE_ENV] = saved
    check(out_ok, "B7 a receipt-dir override outside the runtime root / qc temp is refused")
    st = "6" * 32
    target = td / "elsewhere.json"
    target.write_text(json.dumps({"outcome": "UPDATED", "stage_run_id": st, "receipt_kind": "lines"}), encoding="utf-8")
    try:
        os.symlink(str(target), str(d / f"{st}.lines.json"))
        made = True
    except (OSError, NotImplementedError):
        made = False
    if made:
        check(rr.read_own(st, "lines")[0] == "RUN_RECEIPT_MISSING", "B7 a symlinked receipt file is refused")
    else:
        SKIPS.append("B7 symlinked receipt file: this OS/user cannot create symlinks -- runs on Linux")
    if os.name != "nt":
        mode = os.stat(str(rr.receipt_path(mine, "lines"))).st_mode & 0o777
        check(mode == 0o600, f"B7 POSIX receipt mode 0600 (got {oct(mode)})")
    else:
        SKIPS.append("B7 POSIX 0600 receipt mode: Windows has no POSIX modes -- runs on Linux")

    # B8 retention
    rd = td / "ret"
    os.environ[rr.RECEIPT_DIR_OVERRIDE_ENV] = str(rd / "receipts")
    keep_tok = f"{0xfff:032x}"
    toks = [f"{i:032x}" for i in range(0x200, 0x200 + 30)]
    for i, t in enumerate(toks + [keep_tok]):
        rr.write(t, "lines", {"outcome": "UPDATED", "exit_code": 0})
    now = time.time()
    rdir = Path(rr.receipt_dir_spec()[0])
    os.utime(rdir / f"{keep_tok}.lines.json", (now - 40 * 86400, now - 40 * 86400))   # oldest of all
    for i, t in enumerate(toks):
        age = (20 + i) * 86400 if i < 10 else (30 - i) * 3600
        os.utime(rdir / f"{t}.lines.json", (now - age, now - age))
    removed = rr.prune(protect=(keep_tok,), retain_days=14, max_files=11, now=now)
    left = sorted(p.name.split(".")[0] for p in rdir.glob("*.json"))
    check(keep_tok in left, "B8 the protected (current) run's receipt survives retention even when it is the oldest")
    check(len(left) <= 11 and all(t not in left for t in toks[:10]) and removed >= 19,
          f"B8 retention bounds: >14-day receipts removed and the count capped at 11 incl. the protected one "
          f"({len(left)} left, {removed} removed)")
    os.environ[rr.RECEIPT_DIR_OVERRIDE_ENV] = saved


def qc_publisher_token_paths(td: Path):
    """B6 through the REAL lines publisher: unsafe env token -> refused before lock/request; standalone -> own."""
    from services import nba_lines_publisher as lp, run_receipts as rr
    os.environ["BK_NBA_LINES_LOCK_PATH"] = str(td / "locks" / "nba_game_lines.lock")
    calls = []

    def run_fetch(_args):
        calls.append(1)
        return 1
    base = td / "pubbase"
    (base / "data/tracking").mkdir(parents=True)
    os.environ[rr.STAGE_RUN_ENV] = "NOT-A-SAFE-TOKEN"
    import contextlib
    import io
    with contextlib.redirect_stdout(io.StringIO()) as buf:
        rc = lp.publish(None, run_fetch=run_fetch, base_dir=base, outputs={}, caller="qc_unsafe")
    check(rc == 1 and not calls and "RUN_TOKEN_REJECTED" in buf.getvalue()
          and not (base / "data/tracking/_last_nba_lines_publish.json").exists(),
          "B6 unsafe STAGE_RUN_ENV: the real publisher refuses before any lock/request, writes nothing")
    os.environ.pop(rr.STAGE_RUN_ENV, None)
    with contextlib.redirect_stdout(io.StringIO()) as buf:
        rc = lp.publish(None, run_fetch=run_fetch, base_dir=base, outputs={}, caller="qc_standalone")
    m = re.search(r"own run token ([0-9a-f]{32})", buf.getvalue())
    st = rr.read_own(m.group(1), "lines") if m else ("NONE", None, "")
    check(m and st[0] == "OK" and st[1].get("caller") == "qc_standalone",
          "B6 standalone (no caller token): the publisher generates its own token and writes its own receipt")
    tok = "7" * 32
    os.environ[rr.STAGE_RUN_ENV] = tok
    with contextlib.redirect_stdout(io.StringIO()):
        lp.publish(None, run_fetch=run_fetch, base_dir=base, outputs={}, caller="qc_caller")
    os.environ.pop(rr.STAGE_RUN_ENV, None)
    st = rr.read_own(tok, "lines")
    check(st[0] == "OK" and st[1].get("caller") == "qc_caller",
          "B6 caller token: the publisher writes its receipt under exactly the caller's token")


# ------------------------------------------------------------------------------------------------ static
def _src(rel):
    return (HERE / rel).read_text(encoding="utf-8")


def _code_only(src: str) -> str:
    """Source with comments and docstrings removed (static rules apply to code, not prose)."""
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(getattr(first, "value", None), ast.Constant) \
                    and isinstance(first.value.value, str):
                first.value.value = ""
    return ast.unparse(tree)


CALLER_INVENTORY = {
    "services/nba_market.py": "GOVERNED: ensure_stage passes a fresh run token and reads ONLY its own per-run receipt "
                              "(bk-daily refresh_nba_daily.py + orchestrator refresh_nba_market.py go through it)",
    "batch/REFRESH_DATA.bat": "STANDALONE (Windows dev): default sport basketball_nba; publisher generates its own "
                              "token; the batch uses the exit code only",
    "batch/TASK_refresh_data.bat": "STANDALONE (Windows dev scheduled task): as above",
    "batch/TASK_update_schedule.bat": "STANDALONE (Windows dev): props only; as above",
    "batch/UPDATE_SCHEDULE.bat": "STANDALONE (Windows dev): props only; as above",
    "recover_odds_fetch.py": "STANDALONE operator wrapper: runs an operator-supplied fetch command; exit code + the "
                             "child's printed QUOTA RECEIPT; never reads a publish receipt",
    "run_daily.py": "NOT_NBA: fetch_game_lines --sport americanfootball_nfl_preseason",
    "marketing/generators/weekly_cards.py": "NOT_NBA: fetch_game_lines --sport americanfootball_nfl",
    "app.py": "TEXT_ONLY: comments", "fetch_ncaaf_slate_cfbd.py": "TEXT_ONLY: docstring",
    "fetch_game_lines.py": "TEXT_ONLY: usage text (the entry point itself)",
    "fetch_player_props.py": "TEXT_ONLY: usage text (the entry point itself)",
    "services/nba_lines_publisher.py": "TEXT_ONLY: docstring (the publisher itself)",
    "services/nba_props_publisher.py": "TEXT_ONLY: docstring (the publisher itself)",
}


def qc_static():
    nm = _code_only(_src("services/nba_market.py"))
    bad = [t for t in ("mtime", "_last_nba_lines_publish", "_last_nba_props_publish", "props_step_outcome",
                       "classify_lines", "classify_props_publisher", "load_shape_receipt") if t in nm]
    check(not bad, f"S1 services/nba_market.py code has no mtime / shared-receipt / shape-receipt classifier ({bad})")
    import inspect
    from services import nba_market
    sig = inspect.signature(nba_market.classify_stage)
    check(sig.parameters["stage_run_id"].default is inspect.Parameter.empty,
          "S1 classify_stage REQUIRES a stage_run_id (no default)")
    for rel in ("refresh_nba_daily.py", "refresh_nba_market.py"):
        code = _code_only(_src(rel))
        bad = [t for t in ("_last_nba_lines_publish", "_last_nba_props_publish", "classify_lines",
                           "classify_props_publisher", "props_step_outcome", "st_mtime") if t in code]
        check(not bad, f"S2 {rel}: no shared publish receipt read and no mtime classifier ({bad})")
    files = subprocess.run(["git", "ls-files", "*.py"], cwd=HERE, capture_output=True, text=True, check=True).stdout.split()
    callers = []
    for rel in files:
        if rel.startswith("qc_"):
            continue
        try:
            tree = ast.parse((HERE / rel).read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "publish" \
                    and isinstance(node.func.value, ast.Name) and node.func.value.id in ("nba_lines_publisher",
                                                                                        "nba_props_publisher"):
                callers.append(rel.replace("\\", "/"))
    check(sorted(set(callers)) == ["fetch_game_lines.py", "fetch_player_props.py"],
          f"S3 only the two fetch entry points call an NBA publisher's publish() ({sorted(set(callers))})")
    for rel in ("services/nba_lines_publisher.py", "services/nba_props_publisher.py"):
        src = _src(rel)
        body = src[src.index("def publish("):]
        b, lk = body.find("run_receipts.begin("), body.find("ExclusiveLock(")
        check(0 <= b < lk, f"S3 {rel}: publish() takes its run token BEFORE the lock")
        writer = src[src.index("_RUN_TOKEN: str | None"):src.index("def publish(")]
        check("run_receipts.record(" in writer, f"S3 {rel}: every publisher receipt write goes through run_receipts.record")
    allowed = {"services/nba_lines_publisher.py", "services/nba_props_publisher.py", "services/run_receipts.py",
               "services/receipt_io.py", "services/qc_run_receipts.py"}
    refs = subprocess.run(["git", "grep", "-l", "-E", r"_last_nba_(lines|props)_publish"], cwd=HERE,
                          capture_output=True, text=True).stdout.split()
    stray = [r for r in refs if not (r.startswith("qc_") or r.startswith("docs/") or r.endswith(".md") or r in allowed)]
    check(not stray, f"S4 no caller outside the publishers/QCs/docs references the shared publish receipts ({stray})")
    inv = subprocess.run(["git", "grep", "-l", "-E", r"(fetch_game_lines|fetch_player_props)\.py['\" ]", "--",
                          "*.py", "*.bat", "*.ps1", "*.sh", "*.cmd", "*.service", "*.timer"],
                         cwd=HERE, capture_output=True, text=True).stdout.split()
    unknown = sorted(r for r in inv if not r.startswith("qc_") and r not in CALLER_INVENTORY)
    check(not unknown, f"S5 every caller of the fetch entry points is inventoried/classified (unclassified: {unknown})")
    NOTES.append("S5 inventory: " + "; ".join(f"{k} = {v.split(':')[0]}" for k, v in sorted(CALLER_INVENTORY.items())))


def main(argv) -> int:
    if argv and argv[0] == "--writer":
        return writer_child(argv[1:])
    saved = {k: os.environ.get(k) for k in ("BK_NBA_RUN_RECEIPT_DIR", "BK_NBA_STAGE_RUN_ID", "BK_NBA_LINES_LOCK_PATH")}
    for fn in (qc_behaviour, qc_static):
        try:
            if fn is qc_behaviour:
                with tempfile.TemporaryDirectory(prefix="qc_run_receipt_") as td:
                    fn(Path(td))
            else:
                fn()
        except Exception as exc:  # a crash is a failure, never a pass
            import traceback
            FAILS.append(f"{fn.__name__} crashed: {exc!r}\n{traceback.format_exc()}")
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    print("=" * 64)
    print("QC: NBA RUN-RECEIPT IDENTITY CONTRACT")
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
    raise SystemExit(main(sys.argv[1:]))
