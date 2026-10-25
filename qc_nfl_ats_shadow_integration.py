"""QC: build_nfl_ats_wave shadow call-site integration (Phase 2C-dark local wiring).

Exercises the EXACT call-site logic (replicated here so app.py / pandas need not be
imported) against representative builder-result doubles. Proves: the builder return value
is deep-equal with the shadow OFF and ON; OFF does zero work (no record); shadow exceptions
are isolated (never raised to the route); the shadow record is inspectable only via the
internal test hook; and reports local incremental latency OFF vs ON (no assertion).
"""
from __future__ import annotations

import copy
import os
import statistics
import time

import services.decision_shadow_boundary as boundary
import services.nfl_ats_shadow_hook as hook

BK = "2026-10-26T13:05:00Z"
CA = "2026-10-26T13:05:05Z"
SHA = "ab" * 32


def _call_site(result, dec, cur, season):
    """Byte-for-byte mirror of the app.py build_nfl_ats_wave call site."""
    try:
        from services.decision_shadow_boundary import shadow_enabled
        if shadow_enabled():
            from services import nfl_ats_shadow_hook as _h
            _h.observe_nfl_ats_wave(result, dec=dec, cur=cur, season=season)
    except Exception:
        pass
    return result


def _flag(on):
    if on:
        os.environ[boundary.FLAG] = "1"
    else:
        os.environ.pop(boundary.FLAG, None)


def _dec(per):
    return {"per": per}


def _cur():
    return {"content_sha256": SHA}


def _result(synced=True, members=None):
    return {"members": members if members is not None else [{"team": "PHI", "streak": 4}],
            "sync": {"synchronized": synced, "checked_at_utc": BK, "content_fetched_at_utc": CA},
            "expected_completed_week": 8}


def _gov(teams):
    return {"build_id": "build-ats-2026w8", "config_version": "cfg-7",
            "rule_versions": {"membership": 3, "ordering": 1}, "ordering_rule_version": "1",
            "observation_seq": 1001, "reason_def_version": 1, "threshold": 3,
            "identity_profiles": {t: {"profile": "team:sport+season", "profile_version": "v1",
                                      "collision_proof": f"ledger#{t}"} for t in teams}}


def run_qc() -> dict:
    checks, failures = [], []

    def ok(cond, label):
        (checks if cond else failures).append(label)

    season = 2026
    per_pop = {"PHI": {"cover_streak": 4}, "DAL": {"cover_streak": 3}, "NYG": {"cover_streak": 1}}
    per_empty = {"NYG": {"cover_streak": 1}, "WAS": {"cover_streak": 2}}

    # --- OFF: zero work, no record, output unchanged -------------------------
    _flag(False); hook._reset()
    res = _result(); snap = copy.deepcopy(res)
    out = _call_site(res, _dec(per_pop), _cur(), season)
    ok(out == snap and out is res, "OFF: builder return value is unchanged (deep-equal)")
    ok(hook.last_record() is None, "OFF: no shadow record produced (zero work)")

    # --- ON: output still unchanged; record produced via the internal hook ---
    try:
        _flag(True)

        # populated board (governed evidence supplied) -> parity passes.
        hook._reset()
        res = _result(); snap = copy.deepcopy(res)
        out = _call_site(res, _dec(per_pop), _cur(), season)
        rec = hook.last_record()
        # Observe directly with governed evidence (the call site passes governed=None by
        # default; here we exercise the conformant mapping a future builder would enable).
        hook._reset()
        rec_g = hook.observe_nfl_ats_wave(_result(), dec=_dec(per_pop), cur=_cur(), season=season,
                                          governed=_gov(["PHI", "DAL", "NYG"]))
        ok(out == snap and out is res, "ON: builder return value is unchanged (deep-equal)")
        ok(rec is not None, "ON: a shadow record is produced and inspectable via the hook")
        ok(rec_g["ok"] and rec_g["parity"]["all"], "ON populated+governed: shadow parity passes")

        # honest-empty board (governed) -> ok, empty-state.
        hook._reset()
        e = hook.observe_nfl_ats_wave(_result(), dec=_dec(per_empty), cur=_cur(), season=season,
                                      governed=_gov(["NYG", "WAS"]))
        ok(e["ok"] and e["parity"]["empty_state"], "ON honest-empty+governed: ok")

        # unhealthy source with a member present -> fail closed.
        hook._reset()
        u = hook.observe_nfl_ats_wave(_result(synced=False), dec=_dec(per_pop), cur=_cur(),
                                      season=season, governed=_gov(["PHI", "DAL", "NYG"]))
        ok((not u["ok"]) and any("source_health_not_synchronized" in f for f in u["fail_closed"]),
           "ON unhealthy-source: fail-closed source-health finding")

        # missing provenance (the CURRENT builder: governed=None) -> fail closed, isolated.
        hook._reset()
        res = _result(); snap = copy.deepcopy(res)
        out = _call_site(res, _dec(per_pop), _cur(), season)  # call site passes governed=None
        mp = hook.last_record()
        ok(out == snap, "ON missing-provenance: builder return value still unchanged")
        ok((not mp["ok"]) and mp["error"] is not None,
           "ON missing-provenance: shadow fails closed (governed evidence absent)")

        # adapter/hook exception (result without 'sync') -> isolated, never raised.
        hook._reset()
        bad = {"members": [], "expected_completed_week": 8}  # no 'sync'
        raised = False
        try:
            _call_site(bad, _dec(per_pop), _cur(), season)
        except Exception:
            raised = True
        xr = hook.last_record()
        ok(not raised, "ON adapter-exception: call site never raises (no 500)")
        ok(xr is not None and xr["ok"] is False and xr["stage"] == "hook",
           "ON adapter-exception: failure isolated into the record")

        # --- latency (local incremental; no assertion) -----------------------
        N = 3000
        _flag(False)
        off = []
        for _ in range(N):
            r = _result(); t = time.perf_counter(); _call_site(r, _dec(per_pop), _cur(), season)
            off.append((time.perf_counter() - t) * 1e6)
        _flag(True)
        on = []
        for _ in range(N):
            r = _result(); t = time.perf_counter()
            hook.observe_nfl_ats_wave(r, dec=_dec(per_pop), cur=_cur(), season=season,
                                      governed=_gov(["PHI", "DAL", "NYG"]))
            on.append((time.perf_counter() - t) * 1e6)
        lat = {"off_median_us": round(statistics.median(off), 1), "off_worst_us": round(max(off), 1),
               "on_median_us": round(statistics.median(on), 1), "on_worst_us": round(max(on), 1),
               "n": N}
        ok(True, f"latency (local, N={N}): OFF median {lat['off_median_us']}us / worst "
                 f"{lat['off_worst_us']}us ; ON median {lat['on_median_us']}us / worst "
                 f"{lat['on_worst_us']}us")
    finally:
        _flag(False); hook._reset()

    return {"clean": not failures, "checks": checks, "failures": failures, "latency": lat}


def main() -> int:
    r = run_qc()
    print("=" * 72)
    print("BUILD_NFL_ATS_WAVE SHADOW CALL-SITE INTEGRATION QC (Phase 2C-dark)")
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
