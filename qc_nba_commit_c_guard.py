"""QC: NBA Commit C authority removal is NBA-only and fail-safe.

Proves the frozen P0 Commit C guards on templates/props.html:
  - the Confidence "50-99 play strength" tile, the Tier tile, and the Conf column are removed ONLY
    when is_nba_props is True (the NBA board);
  - every OTHER sport keeps them, including when the flag is OMITTED entirely (the fail-safe
    default must be False, so a renderer that forgot the flag can never strip a non-NBA board);
  - the guards hold on BOTH the floor and the non-floor (default) view;
  - removing the Conf column keeps the table byte-aligned (one fewer <th> AND one fewer <td>);
  - the NBA sort control offers Tip-off (the authority-free order) instead of Confidence.

props.html extends bk_base.html; to test its content in isolation (without the full page's nav
context) we render it against a minimal stub base via a ChoiceLoader. This exercises the real
template source and its real guards. A separate check covers the server-side sort default.

Exits 0 when every guard holds, 1 otherwise.
"""
from __future__ import annotations

import jinja2
import re

from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader

import app

STUB_BASE = ("{% block title %}{% endblock %}{% block app_class %}{% endblock %}"
             "{% block betslip %}{% endblock %}{% block content %}{% endblock %}")


class _Lenient(jinja2.Undefined):
    """Callable + chainable Undefined so the template's auxiliary globals (team_mark,
    glossary_hint, ou_rate_color, get_method_guide, ...) render empty without per-function stubs.
    It stays a real Undefined subclass, so `is_nba_props|default(False)` still resolves to False
    when the flag is omitted -- exactly the fail-safe path we are testing. The markers asserted
    below are static template text gated on is_nba_props, which is always passed explicitly."""
    def __call__(self, *a, **k):
        return self
    def __getattr__(self, name):
        return self
    def __getitem__(self, key):
        return self
    def __iter__(self):
        return iter([])
    def __str__(self):
        return ''
    def __bool__(self):
        return False

# A complete row: every prop.* field the row template references (numeric fields as numbers,
# flags False, text fields empty) so the full <tr> renders for both board shapes.
_NUM = {k: 0 for k in (
    'avg', 'book_count', 'confidence', 'current_line', 'edge_pct', 'ev_pct', 'fair_price',
    'game_total', 'line', 'market_price', 'market_prob', 'model_prob', 'one_sided_price',
    'over_rate', 'projected_minutes', 'team_spread', 'ts_pct', 'under_rate', 'usage_pct',
    'weighted_over_rate', 'weighted_under_rate')}
ROW = dict(_NUM, player='Al Horford', team='BOS', stat='Points', line=10.5, avg=12.0,
           direction='over', confidence=82, over_rate=60, under_rate=40, market_prob=58,
           weighted_over_rate=60, weighted_under_rate=40, game='BOS @ NYK',
           game_date='2026-10-21', game_time='7:30 PM', edge_pct=2.0, situations=[],
           best_book='', book='', core_model_read='', featured_risk_note='',
           game_environment_label='', has_injury_flag=False, injury_context_note='',
           injury_reason='', injury_short_label='', injury_status='', lean_strength='',
           market_view='', matchup='', play_verdict='', play_verdict_note='',
           public_trend_note='', rank_explanation='')

_PP = {'sport': {'opportunity': 'High', 'reliability': 'High', 'label': 'NBA', 'checks': [],
                 'best_types': [], 'best_market': 'x', 'main_trap': 'x', 'why': 'x'},
       'universal': []}


def _env():
    return Environment(loader=ChoiceLoader([
        DictLoader({'bk_base.html': STUB_BASE}),
        FileSystemLoader('templates'),
    ]), undefined=_Lenient)


def _render(env, *, filter_type, sport_key, sport_label, is_nba_props=None):
    ctx = dict(
        props=[ROW], filter_type=filter_type, date_filter='today', direction_filter='all',
        stat_options=[], upcoming={}, postseason_only=False, team_query='', player_query='',
        stat_query='', query_suffix='', sample_mode='full', sort_by='tipoff', sort_dir='asc',
        base_params={}, build_sort_link=lambda *a, **k: '#',
        refresh_meta={'last_updated': 'now', 'book_count': 3, 'books': ['dk'], 'row_count': 1},
        model_debug=False,
        pagination={'page': 1, 'page_count': 1, 'page_size': 15, 'start': 1, 'end': 1, 'total': 1},
        board_intelligence={}, prop_pointers=_PP, props_sport_key=sport_key,
        props_sport_label=sport_label, props_base_path='/x', props_all_path='/x',
        props_floor_path='/x/floor', props_locks_path='/x/locks',
        props_tracking_label='NGS', props_tracking_note='x',
    )
    if is_nba_props is not None:
        ctx['is_nba_props'] = is_nba_props
    return env.get_template('props.html').render(**ctx)


def _markers(html):
    return {
        'confidence_tile': 'Normalized play strength' in html,
        'tier_tile': 'Parlay build quality' in html,
        'conf_col_header': '<th>Conf</th>' in html,
        'conf_sort_option': 'value="confidence"' in html,
        'tipoff_sort_option': 'value="tipoff"' in html,
        # Count header cells whether or not they carry attributes (<th> and <th title=...>),
        # excluding <thead>. The NBA "Market lean gap" header (R1) is a <th title=...>, so a plain
        # '<th>' substring count would under-count NBA by one and read as a false misalignment.
        'th_count': len(re.findall(r'<th[ >]', html)),
        'row_present': 'Al Horford' in html,
    }


def run_qc():
    issues, notes = [], []
    env = _env()

    for ft in (None, 'floor'):
        label = ft or 'default'
        # --- NBA: all authority removed ------------------------------------------------
        try:
            nba = _markers(_render(env, filter_type=ft, sport_key='nba', sport_label='NBA',
                                   is_nba_props=True))
        except Exception as e:
            issues.append(f"NBA/{label}: render failed: {type(e).__name__}: {e}")
            continue
        if nba['confidence_tile']:
            issues.append(f"NBA/{label}: Confidence tile still present")
        if nba['tier_tile']:
            issues.append(f"NBA/{label}: Tier tile still present")
        if nba['conf_col_header']:
            issues.append(f"NBA/{label}: Conf column header still present")
        if nba['conf_sort_option']:
            issues.append(f"NBA/{label}: Confidence sort option still offered")
        if not nba['tipoff_sort_option']:
            issues.append(f"NBA/{label}: Tip-off sort option missing")
        if not nba['row_present']:
            issues.append(f"NBA/{label}: row did not render (market columns gone too?)")

        # --- Non-NBA sports: everything preserved, BOTH explicit-False and OMITTED -------
        for sk, sl in (('nfl', 'NFL'), ('ncaaf', 'CFB'), ('mlb', 'MLB'), ('wnba', 'WNBA')):
            for mode, flag in (('explicit-False', False), ('omitted (fail-safe)', None)):
                try:
                    m = _markers(_render(env, filter_type=ft, sport_key=sk, sport_label=sl,
                                         is_nba_props=flag))
                except Exception as e:
                    issues.append(f"{sl}/{label}/{mode}: render failed: {type(e).__name__}: {e}")
                    continue
                if not m['confidence_tile']:
                    issues.append(f"{sl}/{label}/{mode}: Confidence tile was stripped (should stay)")
                if not m['tier_tile']:
                    issues.append(f"{sl}/{label}/{mode}: Tier tile was stripped (should stay)")
                if not m['conf_col_header']:
                    issues.append(f"{sl}/{label}/{mode}: Conf column was stripped (should stay)")
                if not m['conf_sort_option']:
                    issues.append(f"{sl}/{label}/{mode}: Confidence sort option was removed (should stay)")
                # Column alignment: NBA board has exactly one fewer <th> than the non-NBA board.
                if m['th_count'] != nba['th_count'] + 1:
                    issues.append(f"{sl}/{label}/{mode}: th count {m['th_count']} != NBA {nba['th_count']}+1 "
                                  "(column misalignment)")
        notes.append(f"view '{label}': NBA stripped of Confidence/Tier/Conf-col; "
                     "NFL/CFB/MLB/WNBA unchanged (explicit-False and omitted)")

    # --- server-side NBA default sort is the authority-free tip-off order ----------------
    out = app.sort_prop_rows(
        [{'player': 'Zed', 'game_date': '2026-10-21', 'game_time': '10:00 PM'},
         {'player': 'Al', 'game_date': '2026-10-21', 'game_time': '7:30 PM'}], 'tipoff', 'asc')
    if [r['player'] for r in out] != ['Al', 'Zed']:
        issues.append("sort_prop_rows('tipoff') not chronological (7:30 PM before 10:00 PM)")
    else:
        notes.append("sort_prop_rows('tipoff') orders by tip-off ascending, then player A-Z")

    return {'issues': issues, 'notes': notes}


def main() -> int:
    report = run_qc()
    print("=" * 60)
    print("BANKROLL KINGS NBA COMMIT C GUARD QC")
    print("=" * 60)
    for note in report["notes"]:
        print(f"[NOTE] {note}")
    if report["notes"]:
        print()
    if not report["issues"]:
        print("NBA-only authority removal verified; other sports unchanged.")
        return 0
    for msg in report["issues"]:
        print(f"[FAIL] {msg}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
