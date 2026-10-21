"""QC: Green Light lens-adapter framework (services/green_light_adapters.py) — pure, no app import.

Proves the uniform envelope + the invariants every real adapter inherits:
- canonical membership count preserved; universe_hash == gl_hash (Green Light adds/suppresses nothing);
- preference sport/market filtering changes only the eligible subset + filtered count, never the universe;
- availability derivation is never a silent zero (empty/stale/gated -> unavailable/stale/gated);
- three real, never-combined aggregate counts (incl. a wholly-unavailable lens counted, not zeroed);
- failure isolation: a raising/garbage adapter abstains cleanly; the seven failure modes each yield a clean
  envelope without escaping an exception.
Exits 0 when all hold.
"""
from __future__ import annotations

import services.green_light_adapters as ga

ISSUES, NOTES = [], []


def ok(cond, fail, pas=None):
    (NOTES.append(pas) if pas else None) if cond else ISSUES.append(fail)


def _m(i, sport='nfl', market='receptions', **k):
    base = {'id': f'{sport}:{market}:{i}', 'sport': sport, 'market': market, 'label': f'item {i}',
            'why': 'cleared the threshold', 'data_through': 'Wk 6', 'contradiction': False,
            'unavailable': False, 'stale': False, 'gated': False}
    base.update(k)
    return base


def run_qc():
    mem = [_m(0), _m(1), _m(2), _m(3, sport='cfb', market='spread'), _m(4, sport='cfb', market='total')]

    # 1. canonical count + hash equality (no add/suppress)
    e = ga.build_envelope('heat_map', 'Heat Map', 'fact', 'nfl', 'receptions', mem, source='nflverse',
                          data_through='Wk 6')
    ok(e['membership_count'] == 5, 'canonical count wrong')
    ok(e['universe_hash'] == e['gl_hash'] and e['no_suppression'], 'universe != GL universe (suppression)')
    ref = ga._hash_ids([x['id'] for x in mem])
    ok(e['universe_hash'] == ref, 'universe hash not reproducible from membership')
    # dropping a record changes the hash -> suppression would be detectable
    ok(ga._hash_ids([x['id'] for x in mem[:4]]) != ref, 'hash insensitive to a dropped record')
    NOTES.append('canonical universe preserved; universe_hash==gl_hash; hash detects a dropped record')

    # 2. preference filtering changes eligible subset, NOT the universe
    e2 = ga.build_envelope('heat_map', 'Heat Map', 'fact', 'nfl', 'receptions', mem,
                           prefs={'sports': ['nfl']})
    ok(e2['membership_count'] == 5 and e2['eligible_count'] == 3 and e2['filtered_by_pref'] == 2,
       f'sport filter counts wrong: {e2["eligible_count"]}/{e2["filtered_by_pref"]}',
       'sport pref filters eligible subset, universe count preserved')
    e3 = ga.build_envelope('heat_map', 'Heat Map', 'fact', 'nfl', 'receptions', mem,
                           prefs={'sports': ['nfl'], 'markets': ['receptions']})
    ok(e3['eligible_count'] == 3, 'market filter within sport wrong')
    e4 = ga.build_envelope('heat_map', 'Heat Map', 'fact', 'nfl', 'receptions', mem,
                           prefs={'sports': ['cfb'], 'markets': ['spread']})
    ok(e4['eligible_count'] == 1 and e4['membership_count'] == 5,
       'cfb+spread filter wrong', 'market vocabulary narrows within sport; universe intact')

    # 3. availability derivation is never a silent zero
    ok(ga.build_envelope('x', 'x', 'fact', 'nfl', None, [])['availability'] == ga.UNAVAILABLE,
       'empty membership not UNAVAILABLE (silent zero)')
    ok(ga.build_envelope('x', 'x', 'fact', 'nfl', None, [_m(0, gated=True)])['availability'] == ga.GATED,
       'all-gated not GATED')
    ok(ga.build_envelope('x', 'x', 'fact', 'nfl', None, [_m(0, stale=True)])['availability'] == ga.STALE,
       'all-stale not STALE')
    ok(ga.build_envelope('x', 'x', 'fact', 'nfl', None, [_m(0), _m(1, unavailable=True)])['availability'] == ga.PARTIAL,
       'mixed not PARTIAL')
    ok(ga.build_envelope('x', 'x', 'fact', 'nfl', None, [_m(0)])['availability'] == ga.AVAILABLE,
       'clean not AVAILABLE')
    NOTES.append('availability never a silent zero (empty/stale/gated/partial/available all derived)')

    # 4. abstain + safe_adapter isolation
    ab = ga.abstain_envelope('weather', 'Weather', 'fact', 'nfl', None, 'missing_file')
    ok(ab['availability'] == ga.UNAVAILABLE and ab['membership_count'] == 0 and ab['context_note'] == 'missing_file'
       and ab['no_suppression'], 'abstain envelope malformed')
    ok(ga.safe_adapter('k', 'L', 'fact', lambda: (_ for _ in ()).throw(RuntimeError('boom')))['context_note']
       .startswith('adapter_exception'), 'exception not isolated to abstain')
    ok(ga.safe_adapter('k', 'L', 'fact', lambda: 'not an envelope')['context_note'] == 'adapter_bad_envelope',
       'garbage envelope not rejected')
    ok(ga.safe_adapter('k', 'L', 'fact', lambda: e)['membership_count'] == 5, 'good adapter not passed through')
    NOTES.append('failure isolation: a raising/garbage adapter abstains cleanly (workspace unaffected)')

    # 5. the seven failure modes each yield a clean envelope, no exception escapes
    modes = {
        'missing_file': lambda: ga.abstain_envelope('k', 'L', 'fact', reason='missing_file'),
        'stale_source': lambda: ga.build_envelope('k', 'L', 'fact', 'nfl', None, [_m(0, stale=True)]),
        'legal_gate': lambda: ga.build_envelope('k', 'L', 'governed-model', 'nba', None, [_m(0, gated=True)]),
        'malformed_row': lambda: ga.build_envelope('k', 'L', 'fact', 'nfl', None, [{'oops': 1}]),
        'cache_miss': lambda: ga.abstain_envelope('k', 'L', 'fact', reason='cache_miss'),
        'empty_current_season': lambda: ga.build_envelope('k', 'L', 'fact', 'nfl', None, []),
        'builder_exception': lambda: ga.safe_adapter('k', 'L', 'fact', lambda: 1 / 0),
    }
    for name, fn in modes.items():
        env = ga.safe_adapter('k', 'L', 'fact', fn)
        ok(isinstance(env, dict) and env['availability'] in ga.AVAILABILITY_STATES,
           f'failure mode {name} did not yield a clean envelope')
    # malformed row must not crash and must still count as a (degraded) member
    mr = ga.build_envelope('k', 'L', 'fact', 'nfl', None, [{'oops': 1}], include_items=True)
    ok(mr['membership_count'] == 1 and mr['items'][0]['id'] == '', 'malformed row crashed compaction')
    NOTES.append('seven failure modes (missing file/stale/legal/malformed/cache-miss/empty-season/exception) clean')

    # 6. three real counts, never combined; wholly-unavailable lens counted (not zeroed); out-of-sport
    # lens contributes its whole membership to the sport/market-filtered count.
    visible = [
        ga.build_envelope('a', 'A', 'fact', 'nfl', None, [_m(0), _m(1, unavailable=True)]),      # 1 unavailable item
        ga.build_envelope('b', 'B', 'fact', 'nfl', None, mem, prefs={'sports': ['nfl']}),         # 2 filtered
        ga.abstain_envelope('c', 'C', 'fact', reason='missing_file'),                             # wholly unavailable -> +1
    ]
    out_of_sport = [ga.build_envelope('d', 'D', 'fact', 'cfb', None, [_m(0, sport='cfb'), _m(1, sport='cfb')])]  # 2 items
    counts = ga.aggregate_counts(visible, out_of_sport, hidden_by_user_keys=['z1', 'z2'])
    ok(counts['lenses_hidden_by_user'] == 2, 'hidden-by-user count wrong')
    ok(counts['eligible_items_hidden_by_pref'] == 4,
       f'filtered items wrong: {counts["eligible_items_hidden_by_pref"]} (2 visible + 2 out-of-sport)')
    ok(counts['items_unavailable_by_gate'] == 2, f'unavailable count wrong: {counts["items_unavailable_by_gate"]}')
    NOTES.append('three distinct counts from the same universe; out-of-sport membership -> filtered; wholly-unavailable lens counted')

    return {'issues': ISSUES, 'notes': NOTES}


def main():
    r = run_qc()
    print('=' * 68)
    print('BANKROLL KINGS - GREEN LIGHT ADAPTER FRAMEWORK QC')
    print('=' * 68)
    for n in r['notes']:
        print(f'[NOTE] {n}')
    if r['notes']:
        print()
    if not r['issues']:
        print('No adapter-framework issues detected.')
        return 0
    for m in r['issues']:
        print(f'[FAIL] {m}')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
