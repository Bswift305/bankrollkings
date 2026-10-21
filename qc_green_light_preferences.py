"""QC: Green Light preference workspace — store + registry (commit 2, no UI).

Proves the contract's verification points that the pure layer owns:
- same factual source universe before/after preferences (visible+hidden is a partition of exactly the
  available keys; nothing outside is added);
- deterministic lens ordering (identical output across repeated calls);
- hidden-by-user count equals what the user's filters removed;
- Reset to Default (empty prefs) restores the house default order with nothing hidden;
- no model-based membership suppression (every hide reason is VIEW-class; a governed-model lens is never
  auto-hidden — only a user action or sport filter hides anything);
- validation fails safe (unknown lens keys / sports / markets / display dropped; bad input -> defaults);
- no Decision Journal or draft-store import in the module.
Pure module; exits 0 when all hold. (Account-bound store isolation + route import-guard are covered by the
commit-3 route QC, since they need the app request layer.)
"""
from __future__ import annotations

import services.green_light_lenses as gl

ISSUES, NOTES = [], []


def ok(cond, fail_msg, pass_msg=None):
    if cond:
        if pass_msg:
            NOTES.append(pass_msg)
    else:
        ISSUES.append(fail_msg)


def run_qc():
    all_keys = list(gl.LENS_KEYS)

    # 1. partition / same universe: visible + hidden == available, disjoint, subset of available
    prefs = {'lens_hidden': ['heat_map', 'weather'], 'lens_order': ['matchup_context', 'heat_map']}
    r = gl.apply_lens_preferences(all_keys, prefs)
    vis, hid = set(r['visible']), {h['key'] for h in r['hidden']}
    ok(vis.isdisjoint(hid), 'visible and hidden overlap')
    ok(vis | hid == set(all_keys), 'visible+hidden != available universe')
    ok(set(r['order']) == set(all_keys) and len(r['order']) == len(all_keys),
       'order is not exactly the available universe')
    # nothing outside the available set is ever produced
    subset = ['heat_map', 'weather', 'contradictions']
    rs = gl.apply_lens_preferences(subset, prefs)
    ok(set(rs['order']) == set(subset), 'order introduced keys outside the available set')
    NOTES.append('same factual universe: visible+hidden is an exact partition of the available keys')

    # 2. determinism
    a = gl.apply_lens_preferences(all_keys, prefs)
    b = gl.apply_lens_preferences(all_keys, prefs)
    ok(a == b, 'ordering/partition is not deterministic', 'deterministic lens ordering')
    # user order honored, then remaining in default order
    ok(r['order'][:2] == ['matchup_context', 'heat_map'], 'user lens_order not honored first')
    rest = r['order'][2:]
    default_rest = [k for k in gl.default_lens_order() if k not in ('matchup_context', 'heat_map')]
    ok(rest == default_rest, 'remaining lenses not in deterministic default order',
       'user order first, remaining lenses in stable default order')

    # 3. hidden-by-user count
    ok(r['hidden_count'] == 2 and {h['key'] for h in r['hidden']} == {'heat_map', 'weather'},
       f'hidden count/keys wrong: {r["hidden_count"]}', 'hidden-by-user count matches the user filter')
    ok(all(h['reason'] == gl.HIDDEN_BY_USER for h in r['hidden']),
       'user-hidden lenses not tagged HIDDEN_BY_USER')

    # 4. reset to default: empty prefs -> house default order, nothing hidden
    d = gl.apply_lens_preferences(all_keys, {})
    ok(d['order'] == gl.default_lens_order() and d['hidden_count'] == 0 and d['visible'] == gl.default_lens_order(),
       'empty prefs did not restore the house default', 'reset/empty prefs restores the house default')

    # 5. no model-based membership suppression; every hide reason is VIEW-class
    reasons = {h['reason'] for h in r['hidden']}
    ok(reasons <= set(gl.VIEW_REASONS), f'a non-VIEW hide reason appeared: {reasons}')
    # governed-model lens is never auto-hidden when in-sport and not user-hidden
    gm = gl.apply_lens_preferences(all_keys, {})
    ok('governed_models' in gm['visible'], 'governed-model lens auto-hidden with no user action',
       'no model-based suppression: hides are VIEW-class only; governed model never auto-hidden')
    # sport filter is VIEW-class OUT_OF_SPORT, not a factual drop
    sp = gl.apply_lens_preferences(['ats_waves', 'heat_map'], {'sports': ['cfb']})
    hk = {h['key']: h['reason'] for h in sp['hidden']}
    ok(sp['visible'] == ['ats_waves'] and hk.get('heat_map') == gl.OUT_OF_SPORT,
       f'sport filter wrong: visible={sp["visible"]} hidden={hk}',
       'sport filter hides out-of-sport lenses as VIEW-class OUT_OF_SPORT')

    # 6. validation fails safe
    dirty = {'lens_order': ['heat_map', 'NOPE', 123, 'heat_map'], 'lens_hidden': ['weather', 'bogus'],
             'sports': ['nfl', 'martian'], 'markets': ['rec_yds', 'BAD KEY!', 'x' * 99],
             'display': {'density': 'ultrawide', 'why_expanded': 'yes'}, 'junk': {'a': 1}}
    v = gl.validate_greenlight_prefs(dirty)
    ok(v.get('lens_order') == ['heat_map'], f'unknown/dup lens_order keys not cleaned: {v.get("lens_order")}')
    ok(v.get('lens_hidden') == ['weather'], 'unknown lens_hidden keys not cleaned')
    ok(v.get('sports') == ['nfl'], 'unknown sports not dropped')
    ok(v.get('markets') == ['rec_yds'], f'bad markets not dropped: {v.get("markets")}')
    ok('display' not in v, 'invalid display values not dropped')
    ok('junk' not in v, 'unknown top-level key retained')
    ok(gl.validate_greenlight_prefs('not a dict') == {} and gl.validate_greenlight_prefs(None) == {},
       'non-dict prefs not coerced to defaults', 'validation fails safe: unknown/invalid fields dropped')

    # 7. no Journal / draft-store coupling in the module
    src = open(gl.__file__, encoding='utf-8', errors='replace').read()
    import re as _re
    ok(not _re.search(r'^\s*(from|import)\s+\S*journal', src, _re.MULTILINE),
       'module imports a journal')
    ok('KingsTicketDraftStore' not in src and 'DraftService' not in src and 'kings_tickets_drafts' not in src,
       'module couples to the ticket draft store',
       'no Decision Journal or draft-store coupling in the lens module')

    return {'issues': ISSUES, 'notes': NOTES}


def main():
    r = run_qc()
    print('=' * 68)
    print('BANKROLL KINGS - GREEN LIGHT PREFERENCES QC (store + registry, commit 2)')
    print('=' * 68)
    for n in r['notes']:
        print(f'[NOTE] {n}')
    if r['notes']:
        print()
    if not r['issues']:
        print('No green-light preference issues detected.')
        return 0
    for m in r['issues']:
        print(f'[FAIL] {m}')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
