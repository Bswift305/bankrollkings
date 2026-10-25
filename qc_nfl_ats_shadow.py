"""QC: dark NFL ATS shadow pilot (Phase 2C-dark, Rev 3).

Frozen, synthetic builder-board views (no live data, no app/pandas import). Proves the
provenance foundations: receipt ids bind the COMPLETE build context; source fingerprints
are structured + verified (not laundered labels); identity evidence is type-validated,
never coerced; the three clocks are declared separately and never conflated; named rule
versions are required; non-synchronized sources are fully fail-closed; flag OFF imports
nothing.
"""
from __future__ import annotations

import copy
import subprocess
import sys
from pathlib import Path

import services.decision_shadow_boundary as boundary
import services.nfl_ats_shadow as shadow

FP = [{"source_id": "nflverse_games", "algorithm": "sha256", "digest": "ab" * 32}]
BK = "2026-10-26T13:05:00Z"
KICK = "2026-10-26T17:00:00Z"


def _ident(team, quality="DECLARED_COMPOSITE", collision_tested=True):
    base = {"quality": quality, "key": f"(nfl,2026,{team})",
            "base": {"sport": "nfl", "season": 2026}, "ext": {"team": team}}
    if quality in ("DECLARED_COMPOSITE", "COMPOSITE_NAME_EVENT"):
        base.update(collision_tested=collision_tested, profile="team:sport+season",
                    profile_version="v1", collision_proof=f"ledger#{team}")
    else:
        base["collision_tested"] = collision_tested
    return base


def _prov(build_id="build-ats-2026w8", obs=1001, config="cfg-7", rule_versions=None,
          ordering_id="streak_desc_team_asc", ordering_ver="1", fps=None):
    return {"build_id": build_id, "config_version": config,
            "rule_versions": rule_versions or {"membership": 3, "ordering": 1},
            "ordering_rule_id": ordering_id, "ordering_rule_version": ordering_ver,
            "source_fingerprints": fps if fps is not None else [dict(FP[0])], "observation_seq": obs}


def _clocks(bk=BK, su=None, status="NOT_PROVIDED", ee=KICK):
    return {"bk_captured": bk, "source_updated": su, "source_updated_status": status,
            "event_effective": ee}


def _row(team, leaf, reason, params=None, quality="DECLARED_COMPOSITE", collision_tested=True,
         identity=None):
    r = {"team": team, "leaf": leaf, "reason": reason, "def_version": 1,
         "identity": identity if identity is not None else _ident(team, quality, collision_tested)}
    if params is not None:
        r["params"] = params
    return r


def _view(prov=None, rows=None, counts=None, expected=None, empty=False, health="SYNCHRONIZED",
          clocks=None, created_at="2026-10-26T13:05:05Z", universe=None):
    if rows is None:
        rows = [_row("PHI", "RENDERED", "QUALIFIED"), _row("DAL", "RENDERED", "QUALIFIED"),
                _row("SF", "SUPPRESSED", "DISPLAY_CAPPED"),
                _row("NYG", "NONMEMBER", "BELOW_THRESHOLD", params={"threshold": 3}),
                _row("WAS", "NONMEMBER", "COVER_SHORT")]
        counts = {"RENDERED": 2, "SUPPRESSED": 1, "NONMEMBER": 2}
        expected = 5
    return {"sport": "nfl", "season": 2026, "surface": "nfl_ats_wave",
            "universe": universe or ["team", "nfl_ats_board_2026", "v1"], "created_at": created_at,
            "clocks": clocks or _clocks(), "provenance": prov or _prov(), "rows": rows,
            "counts": counts, "expected_count": expected, "empty_state": empty,
            "source_health_state": health}


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

    # Happy paths.
    r = shadow.run_shadow(_view())
    ok(r["ok"] and r["parity"]["all"] and r["receipts_valid"] and not r["fail_closed"],
       "populated board: parity + full validator set" + ("" if r["ok"] else f"  -> {r['diffs'] or r['error']}"))
    ok(shadow.run_shadow(_empty())["ok"], "honest-empty board (synchronized): ok")

    # BLOCKER 1 — ids bind the COMPLETE build context. Change one field at a time.
    base_ids = shadow.run_shadow(_view())["receipt_ids"]
    variants = {
        "config": _view(prov=_prov(config="cfg-8")),
        "membership_rule": _view(prov=_prov(rule_versions={"membership": 4, "ordering": 1})),
        "ordering_rule_id": _view(prov=_prov(ordering_id="other_rule")),
        "universe": _view(universe=["team", "nfl_ats_board_2026", "v2"]),
        "clocks": _view(clocks=_clocks(bk="2026-10-26T14:00:00Z")),
        "created_at": _view(created_at="2026-10-26T13:06:00Z"),
        "rows": _view(rows=[_row("PHI", "RENDERED", "QUALIFIED")], counts={"RENDERED": 1}, expected=1),
    }
    for name, v in variants.items():
        ids = shadow.run_shadow(v)["receipt_ids"]
        ok(ids and ids != base_ids, f"BLOCKER1: changing {name} yields distinct receipt ids")
    ok(shadow.run_shadow(_view())["receipt_ids"] == base_ids,
       "BLOCKER1: identical replay reproduces identical ids")

    # BLOCKER 2 — structured, verified source fingerprints (not laundered labels).
    for bad, why in (
        (["nflverse@sha256:abc"], "a bare label string"),
        ([{"source_id": "x", "algorithm": "md5", "digest": "ab" * 32}], "unsupported algorithm"),
        ([{"source_id": "x", "algorithm": "sha256", "digest": "nothex"}], "malformed digest"),
        ([{"source_id": "", "algorithm": "sha256", "digest": "ab" * 32}], "blank source_id"),
        ([dict(FP[0]), dict(FP[0])], "duplicate source_id"),
    ):
        res = shadow.run_shadow(_view(prov=_prov(fps=bad)))
        ok((not res["ok"]) and res["error"] is not None, f"BLOCKER2: fingerprint rejected ({why})")
    good = shadow.run_shadow(_view())
    ok(good["ok"], "BLOCKER2: a structured verified fingerprint is accepted")

    # BLOCKER 3 — identity evidence is type-validated, never coerced.
    for idv, why in (
        (_ident("PHI", collision_tested="false"), "collision_tested='false' string"),
        (_ident("PHI", collision_tested=1), "collision_tested=1 int"),
        ({"quality": "DECLARED_COMPOSITE", "key": "(nfl,2026,PHI)",
          "base": {"sport": "nfl", "season": 2026}, "ext": {"team": "PHI"},
          "collision_tested": True, "profile": "p", "profile_version": "v1"}, "missing collision_proof"),
        ({"quality": "DECLARED_COMPOSITE", "key": "k", "base": {"sport": "nfl"},
          "ext": {"team": "PHI"}, "collision_tested": True, "profile": "p",
          "profile_version": "v1", "collision_proof": "x"}, "base missing season"),
        ({"quality": "DECLARED_COMPOSITE", "key": "k", "base": {"sport": "nfl", "season": 2026},
          "ext": "not-a-map", "collision_tested": True, "profile": "p",
          "profile_version": "v1", "collision_proof": "x"}, "ext not a map"),
    ):
        res = shadow.run_shadow(_view(rows=[_row("PHI", "RENDERED", "QUALIFIED", identity=idv)],
                                      counts={"RENDERED": 1}, expected=1))
        ok((not res["ok"]) and res["error"] is not None, f"BLOCKER3: identity rejected ({why})")
    labelonly = shadow.run_shadow(_view(rows=[_row("PHI", "RENDERED", "QUALIFIED", quality="NAME_ONLY",
                                     collision_tested=False)], counts={"RENDERED": 1}, expected=1))
    ok((not labelonly["ok"]) and any("authoritative identity" in d for d in labelonly["diffs"]),
       "BLOCKER3: a NAME_ONLY label member fails closed (non-authoritative)")

    # BLOCKER 4 — clocks declared separately; never conflated.
    r2 = shadow.run_shadow(_view(clocks=_clocks(su=None, status="NOT_PROVIDED")))
    ok(r2["ok"], "BLOCKER4: absent source_updated stays null + NOT_PROVIDED (valid)")
    naive = shadow.run_shadow(_view(clocks=_clocks(bk="2026-10-26T13:05:00")))  # no Z
    ok((not naive["ok"]) and any("bk_captured" in d for d in naive["diffs"]),
       "BLOCKER4: timezone-naive bk_captured fails")
    badstatus = shadow.run_shadow(_view(clocks=_clocks(su=None, status="PRESENT")))  # null+PRESENT
    ok((not badstatus["ok"]) and any("source_updated" in d for d in badstatus["diffs"]),
       "BLOCKER4: null source_updated with status PRESENT fails")
    present = shadow.run_shadow(_view(clocks=_clocks(su="2026-10-26T12:00:00Z", status="PRESENT")))
    ok(present["ok"], "BLOCKER4: a present source_updated + PRESENT status is valid")

    # BLOCKER (final) — strict input contract: NO coercion. Each must fail at the input
    # stage, before any receipt ids are returned (receipt_ids stays empty).
    def _mutate(**over):
        v = copy.deepcopy(_view())
        v.update(over)
        return v

    def _fails_at_contract(v, why):
        res = shadow.run_shadow(v)
        ok((not res["ok"]) and res["error"] is not None and res["receipt_ids"] == {},
           f"strict contract: {why} fails at input stage (no receipt ids)")

    # string/bool numerics
    sv = _mutate(); sv["rows"][3]["def_version"] = "1"
    _fails_at_contract(sv, "def_version as string '1'")
    _fails_at_contract(_mutate(expected_count="5"), "expected_count as string '5'")
    _fails_at_contract(_mutate(season="2026"), "season as string '2026'")
    cv = _mutate(); cv["counts"] = {"RENDERED": "2", "SUPPRESSED": 1, "NONMEMBER": 2}
    _fails_at_contract(cv, "a count value as string '2'")
    _fails_at_contract(_mutate(provenance=_prov(obs="1001")), "observation_seq as string")
    _fails_at_contract(_mutate(provenance=_prov(rule_versions={"membership": "3", "ordering": 1})),
                       "rule version as string")
    bv = _mutate(); bv["rows"][0]["def_version"] = True
    _fails_at_contract(bv, "def_version as boolean True")
    # "false" empty state
    _fails_at_contract(_mutate(empty_state="false"), "empty_state as string 'false'")
    # negative count
    nc = _mutate(); nc["counts"] = {"RENDERED": 2, "SUPPRESSED": 1, "NONMEMBER": 2, "FAILED": -1}
    _fails_at_contract(nc, "a negative count")
    # unknown count leaf
    uc = _mutate(); uc["counts"] = {"RENDERED": 2, "SUPPRESSED": 1, "NONMEMBER": 2, "BOGUS": 0}
    _fails_at_contract(uc, "a count keyed by a non-leaf value")
    # inconsistent expected_count
    _fails_at_contract(_mutate(expected_count=99), "expected_count != sum(counts)")
    # non-JSON-serializable object
    js = _mutate(); js["rows"][0]["params"] = {"x": object()}
    _fails_at_contract(js, "a non-JSON-serializable object in the view")

    # CROSS-FIELD IDENTITY INTEGRITY — identity must describe the same entity/universe as
    # the row/board. Each must fail before receipt ids are produced.
    v = copy.deepcopy(_view()); v["rows"][0]["identity"]["base"]["sport"] = "cfb"
    _fails_at_contract(v, "identity base.sport != board sport")
    v = copy.deepcopy(_view()); v["rows"][0]["identity"]["base"]["season"] = 2025
    _fails_at_contract(v, "identity base.season != board season")
    v = copy.deepcopy(_view()); v["rows"][0]["identity"]["base"]["season"] = "2026"
    _fails_at_contract(v, "identity base.season as string")
    v = copy.deepcopy(_view()); v["rows"][0]["identity"]["ext"]["team"] = "DAL"  # row team is PHI
    _fails_at_contract(v, "member identity.ext.team != row team")
    v = copy.deepcopy(_view()); v["rows"][3]["identity"]["ext"]["team"] = "CLE"  # NYG nonmember row
    _fails_at_contract(v, "NONMEMBER identity.ext.team != row team")
    v = copy.deepcopy(_view()); v["universe"] = ["team_side_decision", "nfl_ats_board_2026", "v1"]
    _fails_at_contract(v, "non-team universe grain")
    v = copy.deepcopy(_view()); v["surface"] = "cfb_ats_wave"
    _fails_at_contract(v, "wrong surface")
    v = copy.deepcopy(_view()); v["sport"] = "cfb"
    _fails_at_contract(v, "wrong sport")
    v = copy.deepcopy(_view()); v["universe"] = ["team", "nfl_ats_board_2027", "v1"]  # season is 2026
    _fails_at_contract(v, "universe id year != board season")
    # duplicate canonical identity across rows: the same governed team appears as both a
    # member (RENDERED) and a NONMEMBER.
    v = copy.deepcopy(_view())
    v["rows"] = [_row("PHI", "RENDERED", "QUALIFIED"),
                 _row("PHI", "NONMEMBER", "BELOW_THRESHOLD", params={"threshold": 3})]
    v["counts"] = {"RENDERED": 1, "NONMEMBER": 1}; v["expected_count"] = 2
    _fails_at_contract(v, "duplicate canonical identity across member + nonmember rows")

    # Named rule-version keys required.
    nr = shadow.run_shadow(_view(prov=_prov(rule_versions={"ordering": 1})))  # no 'membership'
    ok((not nr["ok"]) and "membership" in (nr["error"] or ""),
       "named rule-version key 'membership' is required")

    # Non-synchronized sources fully fail-closed.
    se = shadow.run_shadow(_empty(health="STALE"))
    ok((not se["ok"]) and any("eligible_conclusion" in f for f in se["fail_closed"]),
       "STALE empty board => ok:false + eligible-conclusion fail-closed")
    un = shadow.run_shadow(_unavailable())
    ok((not un["ok"]) and any("source_health_not_synchronized" in f for f in un["fail_closed"])
       and not any("members_admitted" in f for f in un["fail_closed"]),
       "unhealthy source with UNAVAILABLE rows => ok:false, only the source-health finding")

    # Missing provenance / created_at.
    noprov = _view(); del noprov["provenance"]
    ok((not shadow.run_shadow(noprov)["ok"]), "missing provenance fails closed")
    noca = _view(); del noca["created_at"]
    r_noca = shadow.run_shadow(noca)
    ok((not r_noca["ok"]) and "created_at" in (r_noca["error"] or ""), "missing created_at fails closed")

    # No mutation, flag behavior, zero-import proof.
    original = _view(); snap = copy.deepcopy(original); shadow.run_shadow(original)
    ok(original == snap, "adapter does not mutate the builder board view")
    ok(boundary.shadow_if_enabled(_view(), env={}) is None, "flag OFF: boundary no-op")
    ok((boundary.shadow_if_enabled(_view(), env={boundary.FLAG: "1"}) or {}).get("ok") is True,
       "flag ON (local): boundary runs the shadow")
    probe = ("import sys;import services.decision_shadow_boundary as b;"
             "r=b.shadow_if_enabled({'x':1}, env={});m=set(sys.modules);"
             "print('R', r is None);print('ADAPTER','services.nfl_ats_shadow' in m);"
             "print('RECEIPTS','services.decision_receipts' in m);"
             "print('PANDAS', any(x.split('.')[0]=='pandas' for x in m))")
    out = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True,
                         cwd=str(Path(boundary.__file__).resolve().parents[1]))
    lines = dict(l.split(" ", 1) for l in out.stdout.strip().splitlines() if " " in l)
    ok(lines.get("R") == "True" and lines.get("ADAPTER") == "False"
       and lines.get("RECEIPTS") == "False" and lines.get("PANDAS") == "False",
       "flag OFF: fresh interpreter imports neither adapter, receipt package, nor pandas")

    return {"clean": not failures, "checks": checks, "failures": failures}


def main() -> int:
    r = run_qc()
    print("=" * 72)
    print("DARK NFL ATS SHADOW PILOT QC (Phase 2C-dark, Rev 3)")
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
