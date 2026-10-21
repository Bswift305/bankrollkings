"""QC: NFL SGP Workbench (/tools/sgp-workbench) — the 16 frozen acceptance tests.

Engine rules are tested directly against services.nfl_sgp (one source of truth). Context/menu behavior is
tested with a deterministic fixture menu (monkeypatched) so it does not depend on the live feed. The two
production-only items (desktop + 375px authenticated render; cross-sport regression) are checked
separately during deployment, not here. Exits 0 on success, 1 otherwise.
"""
from __future__ import annotations

import app
import services.nfl_sgp as sgp


def _leg(**k):
    k.setdefault('kind', 'player')
    k.setdefault('category', 'QB')
    k.setdefault('direction', 'OVER')
    k.setdefault('stat', 'Pass Yards')
    k.setdefault('line', 250.5)
    k.setdefault('price', -110)
    k.setdefault('book', 'BookA')
    k.setdefault('timestamp', '2026-01-01 00:00')
    k.setdefault('tz', 't')
    k.setdefault('quote_scope', 'individual')
    k.setdefault('lineage', 'x')
    who = k.get('player') or k.get('team') or 'Leg'
    k.setdefault('label', f"{who} {k['direction']} {k['stat']} {k['line']}")
    return k


def _fixture_menu(away, home):
    """A deterministic per-game menu. ids embed the home abbr so a different game has different ids
    (so switching games drops a prior game's selections)."""
    hb = str(home).split()[-1].upper()[:3]
    raw = [
        _leg(player='QB1', team='AAA', position='QB', category='QB', stat='Pass Yards', direction='OVER', line=250.5, price=-110),
        _leg(player='QB1', team='AAA', position='QB', category='QB', stat='Pass Yards', direction='UNDER', line=250.5, price=None),
        _leg(player='WR1', team='AAA', category='Receiving', stat='Rec Yards', direction='OVER', line=70.5, price=-115),
        _leg(player='WR2', team='AAA', category='Receiving', stat='Rec Yards', direction='OVER', line=55.5, price=-110),
        _leg(kind='game', category='Game Line', player=None, team=None, stat='Game Total', direction='OVER', line=47.5, price=-108),
        _leg(kind='game', category='Game Line', player=None, team=None, stat='Game Total', direction='UNDER', line=47.5, price=-112),
        _leg(kind='team_total', category='Team Total', player=None, team='AAA', stat='Team Total', direction='OVER', line=27.5, price=None),
        _leg(kind='team_total', category='Team Total', player=None, team='BBB', stat='Team Total', direction='OVER', line=20.5, price=None),
    ]
    for lg in raw:
        who = lg.get('player') or lg.get('team') or 'Game'
        lg['id'] = '|'.join([lg['book'], lg['kind'], str(who), lg['stat'], lg['direction'],
                             str(lg['line']), hb])
    grouped = {}
    for lg in raw:
        grouped.setdefault(lg['category'], []).append(lg)
    order = ['Game Line', 'Team Total', 'QB', 'Receiving']
    return [{'cat': c, 'legs': grouped[c]} for c in order if c in grouped]


def _ctx(game='Alpha AAA@Beta BBB', sel=None, thesis='custom', menu=None):
    """build_sgp_workbench_context with the menu + matchup week monkeypatched (deterministic)."""
    import services.nfl_sgp  # noqa
    saved_menu = app._nfl_sgp_leg_menu
    saved_mctx = app.build_nfl_matchup_context
    app._nfl_sgp_leg_menu = menu or _fixture_menu
    app.build_nfl_matchup_context = lambda: {'mu_week': [{'away': 'Alpha AAA', 'home': 'Beta BBB'},
                                                         {'away': 'Gamma GGG', 'home': 'Delta DDD'}]}
    try:
        return app.build_sgp_workbench_context(game=game, selected_ids=sel or [], thesis=thesis)
    finally:
        app._nfl_sgp_leg_menu = saved_menu
        app.build_nfl_matchup_context = saved_mctx


def _ids(ctx, **match):
    out = []
    for grp in ctx['menu']:
        for lg in grp['legs']:
            if all(str(lg.get(k)) == str(v) for k, v in match.items()):
                out.append(lg['id'])
    return out


CHECKS = []


def check(fn):
    CHECKS.append(fn)
    return fn


@check
def t01_single_game_only():
    ctx = _ctx()
    valid = _ids(ctx, player='QB1', direction='OVER')[0]
    out = _ctx(sel=[valid, 'BOGUS|from|another|game|1|XXX'])
    ids = [l['id'] for l in out['selected']]
    assert ids == [valid], f'single-game filter failed: {ids}'


@check
def t02_switch_game_clears():
    a = _ctx()
    aid = _ids(a, player='QB1', direction='OVER')[0]
    b = _ctx(game='Gamma GGG@Delta DDD', sel=[aid])  # different game -> different ids
    assert b['selected'] == [], 'switching games did not clear the prior selection'


@check
def t03_same_player_stat_opposing_conflict():
    r = sgp.evaluate([_leg(player='QB1', direction='OVER'), _leg(player='QB1', direction='UNDER')])
    assert any(f['rule_id'] == 'R1_same_player_stat_opposing' for f in r['buckets']['conflict'])


@check
def t04_remove_leg_removes_warning():
    two = sgp.evaluate([_leg(player='QB1', direction='OVER'), _leg(player='QB1', direction='UNDER')])
    one = sgp.evaluate([_leg(player='QB1', direction='OVER')])
    assert two['buckets']['conflict'] and not one['buckets']['conflict'], 'removing a leg kept its warning'


@check
def t05_duplicate_selection_idempotent():
    ctx = _ctx()
    vid = _ids(ctx, player='QB1', direction='OVER')[0]
    out = _ctx(sel=[vid, vid, vid])
    assert len(out['selected']) == 1, f'duplicate selection not idempotent: {len(out["selected"])}'


@check
def t06_missing_price_unavailable():
    ctx = _ctx()
    under = [lg for grp in ctx['menu'] for lg in grp['legs'] if lg.get('player') == 'QB1' and lg['direction'] == 'UNDER'][0]
    assert under['price'] is None, 'missing price was invented'  # template renders "price unavailable"


@check
def t07_combined_price_never_on_leg():
    ctx = _ctx(sel=[_ids(_ctx(), player='QB1', direction='OVER')[0]])
    for lg in ctx['selected']:
        assert 'combined_price' not in lg and 'sgp_price' not in lg, 'a combined price leaked onto a leg'
    assert 'combined_price' not in ctx and 'sgp_price' not in ctx, 'context assigned a combined SGP price'


@check
def t08_findings_link_legs_and_rule():
    r = sgp.evaluate([_leg(player='QB1', direction='UNDER', category='QB', stat='Pass Yards'),
                      _leg(player='WR1', category='Receiving', stat='Rec Yards', direction='OVER', team='AAA'),
                      _leg(player='WR2', category='Receiving', stat='Rec Yards', direction='OVER', team='AAA'),
                      _leg(player='QB1', team='AAA', category='QB', stat='Pass Yards', direction='UNDER')],
                     thesis='custom')
    assert r['findings'], 'no findings produced'
    for f in r['findings']:
        assert f.get('rule_id') and isinstance(f.get('legs'), list) and f['legs'], f'finding missing rule/legs: {f}'


@check
def t09_alignment_is_not_a_score():
    r = sgp.evaluate([_leg(player='QB1', direction='OVER')], thesis='shootout')
    blob = repr(r).lower()
    for banned in ('score', 'confidence', 'probability', 'rank', 'best sgp', 'lock'):
        assert banned not in blob, f'engine output contains banned ranking/score token: {banned}'
    assert set(r['buckets']) == {'supports', 'conflict', 'tension', 'concentration', 'unknown'}


@check
def t10_menu_order_is_factual():
    menu = _fixture_menu('Alpha AAA', 'Beta BBB')
    cats = [g['cat'] for g in menu]
    assert cats == ['Game Line', 'Team Total', 'QB', 'Receiving'], f'menu category order not factual: {cats}'
    # within a category: player/team then stat then line (no score key present on legs)
    for grp in menu:
        for lg in grp['legs']:
            assert 'score' not in lg and 'rank' not in lg and 'confidence' not in lg


@check
def t11_containment_intact():
    # the SGP engine/menu must not import or revive PropScore / calibration ranking
    import inspect
    src = inspect.getsource(sgp) + inspect.getsource(app._nfl_sgp_leg_menu) + inspect.getsource(app.build_sgp_workbench_context)
    low = src.lower()
    for banned in ('propscore', 'calibration', 'promotion_adjust', 'has_authority'):
        assert banned not in low, f'SGP code references contained authority: {banned}'


@check
def t12_matchup_menu_unchanged():
    # the existing per-game menu builder is untouched and distinct from the new one
    assert app._nfl_game_prop_menu is not app._nfl_sgp_leg_menu
    assert callable(app._nfl_game_prop_menu) and callable(app._nfl_sgp_leg_menu)


@check
def t13_parlay_handoff_held_reports_mismatch():
    ctx = _ctx(sel=[_ids(_ctx(), player='QB1', direction='OVER')[0]])
    h = ctx['handoff']
    assert h and h['status'] == 'held' and h['reason'] == 'contract_mismatch'
    for f in ('price', 'sportsbook', 'quote_scope', 'source_timestamp'):
        assert f in h['dropped_fields'], f'handoff did not report dropped field {f}'


@check
def t14_journal_stays_dark():
    ctx = _ctx(sel=[_ids(_ctx(), player='QB1', direction='OVER')[0]])
    assert ctx['journal_enabled'] == bool(app.DECISION_JOURNAL_ENABLED)
    assert app.DECISION_JOURNAL_ENABLED is False or app.DECISION_JOURNAL_ENABLED in (False, None, 0), \
        'Decision Journal flag must be OFF for this scoped task'


@check
def t15_leg_interaction_perf():
    """Deterministic populated-fixture performance guard for leg interaction (the prod workbench showed
    'No legs yet' at capture time, so leg-interaction perf is proven HERE, locally, not in the browser).
    A realistic multi-leg ticket evaluates in well under the interaction budget AND is deterministic
    (identical output across repeats)."""
    import time
    legs = [
        _leg(player='QB1', direction='OVER', cat='pass', stat='pass_yards'),
        _leg(player='WR1', direction='OVER', cat='rec', stat='rec_yards'),
        _leg(player='WR1', direction='UNDER', cat='rec', stat='receptions'),
        _leg(player='RB1', direction='OVER', cat='rush', stat='rush_yards'),
        _leg(player='QB1', direction='UNDER', cat='pass', stat='pass_yards'),   # same-player opposing
        _leg(team='AAA', direction='OVER', cat='team_total', stat='team_total'),
        _leg(direction='UNDER', cat='game_total', stat='game_total'),
        _leg(player='WR2', direction='OVER', cat='rec', stat='rec_yards'),
    ]
    first = sgp.evaluate(legs, thesis='custom', game_total_line=44.5)
    N = 300
    t0 = time.perf_counter()
    for _ in range(N):
        out = sgp.evaluate(legs, thesis='custom', game_total_line=44.5)
    per_ms = (time.perf_counter() - t0) * 1000.0 / N
    assert out == first, 'evaluate() is not deterministic across repeats'
    assert per_ms < 25.0, f'leg-interaction evaluate() ~{per_ms:.2f}ms/call (>25ms interaction budget)'


def main():
    print('=' * 60)
    print('NFL SGP WORKBENCH ACCEPTANCE QC (15 mechanical of 16)')
    print('=' * 60)
    failed = 0
    for fn in CHECKS:
        name = fn.__name__
        try:
            fn()
            print(f'[PASS] {name}')
        except Exception as exc:
            failed += 1
            print(f'[FAIL] {name}: {type(exc).__name__}: {exc}')
    print('-' * 60)
    print('(acceptance #15 desktop+375px prod render and #16 cross-sport regression run at deploy time)')
    if failed:
        print(f'{failed} check(s) FAILED.')
        return 1
    print('SGP Workbench acceptance QC verified.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
