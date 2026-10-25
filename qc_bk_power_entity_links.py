"""QC: BK Power Batch-1 entity-link pilot.

Two contracts:
  (A) SERVER contract — `_bk_power_name_cell` / `_bk_power_attach_ent` emit resolver-produced
      {text,url,sub} cells, sport-scoped: NFL player + team link when the identity resolves; CFB
      player and coaches are ALWAYS plain (url None); ambiguous/gated/unknown identities are plain;
      a hostile label keeps its raw text while the url is fully percent-encoded; source rows are
      never mutated.
  (B) CLIENT contract (static scan of templates/bk_power.html) — the name cell is a `data-ent`
      placeholder (the entity name NEVER enters the innerHTML string), and the fill path builds the
      cell purely via DOM (textContent / createElement / assigned href), links only a same-origin
      path, and performs NO identity resolution client-side.

Pure/offline: the resolver's data predicates are monkeypatched so no data files are needed.
"""
import os
import re
import sys

os.environ.setdefault("SECRET_KEY", "qc-only-not-a-real-secret")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import app  # noqa: E402

fails = []


def check(cond, msg):
    print(("  [ok] " if cond else "  [FAIL] ") + msg)
    if not cond:
        fails.append(msg)


HOSTILE = 'A<b>x</b> O\'Brien & "Q" <script>'
_canon = app._entity_links.canonical_sport
KNOWN_TEAMS = {('cfb', 'Georgia'), ('nfl', 'KC')}
KNOWN_PLAYERS = {('nfl', 'Known Guy'), ('nfl', HOSTILE), ('nba', 'NBA Guy'), ('cfb', 'CFB Guy')}


def _install_resolver(nba_gated=False):
    app._entity_team_known = lambda sport, team: (_canon(sport), team) in KNOWN_TEAMS
    app._entity_player_known = lambda sport, name: (_canon(sport), name) in KNOWN_PLAYERS
    app._nba_market_gated = lambda sport='nba': bool(nba_gated) and _canon(sport) == 'nba'


def test_server_contract():
    print("\n[A] server emits resolver-produced {text,url,sub}, sport-scoped")
    _install_resolver()
    cell = app._bk_power_name_cell

    # shape
    nfl_p = cell('player', 'NFL', 'Known Guy', 'Pittsburgh Steelers')
    check(set(nfl_p) == {'text', 'url', 'sub'}, "cell has exactly {text,url,sub}")
    check(nfl_p['text'] == 'Known Guy' and nfl_p['sub'] == 'Pittsburgh Steelers', "text + sub carried verbatim")
    check(isinstance(nfl_p['url'], str) and nfl_p['url'].startswith('/tools/player-check'),
          "NFL known player links to player-check (%r)" % nfl_p['url'])

    # CFB player NEVER links, even when 'known' (no CFB player page)
    cfb_p = cell('player', 'CFB', 'CFB Guy', 'Georgia')
    check(cfb_p['url'] is None, "CFB player url is None (no destination) even when resolvable")

    # teams, sport-scoped
    check(cell('team', 'CFB', 'Georgia', 'SEC · 40 g')['url'] == '/tools/cfb-team?team=Georgia',
          "CFB known team -> cfb-team")
    nfl_t = cell('team', 'NFL', 'KC', ' · 60 g')
    check(isinstance(nfl_t['url'], str) and nfl_t['url'].startswith('/tools/nfl-team'),
          "NFL known team -> nfl-team (%r)" % nfl_t['url'])

    # coach NEVER links
    check(cell('coach', 'CFB', 'Kirby Smart', '120 g')['url'] is None, "coach url is None (no coach entity)")
    check(cell('coach', 'NFL', 'Andy Reid', '200 g')['url'] is None, "NFL coach url is None")

    # ambiguous / unknown / gated-out -> resolver returns None -> plain text
    check(cell('player', 'NFL', 'Nobody Unknown', 'X')['url'] is None, "unknown/ambiguous NFL player -> plain")
    check(cell('team', 'NFL', 'ZZZ', 'x')['url'] is None, "unknown NFL team -> plain")

    # hostile label: text kept raw, url fully percent-encoded (no raw markup/space can enter the href)
    h = cell('player', 'NFL', HOSTILE, 'team')
    check(h['text'] == HOSTILE, "hostile label text preserved verbatim (client renders via textContent)")
    check(isinstance(h['url'], str) and '<' not in h['url'] and '"' not in h['url']
          and ' ' not in h['url'] and '>' not in h['url'],
          "hostile label is percent-encoded in the url (%r)" % h['url'])

    # NBA market gate is the resolver's call (still a same-origin link), proving sport-scoped gating
    _install_resolver(nba_gated=True)
    nba = cell('player', 'NBA', 'NBA Guy', 'team')
    check(isinstance(nba['url'], str) and nba['url'].startswith('/'),
          "NBA (stats gate off) resolves to the market page, a same-origin link (%r)" % nba['url'])


def test_attach_does_not_mutate():
    print("\n[A2] _bk_power_attach_ent returns NEW rows, never mutates the cached source")
    _install_resolver()
    src = [{'team': 'Georgia', 'conf': 'SEC', 'games': 40}]
    out = app._bk_power_attach_ent('team', 'CFB', src, 'team',
                                   lambda r: f"{r.get('conf') or ''} · {r.get('games','')} g")
    check('ent' not in src[0], "source row NOT mutated (no 'ent' leaked into the cache)")
    check(out[0]['ent']['url'] == '/tools/cfb-team?team=Georgia' and out[0]['ent']['sub'] == 'SEC · 40 g',
          "attached ent carries resolver url + composed sub")
    check(out[0]['team'] == 'Georgia', "sortVal field (team) preserved on the new row")


def test_client_contract_static():
    print("\n[B] client (bk_power.html) renders via DOM, resolves nothing, no entity in innerHTML")
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates', 'bk_power.html'),
               encoding='utf-8').read()
    # name cells are data-ent placeholders (3: team, coach, player)
    check(src.count("cell:r=>'<td class=\"l\" data-ent></td>'") == 3,
          "all three name columns emit an empty data-ent placeholder (name never in the cell string)")
    # the old interpolated name cells are gone
    check("'<td class=\"l\">'+r.team" not in src and "'<td class=\"l\">'+r.player" not in src
          and "'<td class=\"l\">'+r.coach" not in src,
          "no name is concatenated into an innerHTML <td> string anymore")
    # fill path is pure DOM
    for token in ['function fillEntityCell', 'createElement(\'a\')', 'a.href=url', 'a.textContent=text',
                  'createTextNode', "s.className='sub'; s.textContent=cell.sub"]:
        check(token in src, "fill uses DOM construction: %r present" % token)
    check('.innerHTML' not in src.split('function fillEntityCell', 1)[1].split('}', 1)[0]
          if 'function fillEntityCell' in src else False,
          "fillEntityCell body uses no innerHTML")
    # client does NOT resolve identity: no resolver/url-building in the template
    check('player_url' not in src and 'team_url' not in src and 'entity_links' not in src,
          "no identity resolution / url building in client JS (server-only)")
    # only a same-origin path becomes a link (defensive url guard)
    check("cell.url.charAt(0)==='/'" in src, "url guard: only a leading-'/' path is linked")
    # reversibility: fill falls back to the column's plain() when ent is absent
    check('r.ent || entCol.plain(r)' in src, "reversible: ent absent -> plain() fallback (old plain cell)")


if __name__ == '__main__':
    print("=" * 72)
    print("BK POWER — BATCH-1 ENTITY-LINK PILOT QC (server {text,url} + client DOM contract)")
    print("=" * 72)
    test_server_contract()
    test_attach_does_not_mutate()
    test_client_contract_static()
    print("\nClean:", not fails)
    sys.exit(1 if fails else 0)
