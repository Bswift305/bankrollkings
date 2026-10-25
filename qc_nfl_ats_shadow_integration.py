"""QC: build_nfl_ats_wave shadow call-site integration (Phase 2C-dark local wiring, Rev 2).

Invokes the REAL shared observer (services.nfl_ats_shadow_hook.observe_build_nfl_ats_wave) —
the exact function app.py calls — against representative builder results for the POPULATED,
EMPTY, and UNAVAILABLE return paths. It does NOT reimplement the call-site block; instead it
also statically asserts app.py calls that observer (so drift is caught). Proves: builder
result deep-equal with shadow OFF and ON; OFF produces no record; parity is against the
builder's authoritative result['members']; unhealthy sources carry UNAVAILABLE (no factual
nonmembers); the live governed=None path fails closed (runtime pilot BLOCKED); exceptions are
isolated; and reports local incremental latency. Injectable created_at keeps it deterministic.
"""
from __future__ import annotations

import copy
import os
import re
import statistics
import time
from pathlib import Path

import services.decision_shadow_boundary as boundary
import services.nfl_ats_shadow_hook as hook

BK = "2026-10-26T13:05:00Z"
CREATED = "2026-10-26T13:05:05Z"
SHA = "ab" * 32
APP = Path(hook.__file__).resolve().parents[1] / "app.py"


def _flag(on):
    if on:
        os.environ[boundary.FLAG] = "1"
    else:
        os.environ.pop(boundary.FLAG, None)


def _dec(per):
    return {"per": per}


def _cur():
    return {"content_sha256": SHA}


def _result(members, synced=True):
    return {"members": members, "sync": {"synchronized": synced, "checked_at_utc": BK},
            "expected_completed_week": 8}


# Mirror of app.py's authoritative _WAVE_SHADOW_BUILDER_RULES (threshold 3, all rule versions 1).
BUILDER_RULES = {"membership_threshold": 3, "membership_rule_version": 1,
                 "ordering_rule_id": "streak_desc_team_asc", "ordering_rule_version": "1",
                 "reason_def_version": 1}


def _gov(teams):
    return {"build_id": "build-ats-2026w8", "config_version": "cfg-7",
            "rule_versions": {"membership": 1, "ordering": 1},
            "ordering_rule_id": "streak_desc_team_asc", "ordering_rule_version": "1",
            "membership_threshold": 3, "observation_seq": 1001, "reason_def_version": 1,
            "identity_profiles": {t: {"profile": "team:sport+season", "profile_version": "v1",
                                      "collision_proof": f"ledger#{t}"} for t in teams}}


def _obs(result, dec, cur=None, season=2026, governed=None, builder_rules=BUILDER_RULES):
    """Call the REAL shared observer with a deterministic injected creation clock."""
    return hook.observe_build_nfl_ats_wave(result, dec=dec, cur=cur, season=season,
                                           governed=governed, builder_rules=builder_rules,
                                           created_at=CREATED)


def run_qc() -> dict:
    checks, failures = [], []
    lat = {}

    def ok(cond, label):
        (checks if cond else failures).append(label)

    # The builder's authoritative result for a populated board: PHI then DAL (streak-desc).
    members = [{"team": "PHI", "streak": 4}, {"team": "DAL", "streak": 3}]
    per_pop = {"PHI": {}, "DAL": {}, "NYG": {}, "WAS": {}}      # decision universe (4 teams)
    per_empty = {"NYG": {}, "WAS": {}}

    # 0) app.py actually calls the shared observer (static drift guard; no mirror).
    src = APP.read_text(encoding="utf-8", errors="replace")
    ok("observe_build_nfl_ats_wave(" in src
       and "_build_nfl_ats_wave_impl" in src, "app.py calls the shared observer on its return paths")

    # 1) OFF: zero work, no record, output unchanged.
    _flag(False); hook._reset()
    res = _result(members); snap = copy.deepcopy(res)
    out = _obs(res, _dec(per_pop))
    ok(out is None and hook.last_record() is None and res == snap,
       "OFF: no record, no work, builder result unchanged")

    try:
        _flag(True)

        # 2) POPULATED: parity against result['members'] (authoritative), builder order.
        hook._reset(); res = _result(members); snap = copy.deepcopy(res)
        rec = _obs(res, _dec(per_pop), _cur(), governed=_gov(["PHI", "DAL", "NYG", "WAS"]))
        ok(res == snap, "ON populated: builder result unchanged")
        ok(rec["ok"] and rec["parity"]["all"]
           and rec["parity"].get("builder_membership") is True
           and rec["parity"].get("builder_ordering") is True,
           "ON populated: receipt membership/order match result['members'] (authoritative)")

        # drift: builder board lists a member NOT in the decision universe -> fail closed.
        hook._reset()
        drift = _obs(_result([{"team": "PHI"}, {"team": "KC"}]), _dec(per_pop), _cur(),
                     governed=_gov(["PHI", "DAL", "NYG", "WAS", "KC"]))
        ok((not drift["ok"]) and drift["stage"] == "hook"
           and "decision universe" in (drift["error"] or ""),
           "ON drift: a board member absent from the decision universe fails closed")

        # 3) EMPTY (honest, synchronized): zero members, universe are nonmembers.
        hook._reset()
        e = _obs(_result([]), _dec(per_empty), _cur(), governed=_gov(["NYG", "WAS"]))
        ok(e["ok"] and e["parity"]["empty_state"] and e["parity"].get("builder_membership") is True,
           "ON empty: honest-empty parity holds")

        # 4) UNAVAILABLE early return as the LIVE call site sees it (synced False, dec/cur None,
        #    governed=None): the path IS observed and fails closed, isolated.
        hook._reset()
        u = _obs(_result([], synced=False), None, None, governed=None)
        ok((not u["ok"]) and (u.get("error") is not None or u.get("fail_closed")),
           "ON unavailable (early return, live governed=None): observed and fails closed")
        # UNAVAILABLE with a known universe + governed: every expected team is UNAVAILABLE and
        # the source-health failure is recorded — no factual NONMEMBER is emitted.
        hook._reset()
        u2 = _obs(_result([], synced=False), _dec(per_pop), _cur(), governed=_gov([]))
        ok((not u2["ok"])
           and any("source_health_not_synchronized" in f for f in u2["fail_closed"])
           and not any("eligible_conclusion" in f for f in u2["fail_closed"]),
           "ON unavailable (known universe): all UNAVAILABLE, source-health fail-closed, no NONMEMBER")

        # 5) LIVE path parity: governed=None (what app.py passes) -> fail closed, result unchanged.
        hook._reset(); res = _result(members); snap = copy.deepcopy(res)
        live = _obs(res, _dec(per_pop), _cur(), governed=None)
        ok(res == snap, "ON live(governed=None): builder result unchanged")
        ok((not live["ok"]) and live["error"] is not None,
           "ON live(governed=None): fails closed (runtime pilot BLOCKED — no governed sources)")

        # 6) exception isolation: result without 'sync'.
        hook._reset()
        x = hook.observe_build_nfl_ats_wave({"members": []}, dec=_dec(per_pop), cur=_cur(),
                                            season=2026, created_at=CREATED)
        ok(x is not None and x["ok"] is False and x["stage"] == "hook",
           "ON exception: isolated into the record (never raised)")

        # (defect) non-boolean health must be rejected (no coercion).
        hook._reset()
        bad_health = {"members": [], "sync": {"synchronized": "false", "checked_at_utc": BK},
                      "expected_completed_week": 8}
        h = _obs(bad_health, _dec(per_pop), _cur(), governed=_gov(["PHI", "DAL", "NYG", "WAS"]))
        ok((not h["ok"]) and "boolean" in (h["error"] or ""),
           "ON health coercion: synchronized='false' is rejected (not coerced to True)")

        # (defect) empty / missing decision universe -> explicit expected_universe_unavailable.
        hook._reset()
        eu = _obs(_result(members), _dec({}), _cur(), governed=_gov(["PHI", "DAL"]))
        ok((not eu["ok"]) and "expected_universe_unavailable" in eu["fail_closed"],
           "ON empty universe: explicit expected_universe_unavailable finding (no conserved empty board)")

        # (defect) builder_rules is MANDATORY whenever the observer runs.
        hook._reset()
        nbr = hook.observe_build_nfl_ats_wave(_result(members), dec=_dec(per_pop), cur=_cur(),
                                              season=2026, governed=_gov(["PHI", "DAL", "NYG", "WAS"]),
                                              builder_rules=None, created_at=CREATED)
        ok((not nbr["ok"]) and "builder_rules is required" in (nbr["error"] or ""),
           "ON governed: missing builder_rules fails closed (mandatory comparison)")
        hook._reset()
        mbr = hook.observe_build_nfl_ats_wave(_result(members), dec=_dec(per_pop), cur=_cur(),
                                              season=2026, governed=_gov(["PHI", "DAL", "NYG", "WAS"]),
                                              builder_rules={"membership_threshold": 3}, created_at=CREATED)
        ok((not mbr["ok"]) and "builder_rules missing" in (mbr["error"] or ""),
           "ON governed: malformed (incomplete) builder_rules fails closed")

        # (defect) a MISMATCH in EVERY governed rule field fails closed.
        teams = ["PHI", "DAL", "NYG", "WAS"]
        mismatches = {
            "membership_threshold": lambda g: g.__setitem__("membership_threshold", 5),
            "membership_rule_version": lambda g: g["rule_versions"].__setitem__("membership", 9),
            "ordering_rule_id": lambda g: g.__setitem__("ordering_rule_id", "other_rule"),
            "ordering_rule_version": lambda g: g.__setitem__("ordering_rule_version", "9"),
            "reason_def_version": lambda g: g.__setitem__("reason_def_version", 9),
        }
        for field, mut in mismatches.items():
            hook._reset()
            g = _gov(teams); mut(g)
            r = _obs(_result(members), _dec(per_pop), _cur(), governed=g)
            ok((not r["ok"]) and f"governed {field} does not match the builder constant" in (r["error"] or ""),
               f"ON governed: mismatched {field} fails closed")

        # (defect) governed must supply each rule; a missing one fails closed.
        hook._reset()
        g_missing = _gov(teams); del g_missing["ordering_rule_id"]
        gm = _obs(_result(members), _dec(per_pop), _cur(), governed=g_missing)
        ok((not gm["ok"]) and "ordering_rule_id" in (gm["error"] or ""),
           "ON governed: a missing ordering_rule_id fails closed (hook invents nothing)")

        # (defect) malformed health is validated BEFORE the empty-universe finding.
        hook._reset()
        hb = hook.observe_build_nfl_ats_wave(
            {"members": [], "sync": {"synchronized": "false", "checked_at_utc": BK},
             "expected_completed_week": 8}, dec=_dec({}), cur=_cur(), season=2026,
            governed=_gov(teams), builder_rules=BUILDER_RULES, created_at=CREATED)
        ok((not hb["ok"]) and "boolean" in (hb["error"] or "")
           and "expected_universe_unavailable" not in hb.get("fail_closed", []),
           "ON: malformed health is caught BEFORE the empty-universe finding (not masked)")

        # 7) deterministic: same inputs + injected clock -> identical receipt ids/hashes.
        hook._reset()
        a = _obs(_result(members), _dec(per_pop), _cur(), governed=_gov(["PHI", "DAL", "NYG", "WAS"]))
        b = _obs(_result(members), _dec(per_pop), _cur(), governed=_gov(["PHI", "DAL", "NYG", "WAS"]))
        ok(a["receipt_ids"] == b["receipt_ids"] and a["membership_hash"] == b["membership_hash"],
           "ON deterministic: identical build + injected clock reproduces ids/hashes")

        # latency (local incremental; no assertion).
        N = 3000
        _flag(False)
        off = []
        for _ in range(N):
            r = _result(members); t = time.perf_counter(); _obs(r, _dec(per_pop), _cur()); off.append(
                (time.perf_counter() - t) * 1e6)
        _flag(True)
        on = []
        g = _gov(["PHI", "DAL", "NYG", "WAS"])
        for _ in range(N):
            r = _result(members); t = time.perf_counter(); _obs(r, _dec(per_pop), _cur(), governed=g)
            on.append((time.perf_counter() - t) * 1e6)
        lat = {"off_median_us": round(statistics.median(off), 1), "off_worst_us": round(max(off), 1),
               "on_median_us": round(statistics.median(on), 1), "on_worst_us": round(max(on), 1), "n": N}
        ok(True, f"latency (local, N={N}): OFF median {lat['off_median_us']}us / worst "
                 f"{lat['off_worst_us']}us ; ON median {lat['on_median_us']}us / worst {lat['on_worst_us']}us")
    finally:
        _flag(False); hook._reset()

    return {"clean": not failures, "checks": checks, "failures": failures, "latency": lat}


def main() -> int:
    r = run_qc()
    print("=" * 72)
    print("BUILD_NFL_ATS_WAVE SHADOW CALL-SITE INTEGRATION QC (Phase 2C-dark, Rev 2)")
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
