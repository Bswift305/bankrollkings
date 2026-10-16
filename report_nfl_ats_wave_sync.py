"""Production synchronization + freshness report for the NFL Active ATS Wave
(docs/ats_wave_contract.md + docs/nfl_ats_wave_source_characterization.md).

Read-only. Prints ONLY the contracted fields and withholds member names unless synchronized. When
synchronized is false the honest unavailable state stands and the source/grading pipeline is
investigated separately -- never a prior-season fallback.

Run on the production box via SSM:
    sudo -u ubuntu /opt/bankrollkings/venv/bin/python /opt/bankrollkings/report_nfl_ats_wave_sync.py
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import app

BASE = Path(__file__).resolve().parent


def _deployed_commit() -> str:
    try:
        return subprocess.check_output(['git', 'rev-parse', '--short', 'HEAD'], cwd=str(BASE),
                                       stderr=subprocess.DEVNULL, text=True).strip() or 'unknown'
    except Exception:
        return 'unknown'


def main() -> int:
    res = app.build_nfl_ats_wave()
    s = res['sync']
    print('=' * 60)
    print('NFL ACTIVE ATS WAVE - PRODUCTION SYNCHRONIZATION REPORT')
    print('=' * 60)
    print(f'deployed commit            : {_deployed_commit()}')
    print(f'source                     : {s.get("source_label")}')
    print(f'active season (explicit)   : {s.get("source_season")}')
    print(f'source last refresh        : {s.get("last_refresh")}')
    print(f'source age / budget (h)    : {s.get("source_age_hours")} / {s.get("fresh_budget_hours")}')
    print(f'expected completed week    : {res.get("expected_completed_week")}')
    print(f'graded decisions           : {s.get("graded_decisions")}')
    print(f'graded through week        : {s.get("graded_through_week")}')
    print(f'exact duplicates collapsed : {s.get("exact_duplicates_collapsed")}')
    print(f'conflicts                  : {s.get("conflicts")}')
    print(f'overdue (past-grace)       : {s.get("overdue")}')
    print(f'malformed recorded spreads : {s.get("malformed")}')
    print(f'classified exclusions      : {s.get("classified_exclusions")}')
    print(f'season rows                : {s.get("season_rows")}')
    if s.get('reason'):
        print(f'reason                     : {s.get("reason")}')
    synced = bool(s.get('synchronized'))
    print(f'synchronized               : {synced}')
    if synced:
        members = res['members']
        print(f'member count               : {len(members)}')
        print('members                    : '
              + (', '.join(f"{m['team']}({m['streak']})" for m in members) or '(none)'))
    else:
        print('member count               : (withheld - not synchronized; honest unavailable state stands)')
    print('-' * 60)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
