"""Adversarial QC: the governed NFL roster artifact has exactly ONE publisher (RC 2D1 correction c3).

`data/tracking/_nflverse_stats_<season>.parquet` is published only by fetch_nfl_player_week.py (identity
sanitation + atomic publication). The two graders that need season actuals -- grade_nfl_week._season_df and
refresh_nfl_featured_results (which imports it) -- used to urlretrieve straight onto that path, so every
run_daily ended with the raw, unsanitized file. They must now be READ-ONLY with respect to it.

Proves:
  1. repo-wide writer inventory (AST over every tracked .py + text scan of every tracked .sh) is exactly the
     approved producer; QC fixture writers are listed separately;
  2. neither grader re-implements identity sanitation;
  3. both grader call paths leave an existing artifact's sha256, inode, size and mtime unchanged;
  4. neither path creates the artifact when it is absent;
  5. private temp files are removed on success AND on failure;
  6. a download or parse failure leaves the artifact untouched;
  7. mutating back to the old direct-write behavior FAILS checks 1, 3 and 4.

Synthetic only: the download is stubbed, every write lands in a throwaway temp tree, no network, no app boot."""
from __future__ import annotations

import ast
import hashlib
import inspect
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import types
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent
GOVERNED = "_nflverse_stats_"
APPROVED_WRITERS = {("fetch_nfl_player_week.py", "main")}

_OK = 0
_FAIL = 0


def ok(cond, label):
    global _OK, _FAIL
    if cond:
        _OK += 1
        print(f"  [ok] {label}")
    else:
        _FAIL += 1
        print(f"  [FAIL] {label}")


# ---- static writer inventory --------------------------------------------------------------------------
_WRITE_FUNCS = {"urlretrieve", "to_parquet", "to_csv", "replace", "rename", "copy", "copy2", "copyfile",
                "copyfileobj", "move", "write_bytes", "write_text", "symlink", "link", "truncate", "touch"}
# methods that write THROUGH their receiver path (pathlib); for df.to_parquet(p) the receiver is data
_PATH_METHODS = {"write_bytes", "write_text", "replace", "rename", "touch", "truncate", "symlink_to",
                 "hardlink_to"}


def _mentions_governed(node, tainted):
    for n in ast.walk(node):
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and GOVERNED in n.value:
            return True
        if isinstance(n, ast.Name) and n.id in tainted:
            return True
        if isinstance(n, ast.Attribute) and n.attr in tainted:
            return True
    return False


def _reads_data(value):
    """True for an expression that LOADS the file's contents (read_parquet(p), pd.read_csv(p), ...): its
    result is data, not the path, so it must not carry the path taint."""
    for n in ast.walk(value):
        if isinstance(n, ast.Call):
            f = n.func
            name = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else "")
            if name.startswith(("read", "load")):
                return True
    return False


def _taint(body_nodes, tainted):
    """Names assigned from a PATH expression that mentions the governed artifact (to a fixed point)."""
    changed = True
    while changed:
        changed = False
        for n in body_nodes:
            for a in ast.walk(n):
                if isinstance(a, (ast.Assign, ast.AnnAssign)) and a.value is not None:
                    targets = a.targets if isinstance(a, ast.Assign) else [a.target]
                    if _mentions_governed(a.value, tainted) and not _reads_data(a.value):
                        for t in targets:
                            for nm in ast.walk(t):
                                name = nm.id if isinstance(nm, ast.Name) else (
                                    nm.attr if isinstance(nm, ast.Attribute) else None)
                                if name and name not in tainted:
                                    tainted.add(name)
                                    changed = True
    return tainted


def _is_write_call(call):
    f = call.func
    name = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else None)
    if name == "open":
        mode = call.args[1] if len(call.args) > 1 else next(
            (k.value for k in call.keywords if k.arg == "mode"), None)
        return isinstance(mode, ast.Constant) and isinstance(mode.value, str) and any(
            c in mode.value for c in "wax+")
    return name in _WRITE_FUNCS


def writers_in_source(src, fname):
    """[(file, function)] for every call that writes to a governed-path expression."""
    tree = ast.parse(src)
    module_tainted = _taint([n for n in tree.body if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))],
                            set())
    found = set()
    scopes = [("<module>", [n for n in tree.body if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))])]
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            scopes.append((n.name, [n]))
    for scope, nodes in scopes:
        tainted = _taint(nodes, set(module_tainted))
        for n in nodes:
            for c in ast.walk(n):
                if not (isinstance(c, ast.Call) and _is_write_call(c)):
                    continue
                parts = list(c.args) + [k.value for k in c.keywords]
                if isinstance(c.func, ast.Attribute) and c.func.attr in _PATH_METHODS:
                    parts.append(c.func.value)        # p.write_bytes() / p.rename() write via the receiver
                if any(_mentions_governed(p, tainted) for p in parts):
                    found.add((fname, scope))
    return found


def tracked(pattern):
    out = subprocess.run(["git", "ls-files", pattern], cwd=REPO, capture_output=True, text=True)
    return [REPO / p for p in out.stdout.split()]


print("=" * 80)
print("QC: NFL roster artifact single-writer (RC 2D1 correction c3)")
print("=" * 80)

print("--- 1. repository-wide writer inventory ---")
prod_writers, fixture_writers, parse_errors = set(), set(), []
for path in tracked("*.py"):
    try:
        src = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        continue
    if GOVERNED not in src:
        continue
    try:
        w = writers_in_source(src, path.relative_to(REPO).as_posix())
    except SyntaxError as exc:
        parse_errors.append(f"{path.name}: {exc}")
        continue
    (fixture_writers if path.name.startswith("qc_") else prod_writers).update(w)
sh_writers = []
for path in tracked("*.sh"):
    for i, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        s = line.strip()
        if GOVERNED in s and not s.startswith("#") and any(
                t in f" {s} " for t in (" cp ", " mv ", ">", " -o ", "wget", " install ", " tee ", " ln ")):
            sh_writers.append(f"{path.name}:{i}")
print(f"  production writers: {sorted(prod_writers)}")
print(f"  QC fixture writers (temp trees only): {sorted(fixture_writers) or 'none'}")
ok(not parse_errors, f"every tracked .py referencing the path parsed ({parse_errors or 'all'})")
ok(prod_writers == APPROVED_WRITERS, "production writer inventory == {fetch_nfl_player_week.py:main} exactly")
ok(not sh_writers, f"no tracked shell script writes the governed path ({sh_writers or 'none'})")

print("--- 2. graders do not duplicate sanitation ---")
for g in ("grade_nfl_week.py", "refresh_nfl_featured_results.py"):
    src = (REPO / g).read_text(encoding="utf-8")
    ok(not any(t in src for t in ("sanitize_player_identities", "_all_identity_null_mask", "_governed_null_mask",
                                  "GOVERNED_IDENTITY_COLS")), f"{g} carries no copy of identity sanitation")

# ---- behavioral harness --------------------------------------------------------------------------------
import fetch_nfl_player_week as producer  # noqa: E402
import grade_nfl_week as grader  # noqa: E402

# refresh_nfl_featured_results imports `app` (full Flask boot). Stub ONLY that symbol so the real
# _grade_rows code path runs; nothing else is replaced.
_app_stub = types.ModuleType("app")
_app_stub.build_nfl_spots_context = lambda **_: {"sp_top": []}
_had_app = "app" in sys.modules
_saved_app = sys.modules.get("app")
sys.modules["app"] = _app_stub
import refresh_nfl_featured_results as featured  # noqa: E402
if _had_app:
    sys.modules["app"] = _saved_app
else:
    del sys.modules["app"]
featured._current_week = lambda d: 3

SEASON = 2026
FIXTURE = pd.DataFrame([
    {"player_id": "00-1", "player_display_name": "Alice Alpha", "player_name": "A.Alpha", "season": SEASON,
     "week": 3, "team": "SEA", "receiving_yards": 88.0},
    {"player_id": "00-2", "player_display_name": "Bob Beta", "player_name": "B.Beta", "season": SEASON,
     "week": 3, "team": "BUF", "receiving_yards": 12.0},
    # upstream all-null aggregate row -- exactly what the old direct write leaked into the artifact
    {"player_id": np.nan, "player_display_name": np.nan, "player_name": np.nan, "season": SEASON,
     "week": 3, "team": "DAL", "receiving_yards": 7.0},
])
_fx_dir = Path(tempfile.mkdtemp(prefix="qc_rsw_fx_"))
_fx_path = _fx_dir / "fixture.parquet"
FIXTURE.to_parquet(_fx_path, index=False)
FIXTURE_BYTES = _fx_path.read_bytes()
SANITIZED = FIXTURE.iloc[:2].reset_index(drop=True)


def _ok_download(url, filename, *a, **k):
    Path(filename).write_bytes(FIXTURE_BYTES)
    return filename, None


def _fail_download(url, filename, *a, **k):
    raise OSError("synthetic: provider unreachable")


def _garbage_download(url, filename, *a, **k):
    Path(filename).write_bytes(b"not a parquet file")
    return filename, None


class Tree:
    """Throwaway BASE_DIR for both modules + a private tempfile dir, so every path a writer could touch is
    observable. Restores module globals on exit."""

    def __init__(self, seed: bool):
        self.root = Path(tempfile.mkdtemp(prefix="qc_rsw_"))
        self.tracking = self.root / "data" / "tracking"
        self.tracking.mkdir(parents=True)
        self.private = self.root / "_private_tmp"
        self.private.mkdir()
        self.artifact = self.tracking / f"{GOVERNED}{SEASON}.parquet"
        if seed:
            SANITIZED.to_parquet(self.artifact, index=False)
            past = 1_600_000_000
            os.utime(self.artifact, (past, past))

    def __enter__(self):
        self._saved = (grader.BASE_DIR, producer.BASE_DIR, producer.OUT_DIR, tempfile.tempdir,
                       urllib.request.urlretrieve)
        grader.BASE_DIR = self.root
        producer.BASE_DIR = self.root
        producer.OUT_DIR = self.tracking
        tempfile.tempdir = str(self.private)
        return self

    def __exit__(self, *exc):
        (grader.BASE_DIR, producer.BASE_DIR, producer.OUT_DIR, tempfile.tempdir,
         urllib.request.urlretrieve) = self._saved
        shutil.rmtree(self.root, ignore_errors=True)

    def fingerprint(self):
        if not self.artifact.exists():
            return None
        st = self.artifact.stat()
        return (hashlib.sha256(self.artifact.read_bytes()).hexdigest(), st.st_ino, st.st_size, st.st_mtime_ns)

    def tracking_listing(self):
        return sorted(p.name for p in self.tracking.iterdir())

    def private_leftovers(self):
        return sorted(p.name for p in self.private.iterdir())


PENDING = pd.DataFrame([{"SnapshotDate": f"{SEASON}-09-24", "Player": "Alice Alpha", "Stat": "Rec Yds",
                         "Direction": "OVER", "Line": 70.5, "OutcomeState": "Pending"}])


def run_w2(tree):
    return grader._season_df(SEASON)


def run_w3(tree):
    return featured._grade_rows(PENDING.copy())


PATHS = [("grade_nfl_week._season_df", run_w2), ("refresh_nfl_featured_results._grade_rows", run_w3)]

print("--- 3. W3 is bound to the shared grader loader (no shadow copy) ---")
ok(featured._season_df is grader._season_df,
   "refresh_nfl_featured_results._season_df IS grade_nfl_week._season_df")


def scenario_existing(label, fn, download=_ok_download):
    with Tree(seed=True) as t:
        urllib.request.urlretrieve = download
        before, listing = t.fingerprint(), t.tracking_listing()
        try:
            result, err = fn(t), None
        except Exception as exc:  # noqa: BLE001 -- the failure path is under test
            result, err = None, exc
        return {"unchanged": t.fingerprint() == before, "listing_same": t.tracking_listing() == listing,
                "leftovers": t.private_leftovers(), "result": result, "err": err}


def scenario_absent(fn, download=_ok_download):
    with Tree(seed=False) as t:
        urllib.request.urlretrieve = download
        try:
            fn(t)
        except Exception:  # noqa: BLE001
            pass
        return {"absent": not t.artifact.exists(), "listing_empty": t.tracking_listing() == [],
                "leftovers": t.private_leftovers()}


print("--- 4. existing artifact: sha256 / inode / size / mtime unchanged (success path) ---")
for label, fn in PATHS:
    r = scenario_existing(label, fn)
    ok(r["err"] is None, f"{label}: completes on a good download")
    ok(r["unchanged"], f"{label}: artifact sha256, inode, size and mtime unchanged")
    ok(r["listing_same"], f"{label}: nothing created/renamed under data/tracking")
    ok(r["leftovers"] == [], f"{label}: private temp file removed on success")
    if fn is run_w2:
        ok(isinstance(r["result"], pd.DataFrame) and r["result"].reset_index(drop=True).equals(FIXTURE),
           f"{label}: returns the downloaded frame unmodified (grading semantics preserved)")
    else:
        ok(r["result"].loc[0, "OutcomeState"] == "Hit" and float(r["result"].loc[0, "ResultValue"]) == 88.0,
           f"{label}: the pending play still resolves (88 > 70.5 -> Hit)")

print("--- 5. absent artifact: never created ---")
for label, fn in PATHS:
    r = scenario_absent(fn)
    ok(r["absent"] and r["listing_empty"], f"{label}: governed artifact NOT created when absent")
    ok(r["leftovers"] == [], f"{label}: private temp file removed")

print("--- 6. download / parse failure: artifact untouched, temp cleaned ---")
for kind, dl in (("download failure", _fail_download), ("parse failure", _garbage_download)):
    r = scenario_existing("w2", run_w2, dl)
    ok(isinstance(r["err"], RuntimeError), f"grade_nfl_week._season_df: {kind} raises (callers already catch)")
    ok(r["unchanged"] and r["listing_same"], f"grade_nfl_week._season_df: {kind} leaves artifact untouched")
    ok(r["leftovers"] == [], f"grade_nfl_week._season_df: {kind} removes its private temp file")
    r = scenario_existing("w3", run_w3, dl)
    ok(r["err"] is None and r["result"].loc[0, "OutcomeState"] == "Pending",
       f"refresh_nfl_featured_results: {kind} is caught; play stays Pending")
    ok(r["unchanged"] and r["listing_same"] and r["leftovers"] == [],
       f"refresh_nfl_featured_results: {kind} leaves artifact untouched, temp cleaned")

print("--- 7. mutation: the old direct-write _season_df must FAIL this QC ---")
OLD = textwrap.dedent('''
    def _season_df(season: int) -> pd.DataFrame:
        """Download the season's weekly player stats once and return the full frame."""
        url = STATS_URL.format(season=season)
        tmp = BASE_DIR / "data" / "tracking" / f"_nflverse_stats_{season}.parquet"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(url, tmp)
        return pd.read_parquet(tmp)
''')
cur_src = (REPO / "grade_nfl_week.py").read_text(encoding="utf-8")
new_fn_src = inspect.getsource(grader._season_df)
ok(new_fn_src in cur_src, "located the current _season_df source for substitution")
mut_writers = writers_in_source(cur_src.replace(new_fn_src, OLD.lstrip("\n")), "grade_nfl_week.py")
ok(("grade_nfl_week.py", "_season_df") in mut_writers, "static inventory FLAGS the mutant as a second writer")

ns = {}
exec(OLD, {"pd": pd}, ns)  # noqa: S102 -- in-process mutant, test only
# Bind the mutant to the grader's LIVE module globals, so it resolves BASE_DIR at call time from the
# Tree-patched value (a copied globals dict would capture the real repo BASE_DIR and write into it).
mutant = types.FunctionType(ns["_season_df"].__code__, vars(grader), "_season_df")
REPO_ARTIFACT = REPO / "data" / "tracking" / f"{GOVERNED}{SEASON}.parquet"


def _repo_fp():
    if not REPO_ARTIFACT.exists():
        return None
    st = REPO_ARTIFACT.stat()
    return (hashlib.sha256(REPO_ARTIFACT.read_bytes()).hexdigest(), st.st_ino, st.st_size, st.st_mtime_ns)


repo_before = _repo_fp()
real_w2, real_w3 = grader._season_df, featured._season_df
grader.urllib = urllib
grader._season_df = featured._season_df = mutant
try:
    m_exist = [scenario_existing(label, fn) for label, fn in PATHS]
    m_absent = [scenario_absent(fn) for _, fn in PATHS]
finally:
    grader._season_df, featured._season_df = real_w2, real_w3
    del grader.urllib
ok(_repo_fp() == repo_before, "mutant wrote only inside the throwaway tree (repo artifact untouched)")
ok(all(not r["unchanged"] for r in m_exist), "mutant DETECTED on both paths: existing artifact modified")
ok(all(not r["absent"] for r in m_absent), "mutant DETECTED on both paths: artifact created when absent")
ok(grader._season_df is real_w2 and featured._season_df is real_w2, "real loader restored after mutation run")

shutil.rmtree(_fx_dir, ignore_errors=True)
print("=" * 80)
print(f"Clean: {_FAIL == 0}  (ok={_OK} fail={_FAIL})")
sys.exit(1 if _FAIL else 0)
