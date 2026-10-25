"""QC: dark NFL ATS shadow pilot (Phase 2C-dark).

Proves the dark pilot's contract with frozen, synthetic builder-board views (no live
data, no app/pandas import): parity on populated and honest-empty boards; fail-closed on
malformed and unsynchronized inputs; the adapter never mutates the builder output and
never raises; and — critically — the flag-OFF application boundary does ZERO receipt
work and imports nothing (verified in a fresh subprocess).
"""
from __future__ import annotations

import copy
import subprocess
import sys

import services.decision_shadow_boundary as boundary
import services.nfl_ats_shadow as shadow


def _populated() -> dict:
    return {
        "sport": "nfl", "season": 2026, "surface": "nfl_ats_wave",
        "universe": ["team", "nfl_ats_board_2026", "v1"], "as_of": "2026-10-26T13:05:00Z",
        "rows": [
            {"team": "PHI", "leaf": "RENDERED", "reason": "QUALIFIED", "def_version": 1},
            {"team": "DAL", "leaf": "RENDERED", "reason": "QUALIFIED", "def_version": 1},
            {"team": "SF", "leaf": "SUPPRESSED", "reason": "DISPLAY_CAPPED", "def_version": 1},
            {"team": "NYG", "leaf": "NONMEMBER", "reason": "BELOW_THRESHOLD", "def_version": 1},
            {"team": "WAS", "leaf": "NONMEMBER", "reason": "COVER_SHORT", "def_version": 1},
        ],
        "counts": {"RENDERED": 2, "SUPPRESSED": 1, "NONMEMBER": 2}, "expected_count": 5,
        "empty_state": False, "source_health_state": "SYNCHRONIZED",
        "sort_rule_id": "streak_desc_team_asc", "sort_rule_version": "1",
    }


def _empty() -> dict:
    return {
        "sport": "nfl", "season": 2026, "surface": "nfl_ats_wave",
        "universe": ["team", "nfl_ats_board_2026", "v1"], "as_of": "2026-10-26T13:05:00Z",
        "rows": [
            {"team": "NYG", "leaf": "NONMEMBER", "reason": "BELOW_THRESHOLD", "def_version": 1},
            {"team": "WAS", "leaf": "NONMEMBER", "reason": "COVER_SHORT", "def_version": 1},
        ],
        "counts": {"NONMEMBER": 2}, "expected_count": 2, "empty_state": True,
        "source_health_state": "SYNCHRONIZED", "sort_rule_id": "streak_desc_team_asc",
        "sort_rule_version": "1",
    }


def run_qc() -> dict:
    checks, failures = [], []

    def ok(cond, label):
        (checks if cond else failures).append(label)

    # 1) populated board: full parity.
    r = shadow.run_shadow(_populated())
    ok(r["ok"] and r["parity"]["all"] and r["receipts_valid"] and not r["fail_closed"]
       and r["membership_hash"], f"populated board: parity + receipts valid"
       + ("" if r["ok"] else f"  -> {r}"))
    ok(all(r["parity"][k] for k in ("membership", "ordering", "counts", "source_health",
                                    "empty_state")), "populated board: every parity dimension matches")

    # 2) honest-empty board: parity holds, empty-state true, zero members.
    e = shadow.run_shadow(_empty())
    ok(e["ok"] and e["parity"]["empty_state"] and e["parity"]["all"],
       "honest-empty board: parity holds and empty-state disposition matches")

    # 3) parity FAIL surfaced (not crash): builder counts disagree with the rows.
    bad_counts = _populated(); bad_counts["counts"] = {"RENDERED": 9}
    bc = shadow.run_shadow(bad_counts)
    ok((not bc["ok"]) and bc["error"] is None and bc["parity"]["counts"] is False,
       "counts mismatch: parity fails as a RECORD (no raise)")

    # 4) malformed builder output: fail closed, recorded, never raised.
    malformed = _populated()
    malformed["rows"] = [{"team": "PHI", "leaf": "BOGUS_LEAF", "reason": "QUALIFIED", "def_version": 1}]
    m = shadow.run_shadow(malformed)
    ok((not m["ok"]) and m["error"] is not None and m["stage"] == "error",
       "malformed board (bad leaf): fail-closed error record, no raise")
    missing = _populated(); del missing["counts"]
    mm = shadow.run_shadow(missing)
    ok((not mm["ok"]) and mm["error"] is not None, "missing required field: fail-closed, no raise")

    # 5) unsynchronized source presenting members: fail closed.
    unsync = _populated(); unsync["source_health_state"] = "FAIL_CLOSED"
    u = shadow.run_shadow(unsync)
    ok((not u["ok"]) and "members_present_on_non_synchronized_source" in u["fail_closed"],
       "unsynchronized source with rendered members: fail-closed finding recorded")
    # but an empty board on a non-synchronized source is NOT a fail-closed members case.
    unsync_empty = _empty(); unsync_empty["source_health_state"] = "STALE"
    ue = shadow.run_shadow(unsync_empty)
    ok(not ue["fail_closed"], "non-synchronized source with zero members: no members fail-closed finding")

    # 6) adapter NEVER mutates the builder output.
    original = _populated()
    snapshot = copy.deepcopy(original)
    shadow.run_shadow(original)
    ok(original == snapshot, "adapter does not mutate the builder board view (read-only)")

    # 7) flag boundary: OFF (default) is a no-op that returns None.
    ok(boundary.shadow_if_enabled(_populated(), env={}) is None,
       "flag OFF (unset): boundary returns None (no-op)")
    ok(boundary.shadow_if_enabled(_populated(), env={boundary.FLAG: "0"}) is None,
       "flag '0': boundary returns None (no-op)")
    on = boundary.shadow_if_enabled(_populated(), env={boundary.FLAG: "1"})
    ok(isinstance(on, dict) and on.get("ok") is True, "flag ON (local): boundary runs the shadow")

    # 8) flag OFF => ZERO import impact at the application boundary (fresh interpreter).
    probe = (
        "import sys;"
        "import services.decision_shadow_boundary as b;"
        "r=b.shadow_if_enabled({'x':1}, env={});"
        "mods=set(sys.modules);"
        "print('R', r is None);"
        "print('ADAPTER', 'services.nfl_ats_shadow' in mods);"
        "print('RECEIPTS', 'services.decision_receipts' in mods);"
        "print('PANDAS', any(m.split('.')[0]=='pandas' for m in mods))"
    )
    out = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True,
                         cwd=str(__import__("pathlib").Path(boundary.__file__).resolve().parents[1]))
    lines = dict(l.split(" ", 1) for l in out.stdout.strip().splitlines() if " " in l)
    ok(out.returncode == 0 and lines.get("R") == "True", "OFF boundary returns None in a fresh interpreter")
    ok(lines.get("ADAPTER") == "False", "OFF: shadow adapter is NOT imported")
    ok(lines.get("RECEIPTS") == "False", "OFF: receipt package is NOT imported")
    ok(lines.get("PANDAS") == "False", "OFF: pandas is NOT imported")

    return {"clean": not failures, "checks": checks, "failures": failures}


def main() -> int:
    r = run_qc()
    print("=" * 72)
    print("DARK NFL ATS SHADOW PILOT QC (Phase 2C-dark)")
    print("=" * 72)
    for c in r["checks"]:
        print(f"  [ok] {c}")
    for f in r["failures"]:
        print(f"  [FAIL] {f}")
    print(f"\n{len(r['checks'])} passed, {len(r['failures'])} failed")
    print(f"Clean: {r['clean']}")
    return 0 if r["clean"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
