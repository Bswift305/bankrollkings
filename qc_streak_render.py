"""QC: the streak-explainer surfaces RENDER builder-emitted evidence verbatim.

Presentation-completion slice. Two guarantees, checked against the REAL template source (not a
reproduction): (1) the shared explainer partial `_streak_explainer.html` prints the
`services.streak_explainer.normalize(...)` view-model fields directly, synthesizing nothing; (2) the
Hot Hand F3 absence disclosure fragment lifted out of `templates/nfl_heatmap.html` prints the
builder's FULL counts and labels its item list as an explicit capped SAMPLE, never as the universe.

Pure render test — no `app` import, no network, no data files. Jinja renders the on-disk templates.
"""
import os
import re
import sys

from jinja2 import Environment, FileSystemLoader, select_autoescape

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from services.streak_explainer import normalize  # noqa: E402

TEMPLATES = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates')

fails = []


def check(cond, msg):
    print(("  [ok] " if cond else "  [FAIL] ") + msg)
    if not cond:
        fails.append(msg)


def _env():
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(['html']))
    # The explainer only calls entity_anchor for counted_events that carry a real opponent; register a
    # transparent stub so an accidental call is visible rather than crashing the render.
    env.globals['entity_anchor'] = lambda kind, sport, name, label=None: (label or name)
    return env


def test_explainer_partial_prints_viewmodel():
    print("\n[1] shared explainer partial renders the normalize() view-model verbatim")
    env = _env()
    tpl = env.get_template('_streak_explainer.html')

    # ATS cover run with per-game result tokens (builder evidence).
    row = {'team': 'KC', 'cover_streak': 4, 'last': 'W W W W'}
    ex = normalize('ats', row, {'kind': 'cover', 'source': 'current-season graded games',
                                'season': 2026, 'data_through': 'through Wk 7', 'freshness': 'current-season'})
    html = tpl.render(ex=ex)

    check(ex['membership_reason'] == '4 straight covers',
          "normalize() produced the membership reason from the run (got %r)" % ex['membership_reason'])
    check(ex['membership_reason'] in html, "partial prints the exact membership_reason string")
    check('the spread' in html, "threshold 'the spread' from the view-model is shown")
    check('2026' in html, "current season from meta is shown")
    check(html.count('>cover<') == 4, "all 4 per-result tokens render as 'cover' (one chip per builder token)")
    check('<div class="sx-seq">' in html and '<th>Value</th>' not in html,
          "a results-only source renders a compact sequence, NOT a table of empty cells")
    # No fabricated per-game value/line: those columns are simply not shown (never invented).
    check('74' not in html and 'Value' not in html,
          "no per-game value/line is synthesized for a results-only source")

    # Source carries only the run, not per-game results -> whole table is unavailable, no invented digits.
    ex2 = normalize('ats', {'cover_streak': 3}, {'kind': 'fade'})
    html2 = tpl.render(ex=ex2)
    check('Per-game detail is <b>unavailable</b>' in html2,
          "with no per-game evidence the partial shows the unavailable note, not a fabricated table")
    check('3 straight non-covers' in html2, "fade run reason flows through from the view-model")

    # hot_hand with a builder status_label is shown verbatim (not re-derived in the template).
    exh = normalize('hot_hand', {'line': 74.5, 'streak': 5, 'status_label': 'Graded through 2026 Week 7'},
                    {'source': 'nflverse weekly', 'freshness': 'current-season'})
    htmlh = tpl.render(ex=exh)
    check('Graded through 2026 Week 7' in htmlh, "hot_hand status_label from the builder is printed verbatim")

    # milestone carries per-game context -> the RICH table path renders (opponent + value), not the strip.
    exm = normalize('milestone', {'threshold': 100, 'run': 3, 'stat_label': 'rec yds',
                                   'games': [{'week': 5, 'opponent': 'JAX', 'value': 112, 'season': 2026},
                                             {'week': 6, 'opponent': 'DEN', 'value': 141, 'season': 2026},
                                             {'week': 7, 'opponent': 'LV', 'value': 103, 'season': 2026}]},
                    {'source': 'NFL game logs'})
    htmlm = tpl.render(ex=exm)
    check('<th>Value</th>' in htmlm and '<div class="sx-seq">' not in htmlm,
          "milestone (per-game context present) renders the full table, not the compact strip")
    check('JAX' in htmlm and '112' in htmlm, "milestone per-game opponent + value render from builder games[]")


# --- lift the ACTUAL absences fragment out of nfl_heatmap.html -----------------------------------

def _extract_absences_fragment():
    src = open(os.path.join(TEMPLATES, 'nfl_heatmap.html'), encoding='utf-8').read()
    start = src.index('{% if absences and absences.count %}')
    # Walk {% if %}/{% endif %} depth to find the matching endif for the outermost block.
    i, depth = start, 0
    tag = re.compile(r'{%-?\s*(if|endif)\b')
    end = None
    for mo in tag.finditer(src, start):
        if mo.group(1) == 'if':
            depth += 1
        else:
            depth -= 1
            if depth == 0:
                end = mo.end()
                # consume trailing '%}'
                end = src.index('%}', end - 2) + 2 if '%}' not in mo.group(0) else mo.end()
                end = src.index('%}', mo.start()) + 2
                break
    assert end is not None, "could not find matching endif for the absences block"
    return src[start:end]


def test_absences_fragment_prints_builder_counts():
    print("\n[2] Hot Hand F3 absences fragment prints builder FULL counts + labels the sample")
    frag = _extract_absences_fragment()
    env = _env()
    tpl = env.from_string(frag)

    # Builder-shaped payload: 7 total absences across 3 reasons, item list capped at 3 (a SAMPLE).
    absences = {
        'count': 7,
        'by_reason': {'defense_no_player_appearance': 1, 'no_player_log': 2, 'no_matching_stat_columns': 4},
        'items': [
            {'player': 'Chiefs D/ST', 'stat': 'Sacks', 'reason': 'defense_no_player_appearance'},
            {'player': 'J. Fringe', 'stat': 'Rec Yds', 'reason': 'no_player_log'},
            {'player': 'K. Edge', 'stat': 'Rush Yds', 'reason': 'no_matching_stat_columns'},
        ],
    }
    html = tpl.render(absences=absences)

    check('7 board props' in html, "headline prints the FULL builder count (7), not the sample size")
    check('1 team defense' in html, "defense_no_player_appearance count (1) shown with honest category")
    check('2 with no appearance log' in html, "no_player_log count (2) shown with honest category")
    check('4 with no matching stat column' in html, "no_matching_stat_columns count (4) shown")
    check('Sample (3 of 7)' in html,
          "item list is labeled an explicit capped SAMPLE (3 of 7) — not presented as the universe")
    check('3' != '7' and 'of 7' in html, "the sample denominator is the full count, exposing the cap")
    for it in absences['items']:
        check(it['player'] in html and it['reason'] in html,
              "sample item '%s' rendered with its governed reason" % it['player'])

    # Counts must track the dict, not the item length: change count, keep items -> headline follows count.
    absences2 = dict(absences, count=41)
    html2 = tpl.render(absences=absences2)
    check('41 board props' in html2 and 'Sample (3 of 41)' in html2,
          "headline + sample denominator both follow the builder count (41), proving no count is hardcoded")

    # Singular grammar + zero-sample: count==1 with no items list -> no empty <details>.
    html3 = tpl.render(absences={'count': 1, 'by_reason': {'no_player_log': 1}, 'items': []})
    check('1 board prop ' in html3 and 'board props' not in html3, "singular grammar when count == 1")
    check('<details' not in html3, "no sample disclosure rendered when the item list is empty")

    # The empty-board disclosure (count 0) renders nothing (the {% if absences.count %} guard).
    html4 = tpl.render(absences={'count': 0, 'by_reason': {}, 'items': []})
    check(html4.strip() == '', "zero absences -> the block renders nothing (guarded)")


def test_macro_scoped_call_resolves():
    # templates/cfb_ats_streaks.html calls streak_explainer() from INSIDE a {% macro board() %} and then
    # {% include %}s the partial. Jinja context-processor vars do NOT reach macros — only jinja_env.globals
    # do — which is why app.py registers it as a global. Prove the macro->include path resolves + renders.
    print("\n[3] macro-scoped streak_explainer() + include renders (CFB board() pattern)")
    env = _env()
    env.globals['streak_explainer'] = normalize
    tpl = env.from_string(
        "{% macro board(r, kind) %}"
        "{% set ex = streak_explainer('ats', r, {'kind': kind, 'source': 'graded ATS results (CFBD)',"
        " 'freshness': 'current-season'}) %}{% include '_streak_explainer.html' %}{% endmacro %}"
        "{{ board({'team': 'Georgia', 'streak': 5, 'last': 'W W W W W'}, 'cover') }}")
    html = tpl.render()
    check('5 straight covers' in html, "macro-scoped streak_explainer() resolves (global reaches the macro)")
    check(html.count('>cover<') == 5, "sequence chips render from the macro->include path")
    check('the spread' in html, "threshold renders through the macro path")


if __name__ == '__main__':
    print("=" * 72)
    print("STREAK-EXPLAINER + HOT HAND ABSENCE RENDER QC (builder evidence, verbatim)")
    print("=" * 72)
    test_explainer_partial_prints_viewmodel()
    test_absences_fragment_prints_builder_counts()
    test_macro_scoped_call_resolves()
    print("\nClean:", not fails)
    sys.exit(1 if fails else 0)
