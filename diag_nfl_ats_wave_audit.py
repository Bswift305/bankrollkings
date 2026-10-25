"""
NFL ATS Audit #2 -- read-only Source->Render evidence for build_nfl_ats_wave
(docs/ats_wave_contract.md). NO membership/ordering/template/source change. Fingerprints the source +
caches before/after (exit 4 on mutation).

Chain: Source (nflverse games parquet, sha-verified sidecar) -> canonical game_id / reciprocal TeamSide
-> eligibility (current resolver season, event-level completeness) -> ATS grading (result - spread) ->
active trailing cover-streak -> membership (cover_streak >= 3) -> ordering (streak desc, team asc) -> render.

Two layers of evidence:
  A. REAL prod state via build_nfl_ats_wave(): sync/freshness, graded-through, counts, conservation,
     membership + hashes.
  B. SYNTHETIC frozen-contract invariants via the pure core _nfl_ats_decisions_from_games(): push
     interrupts; loss resets; earlier(-season) losses do not disqualify a trailing 3-cover run;
     reciprocity; prior-season rows excluded; an overdue past-grace game fails closed.

Shaped for later Evidence-Ledger migration; no receipts implemented.

Run on the box (prod/owner), venv python, no paid call / no provider refresh:
    /opt/bankrollkings/venv/bin/python3 /opt/bankrollkings/diag_nfl_ats_wave_audit.py
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
from datetime import datetime, timezone

import pandas as pd

import app

app.append_qc_run_log = lambda *a, **k: None
PAST = "2026-09-15"      # well past kickoff+grace relative to NOW below
FUTURE = "2026-12-20"
NOW = datetime(2026, 10, 20, 12, 0)   # fixed Eastern-naive "now" for synthetic fixtures


def _artifacts():
    files = set()
    try:
        import fetch_nfl_games as fgs
        cur = fgs.resolve_current()
        files.add(str(cur.get("parquet_path", "")))
        files.add(str(fgs.pointer_path()))
    except Exception:
        pass
    files.add(str(app.NFL_ATS_SOURCE_FILE))
    for base in (app.DATA_DIR / "historical", app.DATA_DIR / "cache"):
        for pat in ("*nflverse_games*", "*nfl_ats*", "*ats_wave*"):
            files.update(glob.glob(str(base / pat)))
    return sorted(f for f in files if f)


def _fp(paths):
    fp = {}
    for p in paths:
        try:
            st = os.stat(p)
            with open(p, "rb") as fh:
                fp[p] = (hashlib.sha256(fh.read()).hexdigest()[:16], st.st_mtime_ns, st.st_size)
        except OSError:
            fp[p] = None
    return fp


def _g(gid, week, result, spread, home, away, season=2026, gameday=PAST, gametime="13:00"):
    return {"game_id": gid, "season": season, "week": week, "gameday": gameday, "gametime": gametime,
            "home_team": home, "away_team": away, "result": result, "spread_line": spread}


def _synthetic_invariants():
    checks, failures = [], []
    # ALPHA (home each game): earlier loss then 3 covers -> trailing cover_streak = 3
    # result-spread sign: cover=+ , loss=- , push=0. home cover: result=10 spread=3 (7>0).
    rows = [
        _g("2026_01_ALPHA_B", 1, 0, 3, "ALPHA", "B"),     # 0-3=-3 -> home loss
        _g("2026_02_ALPHA_C", 2, 10, 3, "ALPHA", "C"),    # +7 cover
        _g("2026_03_ALPHA_D", 3, 10, 3, "ALPHA", "D"),    # cover
        _g("2026_04_ALPHA_E", 4, 10, 3, "ALPHA", "E"),    # cover
        # PUSHY: cover, cover, push, cover -> trailing run 1 (push interrupts)
        _g("2026_01_PUSHY_B", 1, 10, 3, "PUSHY", "B2"),
        _g("2026_02_PUSHY_C", 2, 10, 3, "PUSHY", "C2"),
        _g("2026_03_PUSHY_D", 3, 3, 3, "PUSHY", "D2"),    # 3-3=0 push
        _g("2026_04_PUSHY_E", 4, 10, 3, "PUSHY", "E2"),
        # RESET: 3 covers then a loss -> trailing cover_streak 0 (loss resets)
        _g("2026_01_RESET_B", 1, 10, 3, "RESET", "B3"),
        _g("2026_02_RESET_C", 2, 10, 3, "RESET", "C3"),
        _g("2026_03_RESET_D", 3, 10, 3, "RESET", "D3"),
        _g("2026_04_RESET_E", 4, 0, 3, "RESET", "E3"),    # loss
        # PRIOR-season cover for ALPHA (2025) must NOT enter 2026 sequence
        _g("2025_18_ALPHA_Z", 18, 10, 3, "ALPHA", "Z", season=2025),
    ]
    dec = app._nfl_ats_decisions_from_games(pd.DataFrame(rows), 2026, NOW)
    per = dec["per"]

    def cs(team):
        return per.get(team, {}).get("cover_streak", None)

    if cs("ALPHA") == 3 and per.get("ALPHA", {}).get("decisions") == 4:
        checks.append("earlier(-season) loss does NOT disqualify a trailing 3-cover run (ALPHA cover_streak=3, 2026 decisions=4, 2025 excluded)")
    else:
        failures.append(f"ALPHA cover_streak={cs('ALPHA')} decisions={per.get('ALPHA', {}).get('decisions')} (want 3 / 4)")
    if cs("PUSHY") == 1:
        checks.append("push interrupts the cover streak (PUSHY W,W,P,W -> 1)")
    else:
        failures.append(f"PUSHY cover_streak={cs('PUSHY')} (want 1)")
    if cs("RESET") == 0:
        checks.append("a loss resets the cover streak (RESET W,W,W,L -> 0)")
    else:
        failures.append(f"RESET cover_streak={cs('RESET')} (want 0)")
    # reciprocity: each completed game yields one cover + one loss (or two pushes)
    recip_ok = all((h == 0 and a == 0) or (h == -a) for (_gid, h, a) in dec["pairs"])
    checks.append("reciprocity holds (each game -> cover/loss mirror, or two pushes)") if recip_ok \
        else failures.append("reciprocity violated in pairs")
    # prior-season exclusion via season_rows (only 2026 rows counted)
    if dec["season_rows"] == 12:
        checks.append("prior-season rows excluded from the calculation (season_rows=12, 2025 row dropped)")
    else:
        failures.append(f"season_rows={dec['season_rows']} (want 12 -- the 2025 row must be excluded)")

    # overdue -> fail closed
    od = [_g("2026_07_LATE_X", 7, None, 3, "LATE", "X", gameday=PAST)]   # past grace, no result
    dec2 = app._nfl_ats_decisions_from_games(pd.DataFrame(od), 2026, NOW)
    sync2 = app._nfl_ats_sync(dec2, 1.0, "now", 2026)
    if dec2["overdue"] and not sync2["synchronized"]:
        checks.append("overdue past-grace ungraded game -> sync fails closed (members would be empty)")
    else:
        failures.append(f"overdue not failing closed: overdue={dec2['overdue']} synchronized={sync2['synchronized']}")

    # within-grace / future ignored (not overdue)
    fut = [_g("2026_20_FUT_Y", 20, None, 3, "FUT", "Y", gameday=FUTURE)]
    dec3 = app._nfl_ats_decisions_from_games(pd.DataFrame(fut), 2026, NOW)
    if not dec3["overdue"] and not dec3["per"]:
        checks.append("future / within-grace unplayed game ignored (not overdue, no decision)")
    else:
        failures.append(f"future game mishandled: overdue={dec3['overdue']} per={list(dec3['per'])}")
    return checks, failures


def main() -> int:
    print("=" * 92)
    print("NFL ATS WAVE AUDIT #2 -- read-only Source->Render evidence (build_nfl_ats_wave)")
    print("=" * 92)
    arts = _artifacts()
    fp0 = _fp(arts)

    # ---- A. REAL prod state --------------------------------------------------------------------
    print("[A] REAL build_nfl_ats_wave()")
    wave = app.build_nfl_ats_wave()
    sync = wave.get("sync", {})
    print(f"  source_label={sync.get('source_label')!r}  source_season={sync.get('source_season')}  "
          f"expected_completed_week={wave.get('expected_completed_week')}")
    print(f"  synchronized={sync.get('synchronized')}  reason={sync.get('reason')!r}")
    print(f"  last_refresh={sync.get('last_refresh')!r}  age_h={sync.get('source_age_hours')} "
          f"budget_h={sync.get('fresh_budget_hours')}  basis={sync.get('freshness_basis')}  "
          f"sha={sync.get('content_sha256')!r} bootstrap={sync.get('bootstrap')}")
    print(f"  graded_through_week={sync.get('graded_through_week')}  graded_decisions={sync.get('graded_decisions')}  "
          f"season_rows={sync.get('season_rows')}")
    print(f"  conflicts={sync.get('conflicts')}  overdue={sync.get('overdue')}  malformed={sync.get('malformed')}  "
          f"classified_exclusions={sync.get('classified_exclusions')}  exact_duplicates_collapsed={sync.get('exact_duplicates_collapsed')}")
    members = wave.get("members", [])
    print(f"  members (cover_streak>={app._WAVE_MIN_STREAK}): {len(members)}")
    mem_hash = hashlib.sha256(json.dumps([[m['team'], m['streak'], m['through_week']] for m in members],
                              sort_keys=True, default=str).encode()).hexdigest()[:16]
    print(f"  membership_hash(team/streak/through_week)={mem_hash}")
    for m in members[:8]:
        print(f"    {m['team']}: streak={m['streak']} through_wk={m['through_week']} weeks={m['weeks_label']!r} pushes={m['pushes']}")
    order_ok = all((-members[i]['streak'], members[i]['team']) <= (-members[i + 1]['streak'], members[i + 1]['team'])
                   for i in range(len(members) - 1)) if len(members) > 1 else True
    print(f"  ordering (streak desc, team asc) monotonic: {order_ok}")
    print("  display-limit: build_nfl_ats_wave returns ALL qualifying members (no builder-level suppression; "
          "any cap is view-level).")

    # ---- conservation from the real parquet ----------------------------------------------------
    print("-" * 92); print("[CONSERVATION] current-season universe vs classified outcomes")
    try:
        import fetch_nfl_games as fgs
        cur = fgs.resolve_current()
        g = pd.read_parquet(cur["parquet_path"])
        _, season = app._nfl_expected_completed_week()
        from zoneinfo import ZoneInfo
        now_et = datetime.now(ZoneInfo("America/New_York")).replace(tzinfo=None)
        dec = app._nfl_ats_decisions_from_games(g, season, now_et)
        gs = g.copy()
        gs["_s"] = pd.to_numeric(gs.get("season"), errors="coerce")
        season_ids = gs[gs["_s"] == season]["game_id"].astype(str).str.strip()
        unique_games = season_ids[season_ids != ""].nunique()
        graded_games = len(dec["pairs"])
        overdue = len(dec["overdue"]); malformed = len(dec["malformed"]); excluded = dec["excluded"]
        conflicts = len(dec["conflicts"]); collapsed = dec["collapsed"]
        residual = unique_games - graded_games - overdue - malformed - excluded - conflicts
        print(f"  season={season}  unique game_ids={unique_games}  graded_games={graded_games}  "
              f"overdue={overdue}  malformed={malformed}  excluded(no-spread)={excluded}  conflicts={conflicts}")
        print(f"  exact-duplicate rows collapsed={collapsed}")
        print(f"  residual (future / within-grace unplayed) = unique - graded - overdue - malformed - "
              f"excluded - conflicts = {residual}  ({'OK, >=0' if residual >= 0 else 'NEGATIVE -> conservation breach'})")
        print(f"  graded_through_week={dec['graded_through_week']}")
        # [DISTRIBUTION] -- is members=0 a legitimately empty board or a calc issue? Show the spread.
        from collections import Counter
        per = dec["per"]
        cs = Counter(v["cover_streak"] for v in per.values())
        ls = Counter(v["loss_streak"] for v in per.values())
        max_cs = max((v["cover_streak"] for v in per.values()), default=0)
        last_wk = Counter(v["last_week"] for v in per.values())
        print(f"  teams with any decision: {len(per)}")
        print(f"  cover_streak distribution: {dict(sorted(cs.items()))}   (max cover_streak={max_cs})")
        print(f"  loss_streak  distribution: {dict(sorted(ls.items()))}")
        print(f"  teams by last graded week: {dict(sorted(last_wk.items(), key=lambda x: (x[0] is None, x[0])))}")
        # a few teams' recent sign sequences (1=cover, -1=loss, 0=push), newest last
        sample = sorted(per.values(), key=lambda v: -v["cover_streak"])[:6]
        for v in sample:
            print(f"    {v['team']}: recent(old->new)={v['recent']}  cover_streak={v['cover_streak']} "
                  f"loss_streak={v['loss_streak']} last_wk={v['last_week']} decisions={v['decisions']}")
        if max_cs >= 3:
            print(f"  => NOTE: max cover_streak is {max_cs} (>=3) but build_nfl_ats_wave returned 0 members -- "
                  "INVESTIGATE a membership/sync gating mismatch.")
        else:
            print(f"  => members=0 is CONSISTENT with the data: no team has a trailing 3+ cover streak "
                  f"(max is {max_cs}); the empty board is factual, not a calc bug.")
    except Exception as exc:
        print(f"  [WARN] conservation read failed: {type(exc).__name__}: {exc}")

    # ---- B. SYNTHETIC frozen-contract invariants -----------------------------------------------
    print("-" * 92); print("[B] FROZEN-CONTRACT INVARIANTS (synthetic, pure core)")
    checks, failures = _synthetic_invariants()
    for c in checks:
        print(f"  [ok] {c}")
    for f in failures:
        print(f"  [FAIL] {f}")

    fp1 = _fp(arts)
    changed = sorted(p for p in arts if fp0.get(p) != fp1.get(p))
    print("=" * 92)
    print(f"READ-ONLY PROOF: {len(arts)} artifact(s); {'ALL UNCHANGED' if not changed else 'CHANGED: ' + ', '.join(changed)}")
    if changed:
        print(f"[FAIL] probe mutated: {changed}"); return 4
    if failures:
        print(f"[FAIL] {len(failures)} contract-invariant failure(s)"); return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
