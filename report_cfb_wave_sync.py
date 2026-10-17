"""Production synchronization report for the CFB Active ATS Wave (docs/ats_wave_contract.md).

Read-only. Prints ONLY the contracted fields, in order, so the operator can decide whether the
Wave is operational. Member names are printed ONLY when synchronized is true; otherwise the honest
unavailable state stands and the grading pipeline is investigated separately -- the cover-percentage
fallback is never restored.

Run on the production box via SSM:
    sudo -u ubuntu /opt/bankrollkings/venv/bin/python /opt/bankrollkings/report_cfb_wave_sync.py
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import app

SEASON = 2026
BASE = Path(__file__).resolve().parent


def _deployed_commit() -> str:
    try:
        return subprocess.check_output(['git', 'rev-parse', '--short', 'HEAD'], cwd=str(BASE),
                                       stderr=subprocess.DEVNULL, text=True).strip() or 'unknown'
    except Exception:
        return 'unknown'


def main() -> int:
    import bk_runtime
    lm = bk_runtime.read_json('cfb_line_moves.json', {})   # runtime copy (never the tracked seed)

    streak_data = app._cfb_active_cover_streaks(SEASON)
    games = lm.get('games') if isinstance(lm.get('games'), list) else []
    moves = [g for g in games if not g.get('completed') and g.get('spread_now') is not None]
    slate_week = min((g['week'] for g in moves), default=None)
    completed_week = (slate_week - 1) if slate_week else None
    sync = app._cfb_ats_sync(streak_data, lm, completed_week, SEASON)

    print('=' * 60)
    print('CFB ACTIVE ATS WAVE - PRODUCTION SYNCHRONIZATION REPORT')
    print('=' * 60)
    print(f'deployed commit            : {_deployed_commit()}')
    print(f'manifest season            : {sync.get("manifest_season")}')
    print(f'manifest updated           : {sync.get("manifest_updated")}')
    print(f'displayed slate week       : {slate_week}')
    print(f'expected completed FBS dec.: {sync.get("expected_decisions")}')
    print(f'canonical graded decisions : {sync.get("graded_decisions")}')
    print(f'legitimate exclusions      : {sync.get("exclusions")}')
    # Declared integrity counters (all must be zero to close).
    counters = {
        'missing_decisions': sync.get('missing_count'),
        'overdue_decisions': sync.get('overdue_decisions'),
        'conflicting_duplicates': sync.get('conflicting_duplicates'),
        'exact_duplicates_collapsed': sync.get('exact_duplicates_collapsed'),
        'malformed_rows': sync.get('malformed_rows'),
        'ineligible_rows': sync.get('ineligible'),
        'manifest_missing_gameid': sync.get('manifest_missing_gameid'),
        'manifest_dup_gameid': sync.get('manifest_dup_gameid'),
        'unknown_conference': sync.get('unknown_conference'),
    }
    for label, val in counters.items():
        print(f'{label:27}: {val}')
    if sync.get('reason'):
        print(f'reason                     : {sync.get("reason")}')
    synced = bool(sync.get('synchronized'))
    print(f'synchronized               : {synced}')

    # exact_duplicates_collapsed is informational (an identical repeat is harmless); every OTHER counter
    # must be exactly zero. overlay_misattributions must be exactly 0.
    bad = [k for k, v in counters.items()
           if k != 'exact_duplicates_collapsed' and (v or 0) != 0]
    overlay_mis = None
    if synced:
        ctx = app.build_cfb_wave_context()
        if ctx.get('wave_unsynced'):              # rendered context flipped to unsynchronized
            synced = False
            bad.append('rendered_context_unsynced')
        members = ctx.get('wave_members', []) if not ctx.get('wave_unsynced') else []
        overlay_mis = ctx.get('overlay_misattributions')
        print(f'overlay_misattributions    : {overlay_mis}')
        print(f'member count               : {len(members)}')
        print('members                    : ' + (', '.join(m['team'] for m in members) or '(none)'))
    else:
        print('member count               : (withheld - not synchronized; honest unavailable state stands)')
        miss = sync.get('missing') or []
        if miss:
            print('sample missing (GameID, side):')
            for m in miss[:25]:
                print(f'    {m}')
    if overlay_mis != 0:                          # must be exactly 0 (never None/unavailable at close)
        bad.append('overlay_misattributions')
    print('-' * 60)
    rc = 0 if (synced and not bad) else 1
    print(f'[EXIT {rc}] ' + ('CFB synchronized; all declared integrity counters zero.'
                             if rc == 0 else 'NOT closable: ' + ', '.join(sorted(set(bad)) or ['unsynchronized'])))
    return rc


if __name__ == '__main__':
    raise SystemExit(main())
