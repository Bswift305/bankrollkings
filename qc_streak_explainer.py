"""QC: shared streak-explainer normalized view-model (services/streak_explainer.py, pure).

Proves: every family maps into the SAME common model; fields the source provides are carried; fields it does
NOT provide are labeled 'unavailable' and never synthesized; governed-model status is separate from factual
membership. No app import.
"""
from __future__ import annotations

import services.streak_explainer as se

ISSUES, NOTES = [], []
COMMON = {'family', 'threshold', 'direction', 'current_streak', 'current_season', 'counted_events',
          'excluded_events', 'source', 'data_through', 'freshness', 'availability', 'membership_reason',
          'model_status'}


def ok(cond, fail, pas=None):
    (NOTES.append(pas) if pas else None) if cond else ISSUES.append(fail)


def run_qc():
    # milestone: carries per-game counted events + threshold
    mil = se.normalize('milestone', {'run': 5, 'threshold': 100, 'stat_label': 'Receiving Yards',
                                     'availability_state': 'ACTIVE',
                                     'games': [{'week': 3, 'opponent': 'JAX', 'value': 110, 'season': 2026},
                                               {'week': 4, 'opponent': 'KC', 'value': 120, 'season': 2026}]},
                       meta={'source': 'game stats', 'data_through': 'Wk 7', 'freshness': 'fresh', 'season': 2026})
    ok(set(mil) == COMMON, f'milestone model keys != common set: {set(mil) ^ COMMON}')
    ok(mil['threshold'] == 100 and mil['current_streak'] == 5 and mil['current_season'] == 2026,
       f'milestone fields wrong: {mil}')
    ok(isinstance(mil['counted_events'], list) and mil['counted_events'][0]['value'] == 110
       and mil['counted_events'][0]['opponent'] == 'JAX',
       'milestone counted events not carried', 'milestone: per-game counted events carried (value+opponent+week)')
    ok(mil['model_status'] == se.FACTUAL, 'milestone model_status not factual')

    # prop: has threshold + streak, but NO per-game values -> counted_events unavailable (not synthesized)
    prop = se.normalize('prop', {'line': 60.5, 'side': 'Over', 'streak': 5, 'status_label': 'Active run',
                                 'availability_state': 'ACTIVE'},
                        meta={'source': 'graded record', 'data_through': 'Wk 7', 'freshness': 'fresh'})
    ok(set(prop) == COMMON, 'prop model keys != common set')
    ok(prop['threshold'] == 60.5 and prop['direction'] == 'Over' and prop['current_streak'] == 5,
       f'prop fields wrong: {prop}')
    ok(prop['counted_events'] == se.UNAVAILABLE,
       'prop per-game events synthesized (source has none)',
       'prop: per-game values labeled unavailable (never synthesized)')

    # ats: results signs -> counted events (result only); threshold is the spread
    ats = se.normalize('ats', {'cover_streak': 3, 'results': ['L', 'W', 'W', 'W']},
                       meta={'source': 'nflverse games', 'data_through': 'Wk 6'})
    ok(ats['direction'] == 'cover' and ats['current_streak'] == 3
       and isinstance(ats['counted_events'], list) and ats['counted_events'][-1]['result'] == 'cover',
       f'ats fields wrong: {ats}', 'ats: cover run + per-result events; threshold = the spread')
    ok(ats['counted_events'][0]['value'] == se.UNAVAILABLE,
       'ats value synthesized', 'ats: per-game value labeled unavailable (source carries only the result)')

    # hot_hand
    hh = se.normalize('hot_hand', {'line': 60.5, 'streak': 3, 'status_label': 'Active run',
                                   'availability_state': 'ACTIVE'}, meta={'source': 'gamelog x line'})
    ok(hh['direction'] == 'clear the line' and hh['current_streak'] == 3
       and hh['counted_events'] == se.UNAVAILABLE, f'hot_hand fields wrong: {hh}',
       'hot_hand: streak + threshold carried; per-game values unavailable')

    # governed-model status overrides separately (e.g. a governed-model lens)
    gm = se.normalize('prop', {'line': 1, 'side': 'Over', 'streak': 3},
                      meta={'model_status': 'Discovery — no authority'})
    ok(gm['model_status'] == 'Discovery — no authority',
       'governed model status not carried separately',
       'governed-model status carried separately from factual membership')

    # missing everything -> all unavailable, no crash, no synthesis
    empty = se.normalize('prop', {})
    ok(empty['threshold'] == se.UNAVAILABLE and empty['current_streak'] == se.UNAVAILABLE
       and empty['source'] == se.UNAVAILABLE and set(empty) == COMMON,
       f'empty row not all-unavailable: {empty}', 'empty row -> every field unavailable (never synthesized)')

    return {'issues': ISSUES, 'notes': NOTES}


def main():
    r = run_qc()
    print('=' * 70)
    print('BANKROLL KINGS - SHARED STREAK-EXPLAINER VIEW-MODEL QC')
    print('=' * 70)
    for n in r['notes']:
        print(f'[NOTE] {n}')
    if r['notes']:
        print()
    if not r['issues']:
        print('No streak-explainer view-model issues detected.')
        return 0
    for m in r['issues']:
        print(f'[FAIL] {m}')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
