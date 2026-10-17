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
import bk_runtime

SEASON = 2026
BASE = Path(__file__).resolve().parent

# Every declared integrity counter must be PRESENT, an integer, and ZERO to close (exact_duplicates_
# collapsed is gated at zero for this launch -- an identical duplicate means the producer is wrong).
DECLARED_COUNTERS = ('missing_count', 'overdue_decisions', 'conflicting_duplicates',
                     'exact_duplicates_collapsed', 'malformed_rows', 'ineligible',
                     'manifest_missing_gameid', 'manifest_dup_gameid', 'unknown_conference')


def evaluate_closure(sync, overlay_misattributions, rendered_unsynced):
    """(rc, bad). A MISSING/None/Boolean/negative/non-integer counter is a schema mismatch and fails
    (never a silent zero). overlay_misattributions must be exactly 0 and present. Testable."""
    bad = []
    for k in DECLARED_COUNTERS:
        v = sync.get(k, None)
        if not bk_runtime.valid_int_counter(v):
            bad.append(f'{k}=invalid({v!r})')
        elif v != 0:
            bad.append(f'{k}={v}')
    if not bk_runtime.valid_int_counter(overlay_misattributions) or overlay_misattributions != 0:
        bad.append(f'overlay_misattributions={overlay_misattributions!r}')
    if not sync.get('synchronized'):
        bad.append('not_synchronized')
    if rendered_unsynced:
        bad.append('rendered_context_unsynced')
    return (0 if not bad else 1), bad


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

    overlay_mis, rendered_unsynced = None, False
    if synced:
        ctx = app.build_cfb_wave_context()
        rendered_unsynced = bool(ctx.get('wave_unsynced'))
        members = ctx.get('wave_members', []) if not rendered_unsynced else []
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
    rc, bad = evaluate_closure(sync, overlay_mis, rendered_unsynced)
    print('-' * 60)
    print(f'[EXIT {rc}] ' + ('CFB synchronized; all declared integrity counters present and zero.'
                             if rc == 0 else 'NOT closable: ' + ', '.join(bad)))
    return rc


if __name__ == '__main__':
    raise SystemExit(main())
