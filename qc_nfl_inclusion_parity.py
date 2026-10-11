"""Characterization + parity harness for the NFL inclusion surfaces.

Purpose (Player Check implementation, stages 1 + 3): lock the CURRENT outputs of the four
inclusion surfaces -- Floor board, The Menu, Green Light, Featured (usage) -- so the upcoming
shared-predicate refactor can be proven to change nothing about membership, ordering, cutoffs,
or selected markets.

Usage:
  py -3 qc_nfl_inclusion_parity.py capture <baseline.json>   # snapshot current outputs
  py -3 qc_nfl_inclusion_parity.py check   <baseline.json>   # recompute + diff vs baseline
  py -3 qc_nfl_inclusion_parity.py                           # durable invariants only (no baseline)

The parity workflow is in-session and single-data-state: capture a baseline BEFORE refactoring,
refactor, then `check` against it -- zero diff proves parity. Baselines are data-dependent, so
they live in scratch and are NOT committed. The no-arg invariant mode is data-independent and
safe to run anytime (and in run_all_scorecards if desired).

Deterministic params only: the Menu is snapshotted with timeframe='week' (the no-narrowing
window) so the snapshot does not depend on the weekday.
"""
from __future__ import annotations

import json
import sys

import app

VOLATILE_KEYS = {"updated", "generated", "as_of", "asof", "timestamp", "checked_at"}


def _strip(obj):
    """Deep-normalize: drop volatile timestamp keys, round floats, preserve list order."""
    if isinstance(obj, dict):
        return {k: _strip(v) for k, v in obj.items() if k not in VOLATILE_KEYS}
    if isinstance(obj, list):
        return [_strip(x) for x in obj]
    if isinstance(obj, tuple):
        return [_strip(x) for x in obj]
    if isinstance(obj, float):
        return round(obj, 6)
    return obj


def _snapshot() -> dict:
    """Normalized outputs of every inclusion surface under fixed, deterministic params."""
    return {
        "floor_24_78": _strip(app.build_nfl_floor_board(limit=24, min_hit=78, min_games=8)),
        "floor_90_52": _strip(app.build_nfl_floor_board(limit=90, min_hit=52, min_games=8)),
        "green_all": _strip(app.build_green_light()),
        "green_wr": _strip(app.build_green_light(pos="wr")),
        "menu_week_all": _strip(
            app.build_menu_board(legs="all", timeframe="week", sport="all", tier="all", pos="all")
        ),
        "menu_week_props_wr": _strip(
            app.build_menu_board(legs="props", timeframe="week", sport="all", tier="all", pos="wr")
        ),
        "featured_usage": _strip(app.build_nfl_usage_board()),
    }


def _diff_paths(a, b, path=""):
    """Yield up to a handful of human-readable difference paths between two snapshots."""
    out = []
    if type(a) is not type(b):
        out.append(f"{path}: type {type(a).__name__} != {type(b).__name__}")
        return out
    if isinstance(a, dict):
        for k in a.keys() | b.keys():
            if k not in a:
                out.append(f"{path}.{k}: missing in new")
            elif k not in b:
                out.append(f"{path}.{k}: missing in baseline")
            else:
                out += _diff_paths(a[k], b[k], f"{path}.{k}")
    elif isinstance(a, list):
        if len(a) != len(b):
            out.append(f"{path}: length {len(a)} != {len(b)}")
        for i, (x, y) in enumerate(zip(a, b)):
            out += _diff_paths(x, y, f"{path}[{i}]")
    elif a != b:
        out.append(f"{path}: {a!r} != {b!r}")
    return out[:40]


def _invariants() -> list[str]:
    """Data-independent invariants that must always hold (only asserted on non-empty boards)."""
    issues: list[str] = []

    f = app.build_nfl_floor_board(limit=24, min_hit=78, min_games=8)
    floors = f.get("floors", [])
    if floors:
        if any((r.get("hit") or 0) < 78 for r in floors):
            issues.append("floor(24,78): a row is below the 78% min_hit")
        if list(floors) != sorted(floors, key=lambda r: (-(r.get("hit") or 0), -(r.get("clears") or 0))):
            issues.append("floor(24,78): not sorted by (-hit, -clears)")
        if len(floors) > 24:
            issues.append("floor(24,78): exceeds the limit of 24 rows")

    w = app.build_nfl_floor_board(limit=90, min_hit=52, min_games=8)
    wf = w.get("floors", [])
    if wf and any((r.get("hit") or 0) < 52 for r in wf):
        issues.append("floor(90,52): a row is below the 52% min_hit")

    g = app.build_green_light()
    plays = g.get("plays", [])
    if plays:
        convs = [p.get("convergence", 0) for p in plays]
        if convs != sorted(convs, reverse=True):
            issues.append("green light: plays not ordered by convergence desc")

    return issues


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "invariants"

    if mode == "capture":
        path = sys.argv[2]
        snap = _snapshot()
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(snap, fh, indent=1, sort_keys=True)
        counts = {k: (len(v.get("floors") or v.get("plays") or v.get("games") or v.get("players") or []) if isinstance(v, dict) else 0) for k, v in snap.items()}
        print(f"[CAPTURE] baseline written to {path}")
        print(f"[CAPTURE] surface item counts: {counts}")
        return 0

    if mode == "check":
        path = sys.argv[2]
        with open(path, encoding="utf-8") as fh:
            baseline = json.load(fh)
        new = _snapshot()
        # json round-trip the new snapshot so tuples/types match the loaded baseline exactly
        new = json.loads(json.dumps(new, sort_keys=True))
        diffs = _diff_paths(new, baseline, "")
        print("=" * 60)
        print("NFL INCLUSION PARITY CHECK")
        print("=" * 60)
        if not diffs:
            print("PARITY OK -- refactored outputs identical to baseline.")
            return 0
        print(f"PARITY FAILED -- {len(diffs)} difference(s) (first shown):")
        for d in diffs:
            print(f"  {d}")
        return 1

    # default: durable invariants
    issues = _invariants()
    print("=" * 60)
    print("NFL INCLUSION INVARIANTS")
    print("=" * 60)
    if not issues:
        print("No invariant violations detected.")
        return 0
    for msg in issues:
        print(f"[FAIL] {msg}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
