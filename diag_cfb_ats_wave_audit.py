"""
CFB ATS Audit #3 -- read-only Source->Render evidence for build_cfb_wave_context (/tools/cfb-wave).
NO CFBD request, NO refresh, NO membership/ordering/template change. Uses the RUNTIME artifacts actually
consumed in production (bk_runtime.scenario_read_path manifest + the graded NCAAF_GameLineResults.csv),
not committed seed files. Authoritative identity = (GameID, TeamSide); names are presentation only.
Fingerprints consumed artifacts before/after (exit 4 on mutation).

Chain: runtime manifest -> canonical GameID -> TeamSide identity -> conference eligibility -> ATS grading
-> active cover-streak -> membership (cover_streak>=3, FBS) -> ordering (streak desc, team asc) -> render.

Provider-outage separation: this probe makes NO CFBD call. A CFBD quota exhaustion does NOT make the
last-known-good runtime artifacts stale, and a fresh artifact does NOT prove the provider is up -- the two
are reported independently (artifact freshness from manifest 'updated' + file mtimes; provider state is out
of scope here).

Run on the box (prod/owner), venv python:
    /opt/bankrollkings/venv/bin/python3 /opt/bankrollkings/diag_cfb_ats_wave_audit.py
"""
from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from datetime import datetime, timezone

import pandas as pd

import app
import bk_runtime


def _rt_paths():
    files = ['cfb_line_moves.json', 'cfb_2026_results.json', 'cfb_2026_ats.json']
    out = [("manifest cfb_line_moves.json", str(bk_runtime.scenario_read_path('cfb_line_moves.json')))]
    out.append(("graded NCAAF_GameLineResults.csv", str(app.DATA_DIR / 'tracking' / 'NCAAF_GameLineResults.csv')))
    for f in files[1:]:
        out.append((f, str(bk_runtime.scenario_read_path(f))))
    return out


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


def _et(ts):
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone().strftime('%Y-%m-%d %H:%M %Z')
    except Exception:
        return str(ts)


# ---- synthetic fixtures for the pure core _cfb_cover_streaks_from_df ----------------------------
_COLS = ['MarketType', 'Season', 'OutcomeState', 'GameID', 'Line', 'Week', 'GameDate', 'TeamSide',
         'Team', 'Opponent', 'Conf']


def _row(gid, state, week, date, team, opp, conf='SEC', side='HOME', line=-3.0, season=2026):
    return {'MarketType': 'SPREAD', 'Season': season, 'OutcomeState': state, 'GameID': gid, 'Line': line,
            'Week': week, 'GameDate': date, 'TeamSide': side, 'Team': team, 'Opponent': opp, 'Conf': conf}


def _synthetic():
    checks, failures = [], []
    rows = [
        # ALPHA (FBS): earlier loss then 3 covers -> cover_streak 3; + a 2025 row that must be excluded.
        # GameIDs are positive integers (CFBD form), else bk_runtime.cfb_game_id rejects them as ineligible.
        _row('401001', 'Miss', 1, '2026-09-05', 'ALPHA', 'O1'),
        _row('401002', 'Hit', 2, '2026-09-12', 'ALPHA', 'O2'),
        _row('401003', 'Hit', 3, '2026-09-19', 'ALPHA', 'O3'),
        _row('401004', 'Hit', 4, '2026-09-26', 'ALPHA', 'O4'),
        _row('401099', 'Hit', 15, '2025-12-01', 'ALPHA', 'OZ', season=2025),
        # PUSHY: cover, cover, push, cover -> 1
        _row('401011', 'Hit', 1, '2026-09-05', 'PUSHY', 'O1'),
        _row('401012', 'Hit', 2, '2026-09-12', 'PUSHY', 'O2'),
        _row('401013', 'Push', 3, '2026-09-19', 'PUSHY', 'O3'),
        _row('401014', 'Hit', 4, '2026-09-26', 'PUSHY', 'O4'),
        # RESET: 3 covers then a loss -> 0
        _row('401021', 'Hit', 1, '2026-09-05', 'RESET', 'O1'),
        _row('401022', 'Hit', 2, '2026-09-12', 'RESET', 'O2'),
        _row('401023', 'Hit', 3, '2026-09-19', 'RESET', 'O3'),
        _row('401024', 'Miss', 4, '2026-09-26', 'RESET', 'O4'),
        # CONFLICT: same (GameID, TeamSide) with different result -> conflict (fail closed)
        _row('401031', 'Hit', 1, '2026-09-05', 'CONF', 'O1'),
        _row('401031', 'Miss', 1, '2026-09-05', 'CONF', 'O1'),
        # INELIGIBLE: missing GameID -> ineligible (not malformed)
        _row('', 'Hit', 1, '2026-09-05', 'NOID', 'O1'),
    ]
    df = pd.DataFrame(rows, columns=_COLS)
    res = app._cfb_cover_streaks_from_df(df, 2026)
    per = res['per']

    def cs(t):
        return per.get(t, {}).get('cover_streak')

    (checks if cs('ALPHA') == 3 and per.get('ALPHA', {}).get('decisions') == 4 else failures).append(
        f"earlier loss + prior-season excluded -> ALPHA cover_streak={cs('ALPHA')} decisions={per.get('ALPHA', {}).get('decisions')} (want 3/4)")
    (checks if cs('PUSHY') == 1 else failures).append(f"push interrupts -> PUSHY cover_streak={cs('PUSHY')} (want 1)")
    (checks if cs('RESET') == 0 else failures).append(f"loss resets -> RESET cover_streak={cs('RESET')} (want 0)")
    (checks if res['conflicts'] else failures).append(f"(GameID,TeamSide) conflict detected -> conflicts={res['conflicts']}")
    (checks if res['ineligible'] >= 1 else failures).append(f"missing-GameID row ineligible -> ineligible={res['ineligible']} (want >=1)")
    # conference tri-state
    (checks if app._cfb_conf_class('SEC') == 'FBS' else failures).append("conf 'SEC' -> FBS")
    (checks if app._cfb_conf_class('Big Sky') == 'NON_FBS' else failures).append("conf 'Big Sky' -> NON_FBS (legit exclusion)")
    (checks if app._cfb_conf_class('Mountain Wessst') == 'UNKNOWN' else failures).append(
        "misspelled/renamed conf -> UNKNOWN (fails sync closed, never silently non-FBS)")
    return checks, failures


def main() -> int:
    print("=" * 94)
    print("CFB ATS WAVE AUDIT #3 -- read-only Source->Render evidence (build_cfb_wave_context)")
    print("=" * 94)
    consumed = [p for _, p in _rt_paths()]
    fp0 = _fp(consumed)

    # ---- runtime artifact lineage / freshness (NO provider call) --------------------------------
    print("[RUNTIME ARTIFACTS] (consumed in production; no CFBD request made)")
    for label, p in _rt_paths():
        if os.path.exists(p):
            st = os.stat(p)
            with open(p, 'rb') as fh:
                sha = hashlib.sha256(fh.read()).hexdigest()[:16]
            under_rt = ('runtime' in p.lower()) or (os.environ.get('BK_RUNTIME_DIR', '') and p.startswith(os.environ['BK_RUNTIME_DIR']))
            print(f"  {label}: {p}")
            print(f"      exists sha={sha} size={st.st_size} mtime={_et(st.st_mtime)} "
                  f"{'[under BK_RUNTIME_DIR]' if under_rt else '[repo path]'}")
        else:
            print(f"  {label}: {p}  ABSENT")
    try:
        lm = json.load(open(bk_runtime.scenario_read_path('cfb_line_moves.json'), encoding='utf-8'))
        print(f"  manifest: season={lm.get('season')} updated={lm.get('updated')!r} games={len(lm.get('games', []) or [])}")
    except Exception as exc:
        print(f"  manifest unreadable: {exc}")

    # ---- resolver season ------------------------------------------------------------------------
    print("-" * 94)
    try:
        exp_week, exp_season = app._nfl_expected_completed_week()  # NFL resolver (season label shared)
    except Exception:
        exp_week, exp_season = None, None
    print(f"resolver (shared NFL season anchor): season={exp_season} completed_week={exp_week} "
          "(CFB wave uses the manifest's own week lineage; shown for cross-reference)")

    # ---- REAL build_cfb_wave_context ------------------------------------------------------------
    print("-" * 94); print("[A] REAL build_cfb_wave_context()")
    ctx = app.build_cfb_wave_context()
    sync = ctx.get('wave_sync', {})
    print(f"  wave_available={ctx.get('wave_available')}  wave_unsynced={ctx.get('wave_unsynced')}  "
          f"wave_week={ctx.get('wave_week')}  wave_through_week={ctx.get('wave_through_week')}")
    print(f"  synchronized={sync.get('synchronized')}  reason={sync.get('reason')!r}  read_error={sync.get('read_error')!r}")
    print(f"  manifest_season={sync.get('manifest_season')}  manifest_updated={sync.get('manifest_updated')!r}  "
          f"completed_week={sync.get('completed_week')}")
    print(f"  expected_decisions={sync.get('expected_decisions')}  graded_decisions={sync.get('graded_decisions')}  "
          f"exclusions={sync.get('exclusions')}  missing_count={sync.get('missing_count')}  overdue={sync.get('overdue_decisions')}")
    print(f"  ineligible={sync.get('ineligible')}  malformed_rows={sync.get('malformed_rows')}  "
          f"conflicting_duplicates={sync.get('conflicting_duplicates')}  exact_duplicates_collapsed={sync.get('exact_duplicates_collapsed')}")
    print(f"  manifest_missing_gameid={sync.get('manifest_missing_gameid')}  unknown_conference={sync.get('unknown_conference')}  "
          f"manifest_dup_gameid={sync.get('manifest_dup_gameid')}")
    members = ctx.get('wave_members', [])
    fades = ctx.get('wave_fades', [])
    mem_hash = hashlib.sha256(json.dumps([[m['team'], m['cover_streak']] for m in members], sort_keys=True, default=str).encode()).hexdigest()[:16]
    print(f"  wave_members(cover_streak>=3, FBS)={len(members)}  wave_fades(loss_streak>=3)={len(fades)}  "
          f"overlay_misattributions={ctx.get('overlay_misattributions')}")
    print(f"  membership_hash(team/cover_streak)={mem_hash}")
    for m in members[:8]:
        print(f"    {m['team']}: cover_streak={m['cover_streak']} ats={m.get('ats')} recent={m.get('recent')} pushes={m.get('pushes')}")
    if len(members) > 1:
        order_ok = all((-members[i]['cover_streak'], members[i]['team']) <= (-members[i + 1]['cover_streak'], members[i + 1]['team'])
                       for i in range(len(members) - 1))
        print(f"  ordering (cover_streak desc, team asc) monotonic: {order_ok}")
    print("  display-limit: build_cfb_wave_context returns ALL qualifying members (any cap is view-level).")

    # ---- streak distribution + conference classification (real graded source) -------------------
    print("-" * 94); print("[DISTRIBUTION + FBS GATE] from _cfb_active_cover_streaks(2026)")
    sd = app._cfb_active_cover_streaks(2026)
    if sd.get('read_error'):
        print(f"  read_error={sd['read_error']!r} -> fail closed (UNAVAILABLE, no partial membership)")
    per = sd.get('per', {})
    cs_dist = Counter(v['cover_streak'] for v in per.values())
    conf_class = Counter(app._cfb_conf_class(v.get('conf')) for v in per.values())
    fbs_members = [v for v in per.values() if v['cover_streak'] >= 3 and app._cfb_side_is_fbs(v.get('conf'))]
    print(f"  teams in graded index={len(per)}  cover_streak distribution={dict(sorted(cs_dist.items()))}  "
          f"max={max((v['cover_streak'] for v in per.values()), default=0)}")
    print(f"  conference classification of indexed teams: {dict(conf_class)}  (UNKNOWN in a completed "
          "line-bearing game fails sync closed)")
    print(f"  FBS teams with cover_streak>=3 (should equal wave_members): {len(fbs_members)}")
    print(f"  (GameID,TeamSide) conservation: graded_keys={len(sd.get('graded_keys', set()))} "
          f"conflicts={len(sd.get('conflicts', []))} collapsed={sd.get('collapsed')} "
          f"ineligible={sd.get('ineligible')} malformed={sd.get('malformed')}")

    # ---- SYNTHETIC frozen-contract invariants ---------------------------------------------------
    print("-" * 94); print("[B] FROZEN-CONTRACT INVARIANTS (synthetic, pure core)")
    checks, failures = _synthetic()
    for c in checks:
        print(f"  [ok] {c}")
    for f in failures:
        print(f"  [FAIL] {f}")

    fp1 = _fp(consumed)
    changed = sorted(p for p in consumed if fp0.get(p) != fp1.get(p))
    print("=" * 94)
    print(f"READ-ONLY PROOF: {len(consumed)} artifact(s); {'ALL UNCHANGED' if not changed else 'CHANGED: ' + ', '.join(changed)}")
    if changed:
        print(f"[FAIL] probe mutated: {changed}"); return 4
    return 3 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
