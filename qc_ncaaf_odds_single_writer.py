"""Adversarial QC: NCAAF odds/schedule artifacts have exactly ONE writer each, and CFBD never carries a
price (F7, docs/f7_ncaaf_odds_writers_proposal.md; owner decisions Q-B / fabricated-price removal).

Governed artifacts and their sole approved producer:
  Odds API (fetch_game_lines.py:main)            data/odds/NCAAF_Odds.csv, data/schedules/NCAAF_Odds.csv,
                                                 data/schedules/NCAAF_Schedule.csv
  CFBD (fetch_ncaaf_slate_cfbd.py:publish)       data/odds/NCAAF_CFBD_Lines.csv,
                                                 data/schedules/NCAAF_CFBD_Schedule.csv,
                                                 data/tracking/NCAAF_CFBD_publish.json

Proves:
  a. repo-wide writer inventory (AST over every tracked .py + text scan of tracked .sh / batch/*.bat) is
     exactly the approved producer per artifact. Extends the qc_nfl_roster_single_writer scanner, which
     would have MISSED both F7 writers: atomic_write_csv / csv writers count as writes, `for` targets over
     a tainted iterable are tainted, `with open(..) as fh` taints fh, and a function that RETURNS a
     governed path taints its call sites;
  b. no tracked production .py assigns a literal number to SpreadOdds/OverOdds/UnderOdds/AwayML/HomeML,
     and no producer writes a "CFBD consensus" book (scan) + the CFBD writer's output has no price column
     and no -110 anywhere (behavioral);
  c. the CFBD writer, on HTTP 429 (first call or /lines only), on a non-429 HTTP error, and on zero
     games, publishes NOTHING (no header-only file, existing artifacts byte/inode/mtime identical), exits
     non-zero on any request failure, and its 429 output trips refresh_cfb_data's quota latch detector;
     legacy Odds-API files are untouched even on success; no temp files are left behind;
  d. market/play readers (load_ncaaf_game_market_odds / load_ncaaf_schedule / build_football_live_games
     on them / _cfb_form_legs / the totals board) never surface a CFBD row, even with pre-F7 residue
     (Book='CFBD consensus', -110) still on disk;
  e. context readers (load_ncaaf_context_slate -> Best Spots / Big Favorites / totals pace / CFB matchup
     card) show a CFBD line labeled exactly `CFBD consensus — no book price`, with every price None;
     only those context builders call the composer;
  f. mutation: re-inserting the old legacy-path write loop, or re-introducing -110 prices in the CFBD
     writer, or removing the market firewall, FAILS this QC.

Synthetic only: fake transports, throwaway temp trees, no network. `app` is imported (no server)."""
from __future__ import annotations

import ast
import contextlib
import hashlib
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import types
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent
LABEL = "CFBD consensus — no book price"
GROUPS = {
    "odds_api": {"names": ("NCAAF_Odds.csv", "NCAAF_Schedule.csv"),
                 "approved": {("fetch_game_lines.py", "main")}},
    "cfbd": {"names": ("NCAAF_CFBD_Lines.csv", "NCAAF_CFBD_Schedule.csv", "NCAAF_CFBD_publish.json"),
             "approved": {("fetch_ncaaf_slate_cfbd.py", "publish")}},
}
PRICE_KEYS = {"SpreadOdds", "OverOdds", "UnderOdds", "AwayML", "HomeML"}
CONTEXT_BUILDERS = {"build_cfb_best_spots_context", "build_cfb_big_favorites_context",
                    "build_cfb_totals_context", "build_cfb_matchup_context"}

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


# ---- a. static writer inventory (extended scanner) ----------------------------------------------------
_WRITE_FUNCS = {"urlretrieve", "to_parquet", "to_csv", "to_json", "replace", "rename", "copy", "copy2",
                "copyfile", "copyfileobj", "move", "write_bytes", "write_text", "symlink", "link", "truncate",
                "touch", "atomic_write_csv", "publish_json", "DictWriter", "writer", "dump"}
_PATH_METHODS = {"write_bytes", "write_text", "replace", "rename", "touch", "truncate", "symlink_to",
                 "hardlink_to"}


def _mentions(node, names, tainted):
    for n in ast.walk(node):
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and any(g in n.value for g in names):
            return True
        if isinstance(n, ast.Name) and n.id in tainted:
            return True
        if isinstance(n, ast.Attribute) and n.attr in tainted:
            return True
    return False


def _reads_data(value):
    for n in ast.walk(value):
        if isinstance(n, ast.Call):
            f = n.func
            name = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else "")
            if name.startswith(("read", "load")):
                return True
    return False


def _target_names(t):
    for nm in ast.walk(t):
        name = nm.id if isinstance(nm, ast.Name) else (nm.attr if isinstance(nm, ast.Attribute) else None)
        if name:
            yield name


def _taint(body_nodes, names, tainted):
    """Names bound from a governed PATH expression, to a fixed point: Assign/AnnAssign, `for` targets over
    a tainted iterable, comprehension targets, and `with open(<governed>) as fh` handles."""
    changed = True
    while changed:
        changed = False
        for n in body_nodes:
            for a in ast.walk(n):
                pairs = []
                if isinstance(a, (ast.Assign, ast.AnnAssign)) and a.value is not None:
                    targets = a.targets if isinstance(a, ast.Assign) else [a.target]
                    if _mentions(a.value, names, tainted) and not _reads_data(a.value):
                        pairs = targets
                elif isinstance(a, (ast.For, ast.AsyncFor, ast.comprehension)):
                    if _mentions(a.iter, names, tainted) and not _reads_data(a.iter):
                        pairs = [a.target]
                elif isinstance(a, ast.withitem) and a.optional_vars is not None:
                    if _mentions(a.context_expr, names, tainted) and not _reads_data(a.context_expr):
                        pairs = [a.optional_vars]
                for t in pairs:
                    for name in _target_names(t):
                        if name not in tainted:
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


def _path_returning_funcs(tree, names, base):
    """Functions whose `return` value mentions a governed path -> their names taint call sites."""
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and not n.name.startswith(("read", "load")):
            local = _taint([n], names, set(base))
            if any(isinstance(r, ast.Return) and r.value is not None and _mentions(r.value, names, local)
                   and not _reads_data(r.value) for r in ast.walk(n)):
                out.add(n.name)
    return out


def writers_in_source(src, fname, names):
    tree = ast.parse(src)
    top = [n for n in tree.body if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
    module_tainted = _taint(top, names, set())
    module_tainted |= _path_returning_funcs(tree, names, module_tainted)
    found = set()
    scopes = [("<module>", top)]
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            scopes.append((n.name, [n]))
    for scope, nodes in scopes:
        tainted = _taint(nodes, names, set(module_tainted))
        for n in nodes:
            for c in ast.walk(n):
                if not (isinstance(c, ast.Call) and _is_write_call(c)):
                    continue
                parts = list(c.args) + [k.value for k in c.keywords]
                if isinstance(c.func, ast.Attribute) and c.func.attr in _PATH_METHODS:
                    parts.append(c.func.value)
                if any(_mentions(p, names, tainted) for p in parts):
                    found.add((fname, scope))
    return found


def tracked(*patterns):
    out = subprocess.run(["git", "-c", "core.quotepath=off", "ls-files", "-z", *patterns], cwd=REPO,
                         capture_output=True, text=True, encoding="utf-8")
    return [REPO / p for p in out.stdout.split("\0") if p and (REPO / p).is_file()]


def inventory(names, override=None):
    """{prod writers}, {qc fixture writers}, [parse errors], [script writers]. `override` maps a repo-
    relative path to replacement source (mutation runs)."""
    prod, fixture, errors = set(), set(), []
    for path in tracked("*.py"):
        rel = path.relative_to(REPO).as_posix()
        if rel.startswith("_attic/"):
            continue
        try:
            src = (override or {}).get(rel) or path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if not any(g in src for g in names):
            continue
        try:
            w = writers_in_source(src, rel, names)
        except SyntaxError as exc:
            errors.append(f"{rel}: {exc}")
            continue
        (fixture if path.name.startswith("qc_") else prod).update(w)
    scripts = []
    for path in tracked("*.sh", "*.bat"):
        for i, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            s = line.strip()
            if not any(g in s for g in names) or s.startswith(("#", "REM", "rem", "::")):
                continue
            if any(t in f" {s} " for t in (" cp ", " mv ", " copy ", " move ", ">", " -o ", "wget", " install ",
                                            " tee ", " ln ", "--output", "--schedules-output",
                                            "--schedule-alias-output")):
                scripts.append(f"{path.relative_to(REPO).as_posix()}:{i}")
    return prod, fixture, errors, scripts


print("=" * 80)
print("QC: NCAAF odds single-writer + no fabricated CFBD prices (F7)")
print("=" * 80)

print("--- a. repository-wide writer inventory (per artifact group) ---")
for gname, g in GROUPS.items():
    prod, fixture, errs, scripts = inventory(g["names"])
    print(f"  [{gname}] production writers: {sorted(prod)}")
    print(f"  [{gname}] QC fixture writers (temp trees only): {sorted(fixture) or 'none'}")
    ok(not errs, f"[{gname}] every tracked .py referencing the artifacts parsed ({errs or 'all'})")
    ok(prod == g["approved"], f"[{gname}] production writer inventory == {sorted(g['approved'])} exactly")
    ok(not scripts, f"[{gname}] no tracked .sh/.bat writes or --output-redirects the artifacts ({scripts or 'none'})")

# scanner self-test: the two constructs the roster QC missed
_selftest = '''
from services.atomic_csv import atomic_write_csv
def w1(df):
    p = BASE / "NCAAF_Odds.csv"
    atomic_write_csv(df, p)
def w2(rows):
    for p in (ROOT / "NCAAF_Odds.csv", ROOT / "x.csv"):
        with open(p, "w") as fh:
            pass
'''
st = writers_in_source(_selftest, "t.py", GROUPS["odds_api"]["names"])
ok(("t.py", "w1") in st, "scanner self-test: atomic_write_csv(df, <governed>) is a write")
ok(("t.py", "w2") in st, "scanner self-test: open(<for-loop target over governed paths>, 'w') is a write")

# ---- b. literal-price scan ------------------------------------------------------------------------------
print("--- b. no literal price is written anywhere in production code ---")


def _is_num_const(v):
    if isinstance(v, ast.UnaryOp) and isinstance(v.op, (ast.USub, ast.UAdd)):
        v = v.operand
    return isinstance(v, ast.Constant) and isinstance(v.value, (int, float)) and not isinstance(v.value, bool)


def literal_price_sites(src, rel):
    hits = []
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.Dict):
            for k, v in zip(n.keys, n.values):
                if isinstance(k, ast.Constant) and k.value in PRICE_KEYS and _is_num_const(v):
                    hits.append(f"{rel}:{n.lineno} {{'{k.value}': literal}}")
        elif isinstance(n, ast.Assign) and _is_num_const(n.value):
            for t in n.targets:
                if isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant) and t.slice.value in PRICE_KEYS:
                    hits.append(f"{rel}:{n.lineno} [...]['{t.slice.value}'] = literal")
        elif isinstance(n, ast.Call):
            for kw in n.keywords:
                if kw.arg in PRICE_KEYS and _is_num_const(kw.value):
                    hits.append(f"{rel}:{n.lineno} {kw.arg}=literal")
    return hits


def scan_literal_prices(override=None):
    hits, cfbd_book = [], []
    for path in tracked("*.py"):
        rel = path.relative_to(REPO).as_posix()
        if path.name.startswith("qc_") or rel.startswith(("_attic/", "research/")):
            continue
        try:
            src = (override or {}).get(rel) or path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if not any(k in src for k in PRICE_KEYS) and "CFBD consensus" not in src:
            continue
        try:
            hits += literal_price_sites(src, rel)
        except SyntaxError:
            continue
        if path.name.startswith(("fetch_", "refresh_", "build_")) and re.search(r"['\"]Book['\"]\s*:\s*['\"]CFBD", src):
            cfbd_book.append(rel)
    return hits, cfbd_book


lit_hits, cfbd_book_writers = scan_literal_prices()
ok(not lit_hits, f"no production code assigns a literal number to a price column ({lit_hits or 'none'})")
ok(not cfbd_book_writers, f"no producer writes a 'CFBD consensus' Book ({cfbd_book_writers or 'none'})")
_known = []
for rel in ("app.py",):
    for i, line in enumerate((REPO / rel).read_text(encoding="utf-8").splitlines(), 1):
        if "'price': -110" in line:
            _known.append(f"{rel}:{i}")
print(f"  [info] KNOWN OPEN, outside the CFBD-row contract (owner decision; not counted): "
      f"leg builders still default 'price': -110 at {_known or 'none'}")

# ---- c. CFBD writer behavior ---------------------------------------------------------------------------
print("--- c. CFBD writer: CFBD-owned artifacts only, fail closed, no header-only file ---")
import fetch_ncaaf_slate_cfbd as cfbd  # noqa: E402

_saved_env = dict(os.environ)
import refresh_cfb_data  # noqa: E402  (loads .env into os.environ at import; restored below)
os.environ.clear()
os.environ.update(_saved_env)

try:
    from zoneinfo import ZoneInfo
    _ET = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover
    _ET = timezone(timedelta(hours=-4))
TODAY = datetime.now(_ET).date()


def _iso(d, hh, mm=0):
    return datetime(d.year, d.month, d.day, hh, mm, tzinfo=_ET).astimezone(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.000Z")


WEEK1 = [
    {"id": 401, "startDate": _iso(TODAY, 19, 30), "homeTeam": "Alabama", "awayTeam": "Georgia",
     "homeConference": "SEC", "awayConference": "SEC"},
    {"id": 402, "startDate": _iso(TODAY, 12), "homeTeam": "Army", "awayTeam": "Troy",
     "homeConference": "American Athletic", "awayConference": "Sun Belt"},
    {"id": 403, "startDate": _iso(TODAY, 15), "homeTeam": "Yale", "awayTeam": "Harvard",
     "homeConference": "Ivy", "awayConference": "Ivy"},   # FCS-only -> excluded
]
LINES1 = [
    {"id": 401, "lines": [{"provider": "Bovada", "spread": -3.5, "overUnder": 51.5,
                           "homeMoneyline": -170, "awayMoneyline": 145, "spreadOdds": -110},  # synthetic-fixture
                          {"provider": "DraftKings", "spread": -2.5, "overUnder": 50.5,
                           "homeMoneyline": -150, "awayMoneyline": 130}]},
    {"id": 402, "lines": [{"provider": "Bovada", "spread": -4.5, "overUnder": 44.0},
                          {"provider": "ESPN Bet", "spread": -3.5, "overUnder": 45.0}]},
]
WEEK2 = [{"id": 501, "startDate": _iso(TODAY + timedelta(days=60), 12), "homeTeam": "LSU",
          "awayTeam": "Auburn", "homeConference": "SEC", "awayConference": "SEC"}]


def _http(code, msg):
    return urllib.error.HTTPError("https://api.collegefootballdata.com/x", code, msg, {}, None)


def fake_getter(mode="ok"):
    def get(url, key):
        wk = int(re.search(r"week=(\d+)", url).group(1))
        if "/games" in url:
            if mode == "429_first":
                raise _http(429, "Too Many Requests")
            if mode == "500" and wk == 1:
                raise _http(500, "Server Error")
            if mode == "zero":
                return []
            return WEEK1 if wk == 1 else (WEEK2 if wk == 2 else [])
        if "/lines" in url:
            if mode == "429_lines":
                raise _http(429, "Too Many Requests")
            return LINES1 if wk == 1 else []
        raise AssertionError(url)
    return get


class Tree:
    def __init__(self, seed_legacy=True, seed_cfbd=False):
        self.root = Path(tempfile.mkdtemp(prefix="qc_f7_"))
        for d in ("data/odds", "data/schedules", "data/tracking"):
            (self.root / d).mkdir(parents=True)
        self.legacy = [self.root / "data/odds/NCAAF_Odds.csv", self.root / "data/schedules/NCAAF_Odds.csv",
                       self.root / "data/schedules/NCAAF_Schedule.csv"]
        self.cfbd = list(cfbd.paths(self.root).values())
        past = 1_600_000_000
        if seed_legacy:
            for p in self.legacy:
                p.write_text("Date,Time,Away,Home,Book\n2026-01-01,12:00,A Team,B Team,DraftKings\n",
                             encoding="utf-8")
                os.utime(p, (past, past))
        if seed_cfbd:
            for p in self.cfbd:
                p.write_text("seed-last-known-good\n", encoding="utf-8")
                os.utime(p, (past, past))

    def fp(self, paths):
        out = {}
        for p in paths:
            if p.exists():
                st = p.stat()
                out[p.name + str(p.parent.name)] = (hashlib.sha256(p.read_bytes()).hexdigest(), st.st_ino,
                                                    st.st_size, st.st_mtime_ns)
            else:
                out[p.name + str(p.parent.name)] = None
        return out

    def leftovers(self):
        return sorted(str(p.relative_to(self.root)) for p in self.root.rglob("*.tmp"))

    def listing(self):
        return sorted(str(p.relative_to(self.root)) for p in self.root.rglob("*") if p.is_file())

    def close(self):
        shutil.rmtree(self.root, ignore_errors=True)


def run_writer(tree, mode, module=cfbd):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = module.run(2026, 12, key="fake", getter=fake_getter(mode), root=tree.root, today=TODAY)
    return rc, out.getvalue() + "\n" + err.getvalue()


def success_checks(module, label_prefix=""):
    """Returns list of (cond, label) for the success scenario against `module`."""
    t = Tree(seed_legacy=True)
    try:
        before_legacy = t.fp(t.legacy)
        try:
            rc, text = run_writer(t, "ok", module)
        except Exception as exc:  # noqa: BLE001 -- a broken mutant counts as a failed check
            rc, text = -1, repr(exc)
        P = module.paths(t.root)
        res = [(rc == 0, f"{label_prefix}success: exit 0"),
               (t.fp(t.legacy) == before_legacy, f"{label_prefix}success: legacy Odds-API files sha256/inode/size/mtime unchanged"),
               (all(P[k].exists() for k in ("schedule", "lines", "manifest")),
                f"{label_prefix}success: all three CFBD-owned artifacts published")]
        if P["lines"].exists() and P["schedule"].exists():
            lines, sched = pd.read_csv(P["lines"]), pd.read_csv(P["schedule"])
            raw = P["lines"].read_text(encoding="utf-8") + P["schedule"].read_text(encoding="utf-8")
            res += [
                (not (PRICE_KEYS | {"Book"}) & set(lines.columns) and not (PRICE_KEYS | {"Book"}) & set(sched.columns),
                 f"{label_prefix}success: no price/Book column in either CFBD artifact"),
                ("-110" not in raw, f"{label_prefix}success: no -110 anywhere in the CFBD artifacts"),
                ((lines["Source"] == "CFBD").all() and (sched["Source"] == "CFBD").all(),
                 f"{label_prefix}success: Source=='CFBD' on every row"),
                ({"ProviderName", "FetchedAtUTC"} <= set(lines.columns),
                 f"{label_prefix}success: provenance columns ProviderName + FetchedAtUTC present"),
                (len(lines) == 4 and set(sched["CfbdGameId"]) == {401, 402},
                 f"{label_prefix}success: one row per (game, provider), FCS-only game excluded"),
                (sched["Time"].astype(str).str.fullmatch(r"\d{2}:\d{2}").all(),
                 f"{label_prefix}success: Time is 24h HH:MM ET (aligned with the Odds API feed)"),
            ]
        else:
            res.append((False, f"{label_prefix}success: CFBD artifacts readable"))
        res.append((t.leftovers() == [], f"{label_prefix}success: no temp files left behind"))
        return res
    finally:
        t.close()


for cond, label in success_checks(cfbd):
    ok(cond, label)

for mode, desc, quota in (("429_first", "HTTP 429 on the first /games call", True),
                          ("429_lines", "HTTP 429 on /lines only", True),
                          ("500", "HTTP 500 on /games", False)):
    t = Tree(seed_legacy=True, seed_cfbd=True)
    try:
        before, listing = t.fp(t.legacy + t.cfbd), t.listing()
        rc, text = run_writer(t, mode)
        ok(rc != 0, f"{desc}: exit non-zero (rc={rc})")
        ok(t.fp(t.legacy + t.cfbd) == before and t.listing() == listing,
           f"{desc}: nothing published; legacy + last-known-good CFBD artifacts identical")
        ok(t.leftovers() == [], f"{desc}: no temp files left behind")
        ok(refresh_cfb_data._is_provider_quota_exhausted(text) is quota,
           f"{desc}: refresh_cfb_data quota detector -> {quota}")
    finally:
        t.close()
for seed in (False, True):
    t = Tree(seed_legacy=True, seed_cfbd=seed)
    try:
        before, listing = t.fp(t.legacy + t.cfbd), t.listing()
        rc, _ = run_writer(t, "zero")
        ok(rc == 0 and t.fp(t.legacy + t.cfbd) == before and t.listing() == listing,
           f"zero in-window games ({'existing' if seed else 'no'} CFBD artifacts): exit 0, NO header-only file, nothing changed")
    finally:
        t.close()
ok(cfbd.validate(pd.DataFrame([{"Source": "CFBD", "SpreadOdds": -110}]), pd.DataFrame()) != [],  # synthetic-fixture
   "CFBD validator rejects any price column")
ok(any("zero rows" in e for e in cfbd.validate(pd.DataFrame(columns=cfbd.SCHEDULE_COLS),
                                                pd.DataFrame(columns=cfbd.LINES_COLS))),
   "CFBD validator refuses a header-only schedule")

# ---- d/e. readers -------------------------------------------------------------------------------------
print("--- d. market/play readers never surface a CFBD row ---")
# app refuses to import without SECRET_KEY (a gitignored .env supplies it on real hosts). A throwaway
# QC-only value lets the import proceed in a clean checkout; nothing is served or signed with it.
os.environ.setdefault("SECRET_KEY", "qc-ncaaf-single-writer-not-a-secret")
import app as appmod  # noqa: E402

DAY = appmod.sports_today_ts().strftime("%Y-%m-%d")
R = Path(tempfile.mkdtemp(prefix="qc_f7_app_"))
for d in ("odds", "schedules"):
    (R / d).mkdir(parents=True)
fresh = datetime.now(_ET).strftime("%Y-%m-%dT%H:%M:%S")
# The writer's L1 format (fetch_game_lines.build_dataframe): legacy columns + each spread side as its own
# selection + zone-explicit SourceUpdatedAtUTC / FetchedAtUTC. Freshness is the BK observation time.
_obs_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
W1_COLS = ["Date", "Time", "Away", "Home", "AwayFull", "HomeFull", "AwayML", "HomeML", "Spread", "SpreadOdds",
           "Total", "OverOdds", "UnderOdds", "Book", "GameID", "LastUpdated",
           "HomeSpread", "HomeSpreadOdds", "AwaySpread", "AwaySpreadOdds", "EventId", "EventCommenceAtUTC",
           "SourceUpdatedAtUTC", "FetchedAtUTC"]
legacy = pd.DataFrame([
    [DAY, "19:30", "Georgia Bulldogs", "Alabama Crimson Tide", "Georgia Bulldogs", "Alabama Crimson Tide",
     135, -155, -3.0, -108, 51.0, -112, -108, "DraftKings", "abc123def", fresh,
     -3.0, -108, 3.0, -112, "abc123def", "", _obs_utc, _obs_utc],
    # pre-F7 residue: the old CFBD writer's row for a game the Odds API does not cover
    [DAY, "12:00 PM", "Troy", "Army", "Troy", "Army", 150, -170, -4.0, -110, 44.5, -110, -110,  # synthetic-fixture
     "CFBD consensus", "402", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
     -4.0, -110, 4.0, -110, "402", "", _obs_utc, _obs_utc],  # synthetic-fixture
], columns=W1_COLS)
for p in ("odds/NCAAF_Odds.csv", "schedules/NCAAF_Odds.csv"):
    legacy.to_csv(R / p, index=False)
legacy[["Date", "Time", "Away", "Home"]].to_csv(R / "schedules/NCAAF_Schedule.csv", index=False)

_saved_data_dir = appmod.DATA_DIR
appmod.DATA_DIR = R
try:
    mo = appmod.load_ncaaf_game_market_odds()
    ms = appmod.load_ncaaf_schedule()
    ok(not mo.empty and not mo["Book"].astype(str).str.contains("CFBD", case=False).any(),
       "load_ncaaf_game_market_odds: CFBD residue row dropped, Odds API row kept")
    ok(not (mo[[c for c in PRICE_KEYS if c in mo.columns]] == -110).any().any(),  # synthetic-fixture
       "load_ncaaf_game_market_odds: no -110 reaches a market reader")
    ok("Book" not in ms.columns or not ms["Book"].astype(str).str.contains("CFBD", case=False).any(),
       "load_ncaaf_schedule: CFBD-book residue dropped from the schedule frame")
    mg = appmod.build_football_live_games(mo, ms, date_filter="all")
    troy = [g for g in mg if "Troy" in str(g.get("away"))]
    ok(all("CFBD" not in str(g.get("book")) for g in mg), "build_football_live_games (market loaders): no CFBD book")
    ok(all(pd.isna(pd.to_numeric(g.get("spread"), errors="coerce")) for g in troy),
       "build_football_live_games (market loaders): CFBD-only game carries NO line on a market surface")
    ok(all(not g.get("line_label") for g in mg), "market games never carry the CFBD context label")
    legs = appmod._cfb_form_legs(limit=20)
    ok(all("Troy" not in str(l.get("game")) for l in legs), "_cfb_form_legs (card/parlay legs): no CFBD-only game")
    tb = appmod.build_cfb_totals_board_context("today", "all")
    ok(all("Troy" not in str(r.get("away")) for r in tb.get("tb_rows", [])),
       "build_cfb_totals_board_context (market totals): no CFBD-only game")

    print("--- e. context readers: CFBD consensus labeled, never priced ---")
    (R / "schedules/NCAAF_CFBD_Schedule.csv").unlink(missing_ok=True)
    o0, s0 = appmod.load_ncaaf_context_slate()
    ok(("Source" not in o0.columns) or not (o0["Source"] == "CFBD").any(),
       "no CFBD artifact -> composer degrades to Odds-API rows only (identical to the market binding)")
    t = Tree(seed_legacy=False)
    try:
        rc, _ = run_writer(t, "ok")
        for k in ("schedule", "lines"):
            src = cfbd.paths(t.root)[k]
            dst = R / src.parent.name / src.name
            shutil.copy2(src, dst)
    finally:
        t.close()
    co, cs = appmod.load_ncaaf_context_slate()
    cf = co[co["Source"] == "CFBD"]
    oa = co[co["Source"] == "odds_api"]
    ok(len(oa) == 1 and oa.iloc[0]["Away"] == "Georgia" and oa.iloc[0]["Book"] == "DraftKings"
       and float(oa.iloc[0]["SpreadOdds"]) == -108,
       "composer: Odds API row matched to CFBD school names (Georgia Bulldogs -> Georgia), real book + price kept")
    ok(len(cf) == 1 and cf.iloc[0]["Away"] == "Troy" and cf.iloc[0]["Book"] == LABEL,
       f"composer: CFBD-only game labeled exactly '{LABEL}'")
    ok(len(cf) == 1 and cf[list(PRICE_KEYS)].isna().all().all(), "composer: every CFBD price field is None")
    ok(len(cf) == 1 and float(cf.iloc[0]["Spread"]) in (-4.5, -3.5) and float(cf.iloc[0]["Spread"]) == -4.5,
       "composer: CFBD consensus is a POSTED provider value (lower median -4.5), never an average (-4.0)")
    cg = appmod.build_football_live_games(co, cs, date_filter="all")
    ctroy = [g for g in cg if g.get("away") == "Troy"]
    ok(len(ctroy) == 1 and ctroy[0]["line_label"] == LABEL and ctroy[0]["book"] == LABEL
       and ctroy[0]["away_ml"] is None and ctroy[0]["home_ml"] is None and LABEL in ctroy[0]["summary"],
       "context game row: line_label/book/summary carry the label; no ML")
    mu = appmod.build_cfb_matchup_context().get("mu_week", [])
    mtroy = [g for g in mu if g.get("away") == "Troy"]
    ok(len(mtroy) == 1 and mtroy[0].get("line_label") == LABEL, "CFB matchup card week list labels the CFBD line")
    ok(any(g.get("away") == "Georgia" and not g.get("line_label") for g in mu),
       "CFB matchup card: Odds-API line carries no CFBD label")
    tp = appmod.build_cfb_totals_context().get("to_week", [])
    ok(all(r.get("line_label") in ("", LABEL) for r in tp), "totals pace rows carry line_label (when profiles exist)")
    bf = appmod.build_cfb_big_favorites_context("week", 20)
    ok(isinstance(bf.get("bf_rows"), list), "Big Favorites context builds on the composer")
    # The real template markup renders the label. The full pages extend the authed shell (nav context
    # needs a signed-in request), so render the exact slate-loop block of each template in app's Jinja env.
    def _render_block(tpl, start, stop, suffix="", **ctx):
        """Render template text from `start` up to (excluding) `stop`, plus `suffix` to close blocks."""
        text = (REPO / "templates" / tpl).read_text(encoding="utf-8")
        i = text.index(start)
        j = text.index(stop, i)
        return appmod.app.jinja_env.from_string(text[i:j] + suffix).render(**ctx)

    try:
        html = _render_block("cfb_matchup.html", "{% if mu_week %}", "<div class=\"card mb-24\">\n  <div class=\"p-16\" style=\"border-bottom",
                             mu_week=mu)
        ok(LABEL in html and html.count(LABEL) == 1,
           "cfb_matchup.html week list renders the exact label once (CFBD game only)")
    except Exception as exc:  # noqa: BLE001
        ok(False, f"cfb_matchup.html block render ({type(exc).__name__}: {exc})")
    try:
        card = {"matchup": "Troy @ Army", "away": "Troy", "home": "Army", "date": DAY, "time": "12:00",
                "spread": "-4.5", "total": 44.0, "headline": "h", "bullets": ["b"], "strength": 1,
                "line_label": ctroy[0]["line_label"] if ctroy else ""}
        html = _render_block("cfb_best_spots.html", "{% for c in bs_live %}", "  {% else %}",
                             bs_live=[card])
        ok(LABEL in html, "cfb_best_spots.html card renders the exact label")
        html = _render_block("cfb_totals.html", "{% if to_week %}", "    </tbody>", suffix="{% endif %}",
                             to_week=[{"away": "Troy", "home": "Army", "time": "12:00", "pace": 70, "proj": 50,
                                       "posted": 44.0, "gap": 6.0, "read": "", "line_label": LABEL}])
        ok(LABEL in html, "cfb_totals.html pace row renders the exact label")
    except Exception as exc:  # noqa: BLE001
        ok(False, f"best spots / totals block render ({type(exc).__name__}: {exc})")
    # market loaders are unaffected by the CFBD artifacts being present
    mo2 = appmod.load_ncaaf_game_market_odds()
    ok(len(mo2) == len(mo) and not mo2["Book"].astype(str).str.contains("CFBD", case=False).any(),
       "market loader output unchanged by CFBD artifacts on disk")

    print("--- e2. composer binding: only context builders call load_ncaaf_context_slate ---")
    tree = ast.parse((REPO / "app.py").read_text(encoding="utf-8"))
    callers = set()
    for fn in ast.walk(tree):
        if isinstance(fn, ast.FunctionDef) and fn.name != "load_ncaaf_context_slate":
            for c in ast.walk(fn):
                if isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id == "load_ncaaf_context_slate":
                    callers.add(fn.name)
    ok(callers == CONTEXT_BUILDERS, f"composer callers == context builders exactly ({sorted(callers)})")

    # ---- f. mutations ---------------------------------------------------------------------------------
    print("--- f. mutations must FAIL this QC ---")
    real_fw = appmod._ncaaf_market_only
    appmod._ncaaf_market_only = lambda df: df
    appmod.DATAFRAME_CACHE.clear()
    try:
        mm = appmod.load_ncaaf_game_market_odds()
        ok(mm["Book"].astype(str).str.contains("CFBD", case=False).any(),
           "mutant (market firewall removed): CFBD -110 row DETECTED on the market reader")
    finally:
        appmod._ncaaf_market_only = real_fw
        appmod.DATAFRAME_CACHE.clear()
finally:
    appmod.DATA_DIR = _saved_data_dir
    shutil.rmtree(R, ignore_errors=True)

W2_REL = "fetch_ncaaf_slate_cfbd.py"
w2_src = (REPO / W2_REL).read_text(encoding="utf-8")
OLD_LOOP = '''
def _legacy_publish(sched_rows, odds_rows):
    import csv
    with open(ROOT / "data" / "schedules" / "NCAAF_Schedule.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["Date", "Time", "Away", "Home"]); w.writeheader(); w.writerows(sched_rows)
    for p in (ROOT / "data" / "odds" / "NCAAF_Odds.csv", ROOT / "data" / "schedules" / "NCAAF_Odds.csv"):
        with open(p, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(odds_rows[0])); w.writeheader(); w.writerows(odds_rows)
'''
mut_prod, *_ = inventory(GROUPS["odds_api"]["names"], override={W2_REL: w2_src + OLD_LOOP})
ok((W2_REL, "_legacy_publish") in mut_prod, "mutant (old legacy write loop): static inventory FLAGS a second writer")

ANCHOR = '"Spread": spread, "Total": total})'
ok(ANCHOR in w2_src, "located the CFBD line-row literal for the -110 mutation")
MUT = w2_src.replace(ANCHOR, '"Spread": spread, "Total": total, "SpreadOdds": -110, "OverOdds": -110, "UnderOdds": -110})')
mut_hits, _ = scan_literal_prices(override={W2_REL: MUT})
ok(any(h.startswith(W2_REL) for h in mut_hits), "mutant (-110 re-introduced): literal-price scan FLAGS it")
mod = types.ModuleType("fetch_ncaaf_slate_cfbd_mutant")
mod.__file__ = str(REPO / W2_REL)
exec(compile(MUT, str(REPO / W2_REL), "exec"), mod.__dict__)  # noqa: S102 -- in-process mutant, test only
mres = success_checks(mod, "mutant: ")
ok(any(not c for c, _ in mres), "mutant (-110 re-introduced): behavioral success checks FAIL (publish refused)")
# and with the validator neutered AND the price columns added back to the contract, the artifact checks
# still catch it
mod.validate = lambda s, l: []
mod.LINES_COLS = mod.LINES_COLS + ["SpreadOdds", "OverOdds", "UnderOdds"]
mres2 = success_checks(mod, "mutant2: ")
ok(any((not c) and ("price" in lab or "-110" in lab) for c, lab in mres2),
   "mutant (-110 + validator removed): artifact price/-110 checks FAIL")

print("=" * 80)
print(f"Clean: {_FAIL == 0}  (ok={_OK} fail={_FAIL})")
sys.exit(1 if _FAIL else 0)
