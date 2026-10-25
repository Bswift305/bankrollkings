"""QC: Batch-1 fan-out Group 1 — CFB team-only tables (the three LIVE surfaces: cfb_power,
cfb_regression, cfb_totals). cfb_situational is excluded: /tools/cfb-situational redirects to
cfb-ats?view=situational (served by the deferred cfb_ats.html), so its template/context are unused.

Contracts:
  (A) SERVER — `_wrap_entity_board` wraps a positional-array board's Team column as a resolver-produced
      {text,url} cell (sport-scoped CFB team), marks entity_col/kind/sport, never mutates the input, and
      returns a board WITHOUT a Team column unchanged (reversible). `_entity_cell` resolves CFB team ->
      /tools/cfb-team, and returns url None for a non-team kind / unresolvable name.
  (B) CLIENT — the shared partial templates/_entity_cell.html renders via DOM (safeUrl = URL()+origin
      guard, textContent/createElement), does NO resolution; and each of the four templates includes it,
      routes the entity column to a data-ent placeholder + EC.fill, and sorts the entity column by EC.text.

Offline: CFB team resolution uses a pure name normalizer (no data files).
"""
import os
import sys

os.environ.setdefault("SECRET_KEY", "qc-only-not-a-real-secret")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import app  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
TPL = os.path.join(HERE, 'templates')
fails = []


def check(cond, msg):
    print(("  [ok] " if cond else "  [FAIL] ") + msg)
    if not cond:
        fails.append(msg)


def _board(rows):
    return {'columns': [{'label': 'Team', 'fmt': 'text'}, {'label': 'Conf'}, {'label': 'SP+'}],
            'rows': rows, 'meta': {'x': 1}}


def test_entity_cell():
    print("\n[A1] _entity_cell — CFB team resolves, non-team / unresolvable -> None")
    c = app._entity_cell('team', 'cfb', 'Georgia')
    check(c == {'text': 'Georgia', 'url': '/tools/cfb-team?team=Georgia'}, "CFB team -> cfb-team (%r)" % c)
    check(app._entity_cell('team', 'cfb', 'Ohio State')['url'] == '/tools/cfb-team?team=Ohio+State',
          "CFB team with a space is percent-encoded")
    # unresolvable/ambiguous -> the resolver returns None -> plain text (deterministic via the predicate)
    _orig = app._entity_team_known
    app._entity_team_known = lambda sport, team: ('UNRESOLVABLE' not in str(team)) and _orig(sport, team)
    try:
        check(app._entity_cell('team', 'cfb', 'UNRESOLVABLE TEAM')['url'] is None,
              "resolver-rejected team -> url None (plain text)")
    finally:
        app._entity_team_known = _orig
    check(app._entity_cell('player', 'cfb', 'Anyone')['url'] is None, "CFB player kind -> None (no page)")
    check(app._entity_cell('coach', 'cfb', 'Kirby Smart')['url'] is None, "coach kind -> None")
    check(app._entity_cell('team', 'cfb', '')['text'] == '' and app._entity_cell('team', 'cfb', '')['url'] is None,
          "empty name -> blank text, no url")


def test_wrap_board():
    print("\n[A2] _wrap_entity_board — wraps the Team column, marks entity_col, no mutation, reversible")
    src = _board([['Georgia', 'SEC', 32.1], ['UNRESOLVABLE TEAM', 'X', 1.0]])
    src_snapshot = [list(r) for r in src['rows']]
    _orig = app._entity_team_known
    app._entity_team_known = lambda sport, team: ('UNRESOLVABLE' not in str(team)) and _orig(sport, team)
    try:
        out = app._wrap_entity_board(src, 'team', 'cfb')
    finally:
        app._entity_team_known = _orig
    check(out['entity_col'] == 0 and out['entity_kind'] == 'team' and out['entity_sport'] == 'cfb',
          "entity_col/kind/sport marked")
    check(out['rows'][0][0] == {'text': 'Georgia', 'url': '/tools/cfb-team?team=Georgia'},
          "row 0 Team cell wrapped with resolver url")
    check(out['rows'][1][0] == {'text': 'UNRESOLVABLE TEAM', 'url': None},
          "unresolvable Team -> {text, url:None} (plain text client-side)")
    check(out['rows'][0][1] == 'SEC' and out['rows'][0][2] == 32.1, "non-entity columns untouched")
    check(src['rows'] == src_snapshot and not isinstance(src['rows'][0][0], dict),
          "input board/rows NOT mutated (cache-safe)")
    # a board without a Team column is returned unchanged -> reversible / safe
    noteam = {'columns': [{'label': 'Coach'}, {'label': 'W'}], 'rows': [['x', 1]]}
    out2 = app._wrap_entity_board(noteam, 'team', 'cfb')
    check('entity_col' not in out2, "board without a Team column is returned unchanged (no entity_col)")


def test_client_partial():
    print("\n[B1] shared partial templates/_entity_cell.html — DOM render, URL()+origin guard, no resolution")
    src = open(os.path.join(TPL, '_entity_cell.html'), encoding='utf-8').read()
    for tok in ['window.bkEntityCell', 'function safeUrl(', 'new URL(value, window.location.origin)',
                'p.origin !== window.location.origin', "!value.startsWith('/') || value.startsWith('//')",
                "createElement('a')", 'a.href=url', 'a.textContent=String(label)', 'createTextNode',
                'function text(', 'function fill(']:
        check(tok in src, "partial has %r" % tok)
    check('.innerHTML' not in src, "partial never uses innerHTML (entity label/url are data)")
    check('player_url' not in src and 'team_url' not in src, "partial does NO identity resolution")


def test_templates_wired():
    # cfb_situational is NOT here: /tools/cfb-situational redirects to cfb-ats?view=situational, so the
    # situational view is served by cfb_ats.html (the DEFERRED handler-collision surface), and
    # cfb_situational.html / build_cfb_situational_context are unused. Group 1's live surfaces are these 3.
    print("\n[B2] each CFB template includes the partial + routes entity_col to DOM fill + sorts by text")
    for name, body_id in [('cfb_power', 'pw'), ('cfb_regression', 'cr'), ('cfb_totals', 'to')]:
        src = open(os.path.join(TPL, name + '.html'), encoding='utf-8').read()
        ok = ("{% include '_entity_cell.html' %}" in src
              and 'const EC = window.bkEntityCell;' in src
              and 'if(i===board.entity_col) h+=' in src and 'data-ent></td>' in src
              and 'EC.fill(td, r[board.entity_col])' in src
              and 'if(S.sortCol===board.entity_col){x=EC.text(x);y=EC.text(y);}' in src)
        check(ok, "%s.html wired (include + entity placeholder + EC.fill + EC.text sort)" % name)
        # the entity column no longer goes through the innerHTML fmt() path (it uses the placeholder)
        check("if(i===board.entity_col) h+='<td" in src,
              "%s.html entity column emits a placeholder, not an fmt() innerHTML cell" % name)


if __name__ == '__main__':
    print("=" * 72)
    print("CFB ENTITY-LINK FAN-OUT (GROUP 1) QC — server {text,url} board wrap + client DOM render")
    print("=" * 72)
    test_entity_cell()
    test_wrap_board()
    test_client_partial()
    test_templates_wired()
    print("\nClean:", not fails)
    sys.exit(1 if fails else 0)
