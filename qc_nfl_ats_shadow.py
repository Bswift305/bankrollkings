"""QC: dark NFL ATS shadow pilot (Phase 2C-dark, Rev 2).

Frozen, synthetic builder-board views (no live data, no app/pandas import). Proves the
corrected adapter: the FULL validator set runs; identity/provenance are builder-supplied
(never fabricated); non-synchronized sources are fully fail-closed; receipt ids/sequences
are deterministic per build (distinct across builds); flag OFF imports nothing.
"""
from __future__ import annotations

import copy
import subprocess
import sys

import services.decision_shadow_boundary as boundary
import services.nfl_ats_shadow as shadow


def _ident(team, quality="DECLARED_COMPOSITE"):
    base = {"quality": quality, "key": f"(nfl,2026,{team})",
            "base": {"sport": "nfl", "season": 2026}, "ext": {"team": team}}
    if quality == "DECLARED_COMPOSITE":
        base.update(collision_tested=True, profile="team:sport+season", profile_version="v1",
                    collision_proof=f"ledger#{team}")
    return base


def _prov(build_id="build-ats-2026w8", obs=1001):
    return {"build_id": build_id, "config_version": "cfg-7",
            "rule_versions": {"membership": 3, "ordering": 1},
            "ordering_rule_id": "streak_desc_team_asc", "ordering_rule_version": "1",
            "source_fingerprints": ["nflverse@sha256:abc123"], "observation_seq": obs}


def _row(team, leaf, reason, params=None, quality="DECLARED_COMPOSITE"):
    r = {"team": team, "leaf": leaf, "reason": reason, "def_version": 1, "identity": _ident(team, quality)}
    if params is not None:
        r["params"] = params
    return r


def _view(prov=None, rows=None, counts=None, expected=None, empty=False, health="SYNCHRONIZED"):
    if rows is None:
        rows = [
            _row("PHI", "RENDERED", "QUALIFIED"),
            _row("DAL", "RENDERED", "QUALIFIED"),
            _row("SF", "SUPPRESSED", "DISPLAY_CAPPED"),
            _row("NYG", "NONMEMBER", "BELOW_THRESHOLD", params={"threshold": 3}),
            _row("WAS", "NONMEMBER", "COVER_SHORT"),
        ]
        counts = {"RENDERED": 2, "SUPPRESSED": 1, "NONMEMBER": 2}
        expected = 5
    return {"sport": "nfl", "season": 2026, "surface": "nfl_ats_wave",
            "universe": ["team", "nfl_ats_board_2026", "v1"], "as_of": "2026-10-26T13:05:00Z",
            "provenance": prov or _prov(), "rows": rows, "counts": counts,
            "expected_count": expected, "empty_state": empty, "source_health_state": health}


def _empty(health="SYNCHRONIZED"):
    rows = [_row("NYG", "NONMEMBER", "BELOW_THRESHOLD", params={"threshold": 3}),
            _row("WAS", "NONMEMBER", "COVER_SHORT")]
    return _view(rows=rows, counts={"NONMEMBER": 2}, expected=2, empty=True, health=health)


def _unavailable(health="FAIL_CLOSED"):
    rows = [_row("NYG", "UNAVAILABLE", "SOURCE_UNAVAILABLE"),
            _row("WAS", "UNAVAILABLE", "SOURCE_UNAVAILABLE")]
    return _view(rows=rows, counts={"UNAVAILABLE": 2}, expected=2, empty=True, health=health)


def run_qc() -> dict:
    checks, failures = [], []

    def ok(cond, label):
        (checks if cond else failures).append(label)

    # 1) populated board: full parity + full validator set passes.
    r = shadow.run_shadow(_view())
    ok(r["ok"] and r["parity"]["all"] and r["receipts_valid"] and not r["fail_closed"],
       "populated board: parity + full validator set" + ("" if r["ok"] else f"  -> {r['diffs'] or r['error']}"))

    # 2) honest-empty board (SYNCHRONIZED): ok, empty-state matches.
    e = shadow.run_shadow(_empty())
    ok(e["ok"] and e["parity"]["empty_state"], "honest-empty board (synchronized): ok")

    # BLOCKER 1 — full validator set: a BELOW_THRESHOLD row missing its threshold param fails.
    noparam = _view(rows=[_row("NYG", "NONMEMBER", "BELOW_THRESHOLD")],  # no params
                    counts={"NONMEMBER": 1}, expected=1, empty=True)
    n = shadow.run_shadow(noparam)
    ok((not n["ok"]) and n["error"] is None
       and any("param_fields" in d for d in n["diffs"]),
       "BLOCKER1: missing required reason param is caught by validate_reason_usage (no raise)")

    # BLOCKER 2 — a display label alone cannot become authoritative identity.
    labelonly = _view(rows=[_row("PHI", "RENDERED", "QUALIFIED", quality="NAME_ONLY")],
                      counts={"RENDERED": 1}, expected=1)
    lo = shadow.run_shadow(labelonly)
    ok((not lo["ok"]) and any("authoritative identity" in d for d in lo["diffs"]),
       "BLOCKER2: a NAME_ONLY (label-only) member is non-authoritative and fails closed")

    # BLOCKER 3 — non-synchronized sources are FULLY fail-closed.
    stale_empty = shadow.run_shadow(_empty(health="STALE"))
    ok((not stale_empty["ok"])
       and any("source_health_not_synchronized" in f for f in stale_empty["fail_closed"])
       and any("eligible_conclusion" in f for f in stale_empty["fail_closed"]),
       "BLOCKER3: STALE empty board => ok:false + source-health + eligible-conclusion findings")
    fc_members = shadow.run_shadow(_view(health="FAIL_CLOSED"))
    ok((not fc_members["ok"])
       and "members_admitted_under_unhealthy_source" in fc_members["fail_closed"],
       "BLOCKER3: FAIL_CLOSED board with members => members-admitted fail-closed finding")
    unavail = shadow.run_shadow(_unavailable(health="FAIL_CLOSED"))
    ok((not unavail["ok"])
       and any("source_health_not_synchronized" in f for f in unavail["fail_closed"])
       and not any("members_admitted" in f for f in unavail["fail_closed"])
       and not any("eligible_conclusion" in f for f in unavail["fail_closed"]),
       "BLOCKER3: unhealthy source with UNAVAILABLE rows => ok:false, only the source-health finding")

    # BLOCKER 4 — deterministic ids per build; distinct across builds; stable on replay.
    a = shadow.run_shadow(_view(prov=_prov("buildA", 1001)))
    b = shadow.run_shadow(_view(prov=_prov("buildB", 2002)))
    a2 = shadow.run_shadow(_view(prov=_prov("buildA", 1001)))
    ok(a["receipt_ids"] and a["receipt_ids"] != b["receipt_ids"],
       "BLOCKER4: different builds produce different receipt ids")
    ok(a["receipt_ids"] == a2["receipt_ids"] and a["membership_hash"] == a2["membership_hash"],
       "BLOCKER4: replaying the identical build reproduces identical ids/hashes")

    # BLOCKER 5 — missing provenance fails the shadow (no fabricated defaults).
    noprov = _view(); del noprov["provenance"]
    np = shadow.run_shadow(noprov)
    ok((not np["ok"]) and np["error"] is not None and "provenance" in np["error"],
       "BLOCKER5: missing provenance block fails closed")
    partial = _view(); partial["provenance"] = dict(partial["provenance"]); del partial["provenance"]["source_fingerprints"]
    pp = shadow.run_shadow(partial)
    ok((not pp["ok"]) and pp["error"] is not None and "source_fingerprints" in pp["error"],
       "BLOCKER5: missing source fingerprints fails closed")

    # malformed leaf still fails closed (no raise).
    mal = _view(rows=[_row("PHI", "BOGUS", "QUALIFIED")], counts={"RENDERED": 0}, expected=1)
    m = shadow.run_shadow(mal)
    ok((not m["ok"]) and m["error"] is not None and m["stage"] == "error",
       "malformed leaf: fail-closed error record, no raise")

    # adapter never mutates the builder output.
    original = _view(); snapshot = copy.deepcopy(original); shadow.run_shadow(original)
    ok(original == snapshot, "adapter does not mutate the builder board view (read-only)")

    # flag boundary behavior.
    ok(boundary.shadow_if_enabled(_view(), env={}) is None, "flag OFF (unset): boundary no-op")
    on = boundary.shadow_if_enabled(_view(), env={boundary.FLAG: "1"})
    ok(isinstance(on, dict) and on.get("ok") is True, "flag ON (local): boundary runs the shadow")

    # flag OFF => zero import impact at the application boundary (fresh interpreter).
    probe = (
        "import sys;"
        "import services.decision_shadow_boundary as b;"
        "r=b.shadow_if_enabled({'x':1}, env={});"
        "m=set(sys.modules);"
        "print('R', r is None);"
        "print('ADAPTER', 'services.nfl_ats_shadow' in m);"
        "print('RECEIPTS', 'services.decision_receipts' in m);"
        "print('PANDAS', any(x.split('.')[0]=='pandas' for x in m))"
    )
    from pathlib import Path
    out = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True,
                         cwd=str(Path(boundary.__file__).resolve().parents[1]))
    lines = dict(l.split(" ", 1) for l in out.stdout.strip().splitlines() if " " in l)
    ok(out.returncode == 0 and lines.get("R") == "True", "OFF boundary returns None (fresh interpreter)")
    ok(lines.get("ADAPTER") == "False", "OFF: shadow adapter is NOT imported")
    ok(lines.get("RECEIPTS") == "False", "OFF: receipt package is NOT imported")
    ok(lines.get("PANDAS") == "False", "OFF: pandas is NOT imported")

    return {"clean": not failures, "checks": checks, "failures": failures}


def main() -> int:
    r = run_qc()
    print("=" * 72)
    print("DARK NFL ATS SHADOW PILOT QC (Phase 2C-dark, Rev 2)")
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
