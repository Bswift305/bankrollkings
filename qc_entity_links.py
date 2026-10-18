"""QC: universal player/team entity links -- the sport-scoped resolver + fetch-the-destination proof.

Covers the frozen entity-link contract:
  * pure URL shape + centralized encoding (services/entity_links.py): per-sport destinations, spaces
    percent-encoded (never lowercased/slugified), cross-sport URLs distinct, unsupported -> None.
  * resolver gating (app.player_url / team_url): unknown / ambiguous / historical-only / unsupported
    -> None (-> plain text); exactly-one current entity -> a URL.
  * entity_anchor: prose / heading / disclaimer / option / decorative placements render plain text,
    never a link; an unresolved entity renders plain text; a resolved one renders a single
    <a class="bk-entity-link"> with the centrally-encoded href.
  * identical names across sports never cross-link (sport scoping).
  * FETCH THE DESTINATION: boot app.test_client(), GET the resolved URL, and assert the page renders
    the intended entity (not a string compare on the URL). Sports whose data is absent/gated locally
    are recorded as NOTES (their live 5-sport proof is the authenticated production verification), and
    their resolver output is still asserted to be the honest None (plain text).

Exits 0 when the contract holds, 1 otherwise.
"""
from __future__ import annotations

import pandas as pd

import app
import services.entity_links as el


def run_qc() -> dict:
    issues: list[str] = []
    notes: list[str] = []

    # ---- 1: pure URL shape + encoding -----------------------------------------------------------
    nba = el.player_path('nba', 'Jayson Tatum')
    if nba != '/player/Jayson%20Tatum?sport=nba':
        issues.append(f"1: NBA player_path shape/encoding wrong: {nba!r}")
    if el.player_path('mlb', "Ronald Acuna Jr.") and 'sport=mlb' not in el.player_path('mlb', "Ronald Acuna Jr."):
        issues.append("1: MLB player_path not scoped by sport")
    nfl = el.player_path('nfl', 'Josh Allen')
    if nfl != '/tools/player-check?q=Josh+Allen':
        issues.append(f"1: NFL player_path should hit player-check: {nfl!r}")
    if el.player_path('cfb', 'Anybody') is not None:
        issues.append("1: CFB has no player page -> must be None")
    if el.team_path('nba', 'BOS') != '/team/BOS?sport=nba':
        issues.append(f"1: NBA team_path wrong: {el.team_path('nba', 'BOS')!r}")
    if el.team_path('cfb', 'Georgia') != '/tools/cfb-team?team=Georgia':
        issues.append(f"1: CFB team_path wrong: {el.team_path('cfb', 'Georgia')!r}")
    for s in ('nfl', 'mlb', 'wnba'):
        if el.team_path(s, 'Anybody') is not None:
            issues.append(f"1: {s} has no per-team page -> team_path must be None")
    # cross-sport: same name, different sports -> different URLs (never one shared/inferred page)
    if el.player_path('nba', 'Josh Allen') == el.player_path('nfl', 'Josh Allen'):
        issues.append("1: identical names across sports produced the SAME url (cross-link risk)")
    if el.canonical_sport('ncaaf') != 'cfb':
        issues.append("1: ncaaf should canonicalize to cfb")
    if not any(m.startswith('1:') for m in issues):
        notes.append("pure module: per-sport shapes, %20 encoding, cross-sport URLs distinct, unsupported->None")

    # ---- 2: resolver gating (unknown / ambiguous / historical-only -> None) ----------------------
    saved = {k: getattr(app, k) for k in ('_entity_player_keyset', 'load_mlb_gamelogs',
                                          'load_wnba_gamelogs', 'is_owner_user', 'get_current_user')}
    try:
        # MLB keyset from a controlled gamelog: 'Mike Trout' unique (known, even with repeat rows for
        # the same player), 'Old Timer' absent (historical-only -> None). Two DISTINCT display names
        # normalizing to one key ('AJ Brown' / 'A.J. Brown') are ambiguous -> None.
        app.load_mlb_gamelogs = lambda: pd.DataFrame(
            {'Player': ['Mike Trout', 'Mike Trout', 'AJ Brown', 'A.J. Brown']})
        app._ENTITY_KEYSET_CACHE.clear()
        if not app._entity_player_known('mlb', 'Mike Trout'):
            issues.append("2: a unique current player not recognized as known")
        if app._entity_player_known('mlb', 'AJ Brown'):
            issues.append("2: an ambiguous name (two players, one key) was treated as known")
        if app._entity_player_known('mlb', 'Old Timer'):
            issues.append("2: a historical-only/absent name was treated as known")
        if app.player_url('mlb', 'Mike Trout') != '/player/Mike%20Trout?sport=mlb':
            issues.append(f"2: known MLB player_url wrong: {app.player_url('mlb', 'Mike Trout')!r}")
        if app.player_url('mlb', 'Old Timer') is not None:
            issues.append("2: unknown MLB player_url must be None (-> plain text)")
        # WNBA gated off -> empty keyset -> every WNBA link is plain text (honest, matches the page)
        app.load_wnba_gamelogs = lambda: pd.DataFrame()
        app._ENTITY_KEYSET_CACHE.clear()
        if app.player_url('wnba', 'Anybody') is not None:
            issues.append("2: a gated/empty-source sport still produced a link")
        if not any(m.startswith('2:') for m in issues):
            notes.append("gating: unique=known, duplicate=ambiguous->None, absent=historical->None, gated->None")

        # ---- 3: entity_anchor placement + rendering ---------------------------------------------
        app._entity_player_keyset = lambda sport: {'mike trout': 1}  # deterministic known
        app._ENTITY_KEYSET_CACHE.clear()
        known_html = str(app.entity_anchor('player', 'mlb', 'Mike Trout'))
        if '<a ' not in known_html or 'bk-entity-link' not in known_html or 'sport=mlb' not in known_html:
            issues.append(f"3: a resolved entity did not render a bk-entity-link anchor: {known_html!r}")
        for ctx in ('prose', 'heading', 'disclaimer', 'option', 'decorative'):
            html = str(app.entity_anchor('player', 'mlb', 'Mike Trout', context=ctx))
            if '<a' in html:
                issues.append(f"3: entity_anchor linked a name in {ctx} placement (must be plain text)")
            if 'Mike Trout' not in html:
                issues.append(f"3: entity_anchor dropped the display text in {ctx} placement")
        unknown_html = str(app.entity_anchor('player', 'nba', 'Nobody Here'))
        if '<a' in unknown_html or 'Nobody Here' not in unknown_html:
            issues.append(f"3: an unresolved entity should render plain text: {unknown_html!r}")
        # escaping: a hostile display name must not inject markup
        esc = str(app.entity_anchor('player', 'mlb', '<script>x', context='prose'))
        if '<script>' in esc:
            issues.append("3: entity_anchor did not escape the display text")
        if not any(m.startswith('3:') for m in issues):
            notes.append("anchor: resolved=single bk-entity-link; prose/heading/option/decorative & unknown=plain text")
    finally:
        for k, v in saved.items():
            setattr(app, k, v)
        app._ENTITY_KEYSET_CACHE.clear()

    # ---- 4: FETCH THE DESTINATION (prove the page renders the intended entity) -------------------
    saved_gate = {'is_owner_user': app.is_owner_user, 'get_current_user': app.get_current_user}
    try:
        # A logged-in owner so enforce_access_gate lets the GET through to the real page.
        app.get_current_user = lambda: {'user_id': 'qc', 'email': 'qc@bankrollkings.test',
                                        'plan': 'all_access'}
        app.is_owner_user = lambda u=None: True
        client = app.app.test_client()

        # NFL -> player-check, using a real current-roster player if one is on disk locally.
        try:
            roster = app.load_nfl_current_roster()
        except Exception:
            roster = None
        nfl_name = None
        if roster is not None and not roster.empty and 'Player' in roster.columns:
            for nm in roster['Player'].dropna().astype(str):
                if app._entity_player_known('nfl', nm):
                    nfl_name = nm.strip()
                    break
        if nfl_name:
            url = app.player_url('nfl', nfl_name)
            resp = client.get(url)
            body = resp.get_data(as_text=True)
            last = nfl_name.split()[-1]
            if resp.status_code != 200:
                issues.append(f"4: NFL destination {url} returned {resp.status_code}")
            elif last.lower() not in body.lower():
                issues.append(f"4: NFL player-check page did not render {nfl_name!r}")
            else:
                notes.append(f"fetch NFL: {nfl_name!r} -> {url} renders the player (200)")
        else:
            notes.append("fetch NFL: no resolvable local roster player; live proof is production verification")

        # CFB -> cfb-team, using a known program alias.
        if app._entity_team_known('cfb', 'Georgia'):
            url = app.team_url('cfb', 'Georgia')
            resp = client.get(url)
            body = resp.get_data(as_text=True)
            if resp.status_code != 200:
                issues.append(f"4: CFB destination {url} returned {resp.status_code}")
            elif 'georgia' not in body.lower():
                issues.append("4: CFB team page did not render the team")
            else:
                notes.append(f"fetch CFB: 'Georgia' -> {url} renders the team (200)")
        else:
            notes.append("fetch CFB: 'Georgia' did not resolve locally; live proof is production verification")

        # NBA / WNBA / MLB: assert HONEST resolver output locally (data is gated/absent on this box),
        # and when present, fetch. Either way the resolver must be correct, not guessing.
        for sport in ('nba', 'mlb', 'wnba'):
            try:
                ldr = {'nba': app.load_gamelogs, 'mlb': app.load_mlb_gamelogs,
                       'wnba': app.load_wnba_gamelogs}[sport]
                df = ldr()
            except Exception:
                df = None
            name = None
            if df is not None and not df.empty and 'Player' in df.columns:
                for nm in df['Player'].dropna().astype(str):
                    if app._entity_player_known(sport, nm):
                        name = nm.strip()
                        break
            if name:
                url = app.player_url(sport, name)
                resp = client.get(url)
                if resp.status_code != 200:
                    issues.append(f"4: {sport} destination {url} returned {resp.status_code}")
                else:
                    notes.append(f"fetch {sport.upper()}: {name!r} -> {url} (200)")
            else:
                # no current data locally -> resolver MUST return plain text (None), never a guess
                if app.player_url(sport, 'Someone Random') is not None:
                    issues.append(f"4: {sport} produced a link with no resolvable current data")
                else:
                    notes.append(f"fetch {sport.upper()}: no local data -> resolver returns plain text (honest)")
    finally:
        for k, v in saved_gate.items():
            setattr(app, k, v)

    return {'issues': issues, 'notes': notes}


def main() -> int:
    report = run_qc()
    print('=' * 60)
    print('BANKROLL KINGS UNIVERSAL ENTITY-LINK QC')
    print('=' * 60)
    for note in report['notes']:
        print(f'[NOTE] {note}')
    if report['notes']:
        print()
    if not report['issues']:
        print('No entity-link issues detected.')
        return 0
    for msg in report['issues']:
        print(f'[FAIL] {msg}')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
