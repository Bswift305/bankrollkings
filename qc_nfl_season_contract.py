"""QC: pure NFL season contract + app delegation parity (Step 1 of the identity-adapter build).

Proves `services/nfl_season_contract.py` reproduces the ORIGINAL `app._nfl_expected_completed_week`
behavior exactly, that `app.py` now delegates to it (single source, same Week-1 table object), and that the
default-"today" wiring is preserved. Goldens are hand-computed from the Thu->Mon slate / Tue-completion
rule, independent of the implementation. No prod data, flag, route, or deploy.
"""
import ast
import os
import sys
from datetime import date

# app.py enforces SECRET_KEY at import; this QC only exercises a pure function, so a dummy is fine.
os.environ.setdefault("SECRET_KEY", "qc-nfl-season-contract-dummy")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import services.nfl_season_contract as nfl   # noqa: E402

fails = []


def check(cond, msg):
    print(("  [ok] " if cond else "  [FAIL] ") + msg)
    if not cond:
        fails.append(msg)


# (date, (expected_week, expected_season)) — hand-computed goldens covering every required scenario.
GOLDENS = [
    # --- 2026 anchor: Week-1 Thursday = 2026-09-10 ---
    (date(2026, 8, 1),  (0, 2026)),     # deep pre-season
    (date(2026, 9, 9),  (0, 2026)),     # day before Week 1 (pre-season)
    (date(2026, 9, 10), (0, 2026)),     # Week-1 Thursday itself (boundary): slate in progress, none final
    (date(2026, 9, 14), (0, 2026)),     # Monday of Week 1 (incomplete window)
    (date(2026, 9, 15), (1, 2026)),     # Tuesday -> Week 1 completes
    (date(2026, 9, 16), (1, 2026)),     # Wednesday (still 1 complete)
    (date(2026, 9, 17), (1, 2026)),     # Thursday, Week 2 starts (Week 1 complete)
    (date(2026, 9, 21), (1, 2026)),     # Monday of Week 2 (incomplete)
    (date(2026, 9, 22), (2, 2026)),     # Tuesday -> Week 2 completes
    (date(2026, 12, 31),(16, 2026)),    # year-end boundary, prior-season label (Dec is same season)
    (date(2027, 1, 1),  (16, 2026)),    # Jan 1 boundary -> prior-season (2026) label
    (date(2027, 1, 15), (18, 2026)),    # January -> prior-season AND Week-18 cap
    (date(2027, 2, 1),  (18, 2026)),    # February -> prior-season AND cap
    # --- 2025 anchor: Week-1 Thursday = 2025-09-04 ---
    (date(2025, 9, 3),  (0, 2025)),     # pre-season
    (date(2025, 9, 8),  (0, 2025)),     # Monday of Week 1 (incomplete)
    (date(2025, 9, 9),  (1, 2025)),     # Tuesday -> Week 1 completes
    # --- unsupported calendar years -> (None, season), no guess ---
    (date(2024, 10, 1), (None, 2024)),  # before the table
    (date(2027, 10, 1), (None, 2027)),  # a future season with no anchor yet
    (date(2030, 10, 1), (None, 2030)),  # far future
]


def test_pure_goldens():
    print("\n[A] pure expected_completed_week(date) matches the hand-computed goldens")
    for d, want in GOLDENS:
        got = nfl.expected_completed_week(d)
        check(got == want, f"{d.isoformat()} -> {got} (want {want})")


def test_app_delegation_parity():
    print("\n[B] app._nfl_expected_completed_week delegates to the pure contract (same results)")
    import app  # noqa: E402  (heavy monolith import; established QC pattern)
    # single source: the app name IS the module's table object, not a duplicate
    check(app.NFL_SEASON_WEEK1_THURSDAY is nfl.NFL_SEASON_WEEK1_THURSDAY,
          "app.NFL_SEASON_WEEK1_THURSDAY is the pure module's table (single source)")
    for d, want in GOLDENS:
        got = app._nfl_expected_completed_week(d)   # explicit today -> must equal the golden
        check(got == want, f"app({d.isoformat()}) -> {got} (want {want})")
    # default-"today" wiring preserved: omitting today supplies sports_today_date(), then delegates
    check(app._nfl_expected_completed_week() == nfl.expected_completed_week(app.sports_today_date()),
          "default today == sports_today_date() delegated to the pure contract")


def test_module_purity():
    print("\n[C] the season-contract module imports ONLY the standard library (ast-checked)")
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "services", "nfl_season_contract.py")
    tree = ast.parse(open(path, encoding="utf-8").read())
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            roots.add((node.module or "").split(".")[0])
    allowed = {"__future__", "datetime"}
    check(roots <= allowed, f"module imports only {sorted(allowed)} (actual roots: {sorted(roots)})")
    for forbidden in ("app", "flask", "pandas", "os", "requests", "socket", "pathlib", "numpy"):
        check(forbidden not in roots, f"no import of '{forbidden}'")


if __name__ == "__main__":
    print("=" * 80)
    print("NFL SEASON CONTRACT — STEP 1 PARITY QC (pure extraction + app delegation)")
    print("=" * 80)
    for t in (test_pure_goldens, test_module_purity, test_app_delegation_parity):
        t()
    print("\n" + "=" * 80)
    print("Clean:", not fails)
    if fails:
        print("FAILURES:")
        for f in fails:
            print("  -", f)
    sys.exit(1 if fails else 0)
