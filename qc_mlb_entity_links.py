"""QC: Batch-1 fan-out Group 2 — MLB player tables (mlb_luck, mlb_situational).

Wraps ONLY the Player column with a server-resolved {text,url} cell (sport-scoped MLB), reusing the
shared DOM renderer templates/_entity_cell.html. Checks: resolvable, unresolved/ambiguous -> plain,
hostile label, no source mutation, the board-wrap contract, destination-fetch (boot the test client and
GET the resolved /player?sport=mlb URL -> 200 + the player renders), and the per-template client wiring.
Sorting / nested-anchor / 375px are verified in-browser (stated in the run report).
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


REAL_PLAYER = 'Mike Trout'           # known MLB player (per qc_entity_links)
UNKNOWN_PLAYER = 'Old Timer Nobody'  # not in the keyset -> None -> plain text
HOSTILE = 'A<b>x</b> O\'Brien & "Q"'


def _board(rows):
    return {'columns': [{'label': 'Player', 'fmt': 'text'}, {'label': 'PA', 'fmt': 'int'},
                        {'label': 'wOBA', 'fmt': 'f3'}],
            'rows': rows, 'meta': {'k': 1}}


def test_server_contract():
    print("\n[A] _entity_cell / _wrap_entity_board — Player column, sport-scoped MLB")
    real_url = app.player_url('mlb', REAL_PLAYER)
    resolvable = real_url is not None
    if resolvable:
        c = app._entity_cell('player', 'mlb', REAL_PLAYER)
        check(c['text'] == REAL_PLAYER and c['url'] == real_url and '/player/' in c['url'] and 'sport=mlb' in c['url'],
              "resolvable MLB player -> {text, /player/...?sport=mlb} (%r)" % c['url'])
    else:
        notes.append("LOCAL LIMITATION: the MLB identity keyset is empty here; resolvable-player cases "
                     "are proven via a fixture (monkeypatched resolver), not local data.")
        _orig = app._entity_player_known
        app._entity_player_known = lambda s, n: (s == 'mlb' and n == REAL_PLAYER) or _orig(s, n)
        try:
            c = app._entity_cell('player', 'mlb', REAL_PLAYER)
        finally:
            app._entity_player_known = _orig
        check(c['url'] and '/player/' in c['url'] and 'sport=mlb' in c['url'],
              "resolvable MLB player (fixture) -> /player/...?sport=mlb (%r)" % c['url'])

    check(app._entity_cell('player', 'mlb', UNKNOWN_PLAYER)['url'] is None,
          "unknown/ambiguous MLB player -> url None (plain text)")

    # hostile label: text kept raw, url (when resolvable) is fully encoded, no raw markup/space
    _orig = app._entity_player_known
    app._entity_player_known = lambda s, n: (s == 'mlb' and n == HOSTILE) or _orig(s, n)
    try:
        h = app._entity_cell('player', 'mlb', HOSTILE)
    finally:
        app._entity_player_known = _orig
    check(h['text'] == HOSTILE, "hostile label text preserved verbatim (client renders via textContent)")
    check(isinstance(h['url'], str) and '<' not in h['url'] and '"' not in h['url'] and ' ' not in h['url'],
          "hostile label percent-encoded in the url (%r)" % h['url'])

    # board wrap: Player col -> {text,url}; entity_col marked; input not mutated
    src = _board([[REAL_PLAYER, 300, 0.41], [UNKNOWN_PLAYER, 210, 0.30]])
    snap = [list(r) for r in src['rows']]
    out = app._wrap_entity_board(src, 'player', 'mlb', 'Player')
    check(out['entity_col'] == 0 and out['entity_kind'] == 'player' and out['entity_sport'] == 'mlb',
          "entity_col/kind/sport marked on the wrapped board")
    check(isinstance(out['rows'][0][0], dict) and out['rows'][0][0]['text'] == REAL_PLAYER,
          "Player cell wrapped as {text,url}")
    check(out['rows'][1][0]['url'] is None, "unknown player row -> url None (plain)")
    check(out['rows'][0][1] == 300 and out['rows'][0][2] == 0.41, "non-player columns untouched")
    check(src['rows'] == snap and not isinstance(src['rows'][0][0], dict), "input board NOT mutated (cache-safe)")


def test_destination_fetch():
    print("\n[A2] destination-fetch — the resolved MLB player URL renders the player")
    url = app.player_url('mlb', REAL_PLAYER)
    if not url:
        notes.append("LOCAL LIMITATION: no MLB player resolves locally -> live destination-fetch skipped; "
                     "URL shape proven above via fixture. Production destination resolution and HTTP 200 "
                     "remain PENDING DEPLOYMENT VERIFICATION because the local MLB identity keyset is empty.")
        print("  [skip] MLB keyset empty locally — destination-fetch not exercised (stated as a limitation)")
        return
    client = app.app.test_client()
    resp = client.get(url)
    check(resp.status_code == 200, "GET %s -> 200" % url)
    body = resp.get_data(as_text=True)
    check(REAL_PLAYER.split()[-1] in body or REAL_PLAYER in body,
          "the resolved page renders the player entity (%r)" % REAL_PLAYER)


def test_templates_wired():
    print("\n[B] mlb_luck + mlb_situational reuse _entity_cell.html + route Player col to DOM fill")
    for name in ('mlb_luck', 'mlb_situational'):
        src = open(os.path.join(TPL, name + '.html'), encoding='utf-8').read()
        ok = ("{% include '_entity_cell.html' %}" in src
              and 'const EC = window.bkEntityCell;' in src
              and 'if(i===board.entity_col) h+=' in src and 'data-ent></td>' in src
              and 'EC.fill(td, r[board.entity_col])' in src
              and 'if(S.sortCol===board.entity_col){x=EC.text(x);y=EC.text(y);}' in src)
        check(ok, "%s.html wired (include + placeholder + EC.fill + EC.text sort)" % name)
        check('player_url' not in src and 'team_url' not in src, "%s.html does NO client resolution" % name)
    # one shared renderer, not a duplicate
    part = open(os.path.join(TPL, '_entity_cell.html'), encoding='utf-8').read()
    check('new URL(value, window.location.origin)' in part and '.innerHTML' not in part,
          "shared _entity_cell.html is the single hardened DOM renderer (no duplicate)")


if __name__ == '__main__':
    print("=" * 72)
    print("MLB ENTITY-LINK FAN-OUT (GROUP 2) QC — player column {text,url} + shared DOM render")
    print("=" * 72)
    test_server_contract()
    test_destination_fetch()
    test_templates_wired()
    if notes:
        print("\nNotes:")
        for n in notes:
            print("  - " + n)
    print("\nClean:", not fails)
    sys.exit(1 if fails else 0)
