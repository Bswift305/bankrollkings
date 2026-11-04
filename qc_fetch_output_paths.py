"""QC: Odds API fetchers resolve ONLY their own sport's paths, and an unconfigured sport fails closed
before any provider request and before any file write (truthfulness safeguard A).

Defect guarded (NCAAB discovery audit): `fetch_game_lines.py --sport basketball_ncaab` resolved its
outputs with `SPORT_OUTPUTS.get(sport, SPORT_OUTPUTS[DEFAULT_SPORT])` -> the NBA files, and the sport/path
token guard returned () for "ncaab" so it was skipped. fetch_player_props.py had the same NBA fallback.

Proves, for fetch_game_lines.py AND fetch_player_props.py:
  A. one explicit table: every configured sport declares every output / receipt / coverage / cache key;
     every resolved file path is the sport's OWN (own league token, unique across sports, under BASE_DIR);
     the configured paths equal the pre-change paths exactly (no behavior change for configured sports);
     basketball_ncaab / basketball_wncaab are absent (explicitly UNCONFIGURED) and resolve/_sport_tokens
     raise UnconfiguredSportError for them and for unknown/empty keys.
  B. adversarial: main() for NCAAB / WNCAAB / unknown / empty / short-form keys (also with --output aimed
     at the NBA file) exits 2 with OUTCOME VALIDATION_FAILED reason_code=UNCONFIGURED_SPORT, never calls
     urlopen / get_json / the fetch functions / the API-key reader / the quota receipt, and leaves a temp
     BASE_DIR byte-for-byte unchanged (pre-seeded NBA + WNBA artifacts identical, no new files).
  C. positive control (proves the harness detects writes): a configured sport with a stubbed provider
     publishes ONLY its own files; the pre-seeded NBA artifacts stay byte-identical.
  D. static scan: no path-resolution code in any tracked fetch_*.py has an NBA default / .get fallback
     onto DEFAULT_SPORT, and the two fixed fetchers have no `.get(sport, ...)` fallback on a path/market
     table and no `sport or DEFAULT_SPORT`; scanner self-test on a re-inserted fallback.

Synthetic only: stubbed transports, throwaway temp trees, no provider request. Run via qc_offline.py.
"""
from __future__ import annotations

import ast
import contextlib
import hashlib
import io
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))

import fetch_game_lines as fgl  # noqa: E402
import fetch_player_props as fpp  # noqa: E402
from services.fetch_sport_guard import (  # noqa: E402
    EXIT_UNCONFIGURED_SPORT, EXPLICITLY_UNCONFIGURED_SPORTS, UnconfiguredSportError,
)
from services.odds_quota import LEDGER_REL  # noqa: E402

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


UNCONFIGURED_KEYS = ["basketball_ncaab", "basketball_wncaab", "BASKETBALL_NCAAB ", "icehockey_nhl",
                     "soccer_epl", "nba", "ncaab", "", "basketball_nba_x"]

# The exact paths each configured sport resolved to BEFORE this change (17b5e69). Configured behavior
# must be identical: a diff here is a behavior change, not a refactor.
LEGACY_GAME_LINES = {
    s: {"odds": f"data/odds/{p}_Odds.csv", "schedules": f"data/schedules/{p}_Odds.csv",
        "schedule_alias": f"data/schedules/{p}_Schedule.csv",
        "line_movement_history": f"data/tracking/{p}_LineMovementHistory.csv",
        "line_movement_current": f"data/tracking/{p}_LineMovementCurrent.csv", "prefix": p}
    for s, p in (("basketball_nba", "NBA"), ("basketball_wnba", "WNBA"), ("americanfootball_nfl", "NFL"),
                 ("americanfootball_ncaaf", "NCAAF"), ("americanfootball_nfl_preseason", "NFL_Preseason"),
                 ("baseball_mlb", "MLB"))
}
LEGACY_PROPS = {
    s: {"props": f"data/props/{p}_Props.csv", "coverage": f"data/tracking/{p}_Props_MarketCoverage.csv",
        "receipt": f"data/tracking/_last_props_fetch_{s}.json", "prefix": p}
    for s, p in (("basketball_nba", "NBA"), ("basketball_wnba", "WNBA"), ("americanfootball_nfl", "NFL"),
                 ("americanfootball_ncaaf", "NCAAF"), ("baseball_mlb", "MLB"))
}


@contextlib.contextmanager
def base_dir(mod, root: Path):
    saved = mod.BASE_DIR
    mod.BASE_DIR = root
    try:
        yield
    finally:
        mod.BASE_DIR = saved


def rel(p: Path, root: Path) -> str:
    return p.resolve().relative_to(root.resolve()).as_posix()


# ---- A. the one table -----------------------------------------------------------------------------------
def check_tables():
    print("--- A. one explicit path table per fetcher; every resolved path is the sport's own ---")
    for name, mod, legacy, req_keys, file_keys, shared in (
            ("fetch_game_lines", fgl, LEGACY_GAME_LINES, fgl.REQUIRED_PATH_KEYS, fgl.FILE_PATH_KEYS, {"receipt"}),
            ("fetch_player_props", fpp, LEGACY_PROPS, fpp.PATH_KEYS, fpp.PATH_KEYS, {"ledger"})):
        ok(not hasattr(mod, "SPORT_OUTPUTS"), f"{name}: the old fallback-bearing SPORT_OUTPUTS table is gone")
        ok(not hasattr(mod, "SPORT_TRACKING_PREFIX"), f"{name}: no second (prefix-derivation) path table")
        ok(set(mod.SPORT_PATHS) == set(legacy),
           f"{name}: configured sports unchanged ({sorted(mod.SPORT_PATHS)})")
        ok(set(mod.SPORT_PATHS) == set(mod.SPORT_DEFAULT_MARKETS),
           f"{name}: every configured sport declares markets and no market entry lacks paths")
        for bad in EXPLICITLY_UNCONFIGURED_SPORTS:
            ok(bad not in mod.SPORT_PATHS and bad not in mod.SPORT_DEFAULT_MARKETS,
               f"{name}: {bad} is explicitly UNCONFIGURED (no paths, no markets)")
        seen: dict[str, str] = {}
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with base_dir(mod, root):
                for sport, entry in mod.SPORT_PATHS.items():
                    missing = [k for k in req_keys if k not in entry]
                    ok(not missing, f"{name}[{sport}]: declares every required key explicitly ({missing or 'all'})")
                    paths = mod.resolve_sport_paths(sport)
                    token = mod._sport_tokens(sport)[0]
                    prefix = legacy[sport]["prefix"]
                    own = True
                    for k in file_keys:
                        p = paths[k]
                        if p is None:
                            continue
                        r = rel(p, root)   # raises if outside BASE_DIR
                        if k in shared:
                            ok(r == LEDGER_REL, f"{name}[{sport}]: {k} is the shared append-only sport-tagged ledger")
                            continue
                        fn_ = Path(r).name
                        if not ((fn_.startswith(f"{prefix}_") and token in fn_) or fn_.endswith(f"_{sport}.json")):
                            own = False
                            print(f"      not own: {k} -> {r}")
                        if r in seen and seen[r] != sport:
                            own = False
                            print(f"      shared with {seen[r]}: {k} -> {r}")
                        seen[r] = sport
                        if k in legacy[sport] and r != legacy[sport][k]:
                            own = False
                            print(f"      differs from pre-change path: {k} -> {r} != {legacy[sport][k]}")
                    ok(own, f"{name}[{sport}]: every resolved path is the sport's own ({token}) and equals the pre-change path")
                    if "tracking_prefix" in paths:
                        ok(paths["tracking_prefix"] == prefix, f"{name}[{sport}]: tracking prefix {prefix} unchanged")
                for key in UNCONFIGURED_KEYS:
                    for fn in ("resolve_sport_paths", "_sport_tokens"):
                        try:
                            getattr(mod, fn)(key)
                            raised = False
                        except UnconfiguredSportError:
                            raised = True
                        ok(raised, f"{name}.{fn}({key!r}) raises UnconfiguredSportError (no fallback, no skipped guard)")


# ---- B. adversarial: fail before network and before writes ----------------------------------------------
def tree_state(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
            for p in sorted(root.rglob("*")) if p.is_file()}


def seed(root: Path) -> None:
    files = {}
    for sport in ("basketball_nba", "basketball_wnba"):
        for k, r in LEGACY_GAME_LINES[sport].items():
            if k != "prefix":
                files[r] = f"Date,Away,Home,Book\n2026-11-04,A,B,{sport}-{k}\n"
        for k, r in LEGACY_PROPS[sport].items():
            if k != "prefix":
                files[r] = f"Player,Stat\nseed,{sport}-{k}\n"
    files[LEDGER_REL] = '{"seed": true}\n'
    for r, text in files.items():
        p = root / r
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")


class Tripwire:
    def __init__(self):
        self.calls: list[str] = []

    def fn(self, label):
        def _f(*a, **k):
            self.calls.append(label)
            raise AssertionError(f"QC tripwire: {label} called for an unconfigured sport")
        return _f


class TripQuota:
    def __init__(self, trip: Tripwire):
        self.trip = trip

    def __getattr__(self, item):
        return self.trip.fn(f"_QUOTA.{item}")


def run_main(mod, argv, patches: dict):
    saved_argv = sys.argv[:]
    saved = {k: getattr(mod, k) for k in patches}
    import urllib.request as ur
    saved_ur = ur.urlopen
    out = io.StringIO()
    try:
        for k, v in patches.items():
            setattr(mod, k, v)
        if "urlopen" in patches:
            ur.urlopen = patches["urlopen"]
        sys.argv = argv
        with contextlib.redirect_stdout(out):
            try:
                rc = mod.main()
            except AssertionError as exc:   # a tripwire fired inside main
                rc = f"tripwire: {exc}"
            except SystemExit as exc:
                rc = exc.code
        return rc, out.getvalue()
    finally:
        sys.argv = saved_argv
        ur.urlopen = saved_ur
        for k, v in saved.items():
            setattr(mod, k, v)


def check_fail_closed():
    print("--- B. unconfigured sport -> exit 2, typed outcome, zero network, zero writes ---")
    plans = (
        ("fetch_game_lines", fgl, ("urlopen", "get_json", "fetch_events", "fetch_odds_rows", "get_api_key",
                                   "append_line_movement_snapshot", "build_dataframe")),
        ("fetch_player_props", fpp, ("urlopen", "get_json", "fetch_events", "fetch_event_props", "get_api_key",
                                     "_write_shape_receipt", "write_market_coverage", "build_dataframe")),
    )
    for name, mod, tripped in plans:
        for key in UNCONFIGURED_KEYS:
            for extra in ((), ("--output", "data/odds/NBA_Odds.csv" if mod is fgl else "data/props/NBA_Props.csv")):
                with tempfile.TemporaryDirectory() as td:
                    root = Path(td)
                    seed(root)
                    if extra:
                        extra = (extra[0], str(root / extra[1]))
                    before = tree_state(root)
                    trip = Tripwire()
                    patches = {k: trip.fn(k) for k in tripped}
                    patches["_QUOTA"] = TripQuota(trip)
                    with base_dir(mod, root):
                        rc, out = run_main(mod, [f"{name}.py", "--api-key", "qc-offline-dummy",
                                                 "--sport", key, *extra], patches)
                    after = tree_state(root)
                    tag = f"{name} --sport {key!r}{' --output <NBA file>' if extra else ''}"
                    ok(rc == EXIT_UNCONFIGURED_SPORT, f"{tag}: exit {EXIT_UNCONFIGURED_SPORT} (got {rc!r})")
                    ok("OUTCOME: VALIDATION_FAILED reason_code=UNCONFIGURED_SPORT" in out,
                       f"{tag}: typed outcome VALIDATION_FAILED / UNCONFIGURED_SPORT printed")
                    ok(not trip.calls, f"{tag}: no network/API-key/quota/fetch/write function called ({trip.calls or 'none'})")
                    ok(before == after, f"{tag}: temp BASE_DIR byte+mtime identical; NBA/WNBA artifacts untouched, no new files")


# ---- C. positive control --------------------------------------------------------------------------------
class OkQuota:
    def print_receipt(self, **kw):
        return True, {}


from datetime import datetime, timedelta, timezone  # noqa: E402

EVENT = {"id": "evt1", "home_team": "Home Team", "away_team": "Away Team",
         "commence_time": (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")}


def fake_lines_json(url):
    return [{**EVENT, "bookmakers": [{"key": "draftkings", "title": "DraftKings", "last_update": "2099-01-01T00:00:00Z",
             "markets": [{"key": "h2h", "outcomes": [{"name": "Home Team", "price": -150}, {"name": "Away Team", "price": 130}]},
                         {"key": "spreads", "outcomes": [{"name": "Home Team", "point": -3.5, "price": -110},
                                                         {"name": "Away Team", "point": 3.5, "price": -110}]},
                         {"key": "totals", "outcomes": [{"name": "Over", "point": 160.5, "price": -110},
                                                        {"name": "Under", "point": 160.5, "price": -110}]}]}]}]


def fake_props_json(url):
    if url.split("?")[0].endswith("/events"):
        return [dict(EVENT)]
    outs = []
    for i in range(6):
        outs += [{"name": "Over", "description": f"Player {i}", "point": 10.5 + i, "price": -110},
                 {"name": "Under", "description": f"Player {i}", "point": 10.5 + i, "price": -110}]
    return {"bookmakers": [{"key": "draftkings", "title": "DraftKings", "last_update": "2099-01-01T00:00:00Z",
                            "markets": [{"key": "player_points", "last_update": "2099-01-01T00:00:00Z",
                                         "outcomes": outs}]}]}


def check_positive_control():
    print("--- C. positive control: a configured sport writes ONLY its own files ---")
    for name, mod, sport, fake, own_prefixes in (
            ("fetch_game_lines", fgl, "basketball_wnba", fake_lines_json,
             ("data/odds/WNBA_", "data/schedules/WNBA_", "data/tracking/WNBA_")),
            ("fetch_player_props", fpp, "basketball_wnba", fake_props_json,
             ("data/props/WNBA_", "data/tracking/WNBA_", "data/tracking/_last_props_fetch_basketball_wnba"))):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            seed(root)
            # the WNBA seeds would trip collapse/validation; the control starts that sport empty
            for p in set(root.rglob("*WNBA*")) | set(root.rglob("*basketball_wnba*")):
                p.unlink(missing_ok=True)
            before = tree_state(root)
            calls = []

            def net(*a, **k):
                calls.append("urlopen")
                raise AssertionError("real urlopen reached")

            patches = {"get_json": fake, "urlopen": net, "_QUOTA": OkQuota()}
            with base_dir(mod, root):
                rc, out = run_main(mod, [f"{name}.py", "--api-key", "qc-offline-dummy", "--sport", sport], patches)
            after = tree_state(root)
            changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
            ok(rc == 0, f"{name}[{sport}] stubbed fetch publishes (rc={rc!r})")
            if rc != 0:
                print("      " + "\n      ".join(out.splitlines()[-15:]))
            ok(not calls, f"{name}[{sport}]: the real urlopen was never reached")
            ok(changed and all(c.startswith(own_prefixes) for c in changed),
               f"{name}[{sport}]: only its own files changed ({changed})")
            ok(all(before[k] == after.get(k) for k in before if "NBA_" in k and "WNBA_" not in k or "basketball_nba" in k),
               f"{name}[{sport}]: every pre-seeded NBA artifact byte-identical")


# ---- D. static scan -------------------------------------------------------------------------------------
PATH_TABLES = {"SPORT_PATHS", "SPORT_OUTPUTS", "SPORT_DEFAULT_MARKETS", "SPORT_TRACKING_PREFIX"}


def fallback_findings(src: str, fname: str, strict: bool) -> list[str]:
    """NBA-default fallbacks in path resolution. Always: any `X[DEFAULT_SPORT]` / `.get(.., DEFAULT_SPORT..)`
    used as a fallback value. strict (the fixed fetchers): also any 2-arg `.get(sport, ...)` on a
    path/market table and any `<x> or DEFAULT_SPORT`."""
    out = []
    tree = ast.parse(src)
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "get" and len(n.args) >= 2:
            default = n.args[1]
            if any(isinstance(x, ast.Name) and x.id == "DEFAULT_SPORT" for x in ast.walk(default)):
                out.append(f"{fname}:{n.lineno} .get(..., <DEFAULT_SPORT fallback>)")
            elif strict and isinstance(n.func.value, ast.Name) and n.func.value.id in PATH_TABLES:
                out.append(f"{fname}:{n.lineno} {n.func.value.id}.get(sport, <fallback>)")
        if isinstance(n, ast.Subscript) and isinstance(n.value, ast.Name) and n.value.id in PATH_TABLES \
                and any(isinstance(x, ast.Name) and x.id == "DEFAULT_SPORT" for x in ast.walk(n.slice)):
            out.append(f"{fname}:{n.lineno} {n.value.id}[DEFAULT_SPORT]")
        if strict and isinstance(n, ast.BoolOp) and isinstance(n.op, ast.Or) and any(
                isinstance(v, ast.Name) and v.id == "DEFAULT_SPORT" for v in n.values):
            out.append(f"{fname}:{n.lineno} `... or DEFAULT_SPORT`")
    return out


def tracked_fetchers():
    res = subprocess.run(["git", "-c", "core.quotepath=off", "ls-files", "-z", "fetch_*.py"], cwd=REPO,
                         capture_output=True, text=True, encoding="utf-8")
    files = [REPO / p for p in res.stdout.split("\0") if p]
    return files or sorted(REPO.glob("fetch_*.py"))


def check_static():
    print("--- D. static scan: no NBA-default / fallback path resolution ---")
    findings = []
    for path in tracked_fetchers():
        strict = path.name in ("fetch_game_lines.py", "fetch_player_props.py")
        findings += fallback_findings(path.read_text(encoding="utf-8"), path.name, strict)
    ok(not findings, f"no fallback path resolution in any tracked fetch_*.py ({findings or 'none'})")
    for path in (REPO / "fetch_game_lines.py", REPO / "fetch_player_props.py"):
        src = path.read_text(encoding="utf-8")
        ok("require_configured_sport" in src and "report_unconfigured" in src,
           f"{path.name}: main/tokens route through the fail-closed guard")
        tree = ast.parse(src)
        main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
        first = {}
        for c in ast.walk(main):
            if isinstance(c, ast.Call) and isinstance(c.func, ast.Name):
                first[c.func.id] = min(first.get(c.func.id, c.lineno), c.lineno)
        ok("resolve_sport_paths" in first and "get_api_key" in first
           and first["resolve_sport_paths"] < first["get_api_key"],
           f"{path.name}: main resolves the sport BEFORE reading the API key / any request")
    # scanner self-test: the exact pre-fix line and the props variant must be caught
    legacy = ("def main():\n    defaults = SPORT_OUTPUTS.get(sport, SPORT_OUTPUTS[DEFAULT_SPORT])\n"
              "    markets = SPORT_DEFAULT_MARKETS.get(sport, SPORT_DEFAULT_MARKETS[DEFAULT_SPORT])\n"
              "    sport = str(args.sport or DEFAULT_SPORT)\n"
              "    p = SPORT_PATHS.get(sport, {})\n")
    got = fallback_findings(legacy, "mut.py", strict=True)
    ok(len(got) >= 5, f"scanner self-test: the pre-fix fallback lines are detected ({len(got)} findings)")


def main() -> int:
    print("=" * 80)
    print("QC: fetcher output paths -- own-sport only; unconfigured sport fails closed (safeguard A)")
    print("=" * 80)
    check_tables()
    check_fail_closed()
    check_positive_control()
    check_static()
    print("=" * 80)
    print(f"RESULT: {_OK} ok, {_FAIL} FAIL")
    return 1 if _FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
