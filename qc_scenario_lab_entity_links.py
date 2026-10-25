"""QC: Batch-1 fan-out Group 3 — NFL Scenario Lab (scenario_lab).

Wraps ONLY the NFL player column of the players boards (column 0, whose header varies QB/RB/WR), reusing
_wrap_entity_board (by col_index) and the shared _entity_cell.html renderer. Team-rankings and
team-profile boards are left plain (player-only wrap). Checks: resolvable (fixture + /tools/player-check
URL shape), unknown/ambiguous -> plain, hostile label, no source mutation, player-only scoping on REAL
data, destination behavior, and the client wiring. Sorting / nested-anchor / 375px are verified in-browser
(stated in the run report).
"""
import os
import sys

os.environ.setdefault("SECRET_KEY", "qc-only-not-a-real-secret")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import app  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
TPL = os.path.join(HERE, 'templates')
fails = []
notes = []


def check(cond, msg):
    print(("  [ok] " if cond else "  [FAIL] ") + msg)
    if not cond:
        fails.append(msg)


KNOWN = 'Patrick Mahomes'
UNKNOWN = 'Nobody Q. Unknownson'
HOSTILE = 'A<b>x</b> O\'Brien & "Q"'


def test_server_contract():
    print("\n[A] _entity_cell (NFL player) + _wrap_entity_board(col_index) — by index, not label")
    _orig = app._entity_player_known
    app._entity_player_known = lambda s, n: (s == 'nfl' and n in (KNOWN, HOSTILE)) or _orig(s, n)
    try:
        c = app._entity_cell('player', 'nfl', KNOWN)
        check(c['text'] == KNOWN and isinstance(c['url'], str) and c['url'].startswith('/tools/player-check'),
              "resolvable NFL player (fixture) -> /tools/player-check (%r)" % c['url'])
        h = app._entity_cell('player', 'nfl', HOSTILE)
        check(h['text'] == HOSTILE, "hostile label text preserved verbatim")
        check(isinstance(h['url'], str) and '<' not in h['url'] and '"' not in h['url'] and ' ' not in h['url'],
              "hostile label percent-encoded in the url (%r)" % h['url'])
    finally:
        app._entity_player_known = _orig
    check(app._entity_cell('player', 'nfl', UNKNOWN)['url'] is None, "unknown/ambiguous NFL player -> None")

    # col_index wraps column 0 even when its header is 'QB'/'RB'/'WR' (not 'Player'); no mutation
    board = {'columns': [{'label': 'QB', 'fmt': 'text'}, {'label': 'Plays', 'fmt': 'int'}],
             'rows': [['B.Purdy', 23], ['P.Mahomes', 30]]}
    snap = [list(r) for r in board['rows']]
    out = app._wrap_entity_board(board, 'player', 'nfl', col_index=0)
    check(out['entity_col'] == 0 and out['entity_kind'] == 'player' and out['entity_sport'] == 'nfl',
          "wraps by col_index 0 regardless of the 'QB' header")
    check(isinstance(out['rows'][0][0], dict) and out['rows'][0][0]['text'] == 'B.Purdy',
          "player cell wrapped as {text,url}")
    check(out['rows'][0][1] == 23, "non-player column untouched")
    check(board['rows'] == snap and not isinstance(board['rows'][0][0], dict), "input NOT mutated")
    # an out-of-range index is a safe no-op (reversible)
    out2 = app._wrap_entity_board(board, 'player', 'nfl', col_index=9)
    check('entity_col' not in out2, "out-of-range col_index -> board returned unchanged")


def test_player_only_scoping_real_data():
    print("\n[A2] REAL data (build_scenario_lab_context): player boards wrapped, team boards plain, cache intact")
    ctx = app.build_scenario_lab_context()
    scopes = ctx['scenario_data'].get('scopes') or {}
    if not scopes:
        notes.append("scenario_lab data absent locally — player-only scoping test skipped.")
        print("  [skip] no scenario_lab scopes locally")
        return
    sk = next(iter(scopes))
    sc = scopes[sk]
    pos = next(iter(sc['players']))
    pboards = sc['players'][pos]['boards']
    bk = next(iter(pboards))
    check(pboards[bk].get('entity_col') == 0, "players board marked entity_col 0")
    cell0 = pboards[bk]['rows'][0][0]
    check(isinstance(cell0, dict) and 'text' in cell0 and 'url' in cell0,
          "players board col 0 wrapped as {text,url} (%r)" % cell0)
    tboards = sc.get('teamRankings', {}).get('boards') or {}
    if tboards:
        tk = next(iter(tboards))
        check(tboards[tk].get('entity_col') is None,
              "team-rankings board NOT wrapped (player-only scope)")
    raw = app._SCENARIO_LAB_CACHE['data']['scopes'][sk]['players'][pos]['boards'][bk]['rows'][0][0]
    check(isinstance(raw, str), "cached raw board row NOT mutated (still a plain string)")
    if cell0.get('url') is None:
        notes.append("LOCAL LIMITATION: the NFL identity keyset is empty in this worktree, so scenario_lab "
                     "players fail-closed to plain text locally. Production destination resolution and HTTP "
                     "200 remain PENDING DEPLOYMENT VERIFICATION — not predicted.")


def test_destination_behavior():
    print("\n[A3] destination behavior — resolved NFL player page (or pending production)")
    url = app.player_url('nfl', KNOWN)
    if not url:
        print("  [skip] NFL keyset empty locally — destination-fetch not exercised")
        notes.append("destination-fetch skipped: no NFL player resolves locally; the /tools/player-check "
                     "URL shape is proven via fixture above. Live 200 is PENDING DEPLOYMENT VERIFICATION.")
        return
    resp = app.app.test_client().get(url)
    check(resp.status_code == 200, "GET %s -> 200" % url)
    check(KNOWN.split()[-1] in resp.get_data(as_text=True), "resolved page renders the player entity")


def test_client_wired():
    print("\n[B] scenario_lab.html reuses _entity_cell.html + routes entity_col to DOM fill (shared renderTable)")
    src = open(os.path.join(TPL, 'scenario_lab.html'), encoding='utf-8').read()
    ok = ("{% include '_entity_cell.html' %}" in src
          and 'const EC = window.bkEntityCell;' in src
          and 'if(i===board.entity_col) h+=' in src and 'data-ent></td>' in src
          and 'EC.fill(td, r[board.entity_col])' in src
          and 'if(sc===board.entity_col){x=EC.text(x);y=EC.text(y);}' in src)
    check(ok, "scenario_lab.html wired (include + placeholder + EC.fill + EC.text sort)")
    check('player_url' not in src and 'team_url' not in src, "scenario_lab.html does NO client resolution")
    check('entity_links' not in src, "no resolver import in client JS")


if __name__ == '__main__':
    print("=" * 72)
    print("SCENARIO LAB ENTITY-LINK FAN-OUT (GROUP 3) QC — NFL player column, shared DOM render")
    print("=" * 72)
    test_server_contract()
    test_player_only_scoping_real_data()
    test_destination_behavior()
    test_client_wired()
    if notes:
        print("\nNotes:")
        for n in notes:
            print("  - " + n)
    print("\nClean:", not fails)
    sys.exit(1 if fails else 0)
