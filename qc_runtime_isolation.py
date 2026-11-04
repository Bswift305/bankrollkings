"""QC: no QC can resolve -- let alone lock or write in -- the production runtime (Linux gate defect 1, 2026-11-04).

On the Linux gate, qc_game_lines_event_slate / qc_nba_no_game_governance never set BK_RUNTIME_DIR, so the NBA
publisher resolved `/opt/bankrollkings-runtime` (the PRODUCTION runtime on the prod box). Two layers now:

  S  static: every tracked qc_*.py that can reach an NBA publisher / lock / run receipt / the line-movement
     runner (imports of nba_lines_publisher, nba_props_publisher, nba_market, run_receipts, process_lock,
     refresh_nba_daily, refresh_nba_market, refresh_line_movement_snapshots, fetch_game_lines,
     fetch_player_props, qc_run_receipts, or a fetch_game_lines.py / fetch_player_props.py command) calls
     services.qc_runtime.isolate_runtime() at MODULE TOP LEVEL, before it imports any of those modules.
  G  runtime guard: inside a QC process (BK_QC_OFFLINE=1, or a qc_*.py main script) runtime_root() REFUSES an
     unset runtime, the POSIX production default, and any directory that is not a qc_* temp dir; a qc_* temp
     runtime is accepted. Exercised in real child processes (not in this process's state).
  I  isolate_runtime(): replaces a production / non-qc value with a fresh 0700 qc_runtime_* dir, keeps an
     existing qc_* temp runtime (children inherit their parent's), and restores the environment at exit.
  M  mutation: a reach-set QC with the isolation call removed (or placed after the reach import) is FLAGGED.
Exit 0 on pass, 1 otherwise.
"""
from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
FAILS: list[str] = []
NOTES: list[str] = []
REACH_RE = re.compile(r"import (fetch_game_lines|fetch_player_props)|from (fetch_game_lines|fetch_player_props) import|"
                      r"nba_lines_publisher|nba_props_publisher|nba_market[^_]|nba_market$|run_receipts|"
                      r"refresh_nba_daily|refresh_nba_market|refresh_line_movement_snapshots|process_lock|"
                      r"fetch_game_lines\.py|fetch_player_props\.py", re.M)
REACH_MODULES = ("fetch_game_lines", "fetch_player_props", "nba_lines_publisher", "nba_props_publisher", "nba_market",
                 "run_receipts", "refresh_nba_daily", "refresh_nba_market", "refresh_line_movement_snapshots",
                 "process_lock", "qc_run_receipts", "app")


def check(cond, msg):
    (NOTES if cond else FAILS).append(msg)


def isolation_problem(src: str) -> str | None:
    """None when the module calls _isolate_runtime() at top level before importing any reach module."""
    tree = ast.parse(src)
    call_at = None
    first_reach = None
    for i, node in enumerate(tree.body):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) and \
                getattr(node.value.func, "id", None) == "_isolate_runtime":
            call_at = i if call_at is None else call_at
        names = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""] + [a.name for a in node.names]
        if first_reach is None and any(n.split(".")[-1] in REACH_MODULES or n in REACH_MODULES for n in names):
            first_reach = i
    if call_at is None:
        return "no top-level _isolate_runtime() call"
    if first_reach is not None and first_reach < call_at:
        return "a reach module is imported before _isolate_runtime()"
    return None


def reach_set():
    files = subprocess.run(["git", "ls-files", "qc_*.py"], cwd=HERE, capture_output=True, text=True,
                           check=True).stdout.split()
    out = []
    for rel in files:
        if rel == "qc_runtime_isolation.py":
            continue
        src = (HERE / rel).read_text(encoding="utf-8")
        if REACH_RE.search(src):
            out.append((rel, src))
    return out


GUARD_CHILD = r'''
import os, sys
sys.path.insert(0, os.getcwd())
from services import nba_lines_publisher as p
try:
    print("OK", p.runtime_root())
except p.LockPathRejected as exc:
    print("REFUSED", exc)
'''


def run_guard(env_overrides: dict, script_name: str) -> str:
    env = dict(os.environ)
    env.pop("BK_RUNTIME_DIR", None)
    env.pop("BK_QC_OFFLINE", None)
    env.update({k: v for k, v in env_overrides.items() if v is not None})
    with tempfile.TemporaryDirectory(prefix="guardscript_") as sd:
        script = Path(sd) / script_name
        script.write_text(GUARD_CHILD, encoding="utf-8")
        return subprocess.run([sys.executable, str(script)], cwd=str(HERE), env=env, capture_output=True,
                              text=True, timeout=120).stdout.strip()


def main() -> int:
    rs = reach_set()
    bad = [(rel, isolation_problem(src)) for rel, src in rs if isolation_problem(src)]
    check(len(rs) >= 15 and not bad,
          f"S every QC that can reach an NBA publisher/lock/receipt isolates its runtime first ({len(rs)} QCs) {bad}")
    NOTES.append("S reach set: " + ", ".join(rel for rel, _ in rs))

    with tempfile.TemporaryDirectory(prefix="qc_runtime_iso_") as qt, \
            tempfile.TemporaryDirectory(prefix="notqc_runtime_") as nt:
        for label, env, name, want in (
                ("unset, under qc_offline", {"BK_QC_OFFLINE": "1"}, "child.py", "REFUSED"),
                ("POSIX production default, under qc_offline", {"BK_QC_OFFLINE": "1",
                                                                "BK_RUNTIME_DIR": "/opt/bankrollkings-runtime"},
                 "child.py", "REFUSED"),
                ("non-qc temp dir, qc_*.py main script", {"BK_RUNTIME_DIR": nt}, "qc_child.py", "REFUSED"),
                ("unset, qc_*.py main script (no wrapper)", {}, "qc_child.py", "REFUSED"),
                ("qc_* temp runtime, under qc_offline", {"BK_QC_OFFLINE": "1", "BK_RUNTIME_DIR": qt}, "child.py", "OK"),
        ):
            out = run_guard(env, name)
            check(out.startswith(want), f"G {label} -> {want} ({out[:90]})")

        iso_child = (
            "import os, sys; sys.path.insert(0, os.getcwd());"
            "from services.qc_runtime import isolate_runtime as i; p = i(); "
            "print(os.environ['BK_RUNTIME_DIR']); print(oct(os.stat(p).st_mode & 0o777))")
        for label, start, expect_keep in (("production default", "/opt/bankrollkings-runtime", False),
                                          ("unset", None, False), ("existing qc temp", qt, True)):
            env = dict(os.environ)
            env.pop("BK_RUNTIME_DIR", None)
            if start:
                env["BK_RUNTIME_DIR"] = start
            out = subprocess.run([sys.executable, "-c", iso_child], cwd=str(HERE), env=env, capture_output=True,
                                 text=True, timeout=60).stdout.split()
            got = out[0] if out else ""
            ok = (got == qt) if expect_keep else ("qc_runtime_" in got and got != start)
            check(ok, f"I isolate_runtime with {label}: {'kept' if expect_keep else 'replaced by a fresh qc_runtime_* dir'} ({got})")
            if not expect_keep and len(out) > 1 and os.name != "nt":
                check(out[1] == "0o700", f"I fresh runtime dir is 0700 ({out[1]})")
        if os.name == "nt":
            NOTES.append("I 0700 mode check runs on POSIX only (Windows has no POSIX modes)")

    # M -- mutation: removing / misplacing the call is flagged
    rel, src = rs[0]
    removed = src.replace("_isolate_runtime()  #", "pass  #", 1)
    check(isolation_problem(removed) is not None, f"M {rel} without the isolation call is FLAGGED")
    late = "import fetch_game_lines\n" + src
    check(isolation_problem(late) is not None, f"M {rel} importing a reach module before isolating is FLAGGED")

    print("=" * 64)
    print("QC: RUNTIME ISOLATION (no QC touches the production runtime)")
    print("=" * 64)
    for n in NOTES:
        print(f"[OK]   {n}")
    for f in FAILS:
        print(f"[FAIL] {f}")
    print(f"\n{len(NOTES)} passed, {len(FAILS)} failed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
