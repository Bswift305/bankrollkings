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
    lm_path = BASE / 'data' / 'scenarios' / 'cfb_line_moves.json'
    try:
        with open(lm_path, 'r', encoding='utf-8') as fh:
            lm = json.load(fh)
    except (OSError, ValueError):
        lm = {}

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
    print(f'exact duplicates collapsed : {sync.get("duplicates_collapsed")}')
    print(f'conflicts                  : {sync.get("conflicts")}')
    print(f'missing decisions          : {sync.get("missing_count")}')
    if sync.get('reason'):
        print(f'reason                     : {sync.get("reason")}')
    synced = bool(sync.get('synchronized'))
    print(f'synchronized               : {synced}')

    if synced:
        ctx = app.build_cfb_wave_context()
        members = ctx.get('wave_members', []) if not ctx.get('wave_unsynced') else []
        print(f'member count               : {len(members)}')
        print('members                    : ' + (', '.join(m['team'] for m in members) or '(none)'))
    else:
        print('member count               : (withheld - not synchronized; honest unavailable state stands)')
    print('-' * 60)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
