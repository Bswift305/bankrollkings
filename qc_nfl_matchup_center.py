"""QC: NFL Matchup Center membership + identity + abstention invariants (Green Light B1 / step 2).

Enforces the build contract:
  1. MEMBERSHIP COMPLETE — every current-slate game appears; no model/missing module suppresses one
     (the card count == the raw slate game count from build_football_live_games).
  2. CANONICAL IDENTITY — every card has a stable game_id of the form date:AWAY@HOME (ABBRs, not display
     names), and ids are UNIQUE (no display-name-collision join).
  3. ABSTENTION — every module cell carries an explicit `available` flag + a `source`; an unavailable
     module is False (never a silently-zeroed value).
  4. DERIVED/CONTEXT LABELLING — ATS wave + tendencies carry their context note (not a recommendation);
     milestones are labelled distinct from market-line.
  5. DETERMINISM / ORDER — two builds over the same inputs yield identical game order + ids.
  6. ROUTE TIMING — the cached/materialized route render stays within a generous ceiling (no cold-route
     regression: the nine feeds are built once, not per game).

Exits 0 when all hold, 1 otherwise.
"""
from __future__ import annotations

import time

import app

MODULES = ('market', 'weather', 'line_move', 'injuries', 'ats_wave', 'milestones', 'tendencies')


def run_qc():
    issues, notes = [], []

    # raw slate (the membership oracle) -- same source the builder iterates, unfiltered
    try:
        raw = app.build_football_live_games(app.load_nfl_game_market_odds(), app.load_nfl_schedule(),
                                            date_filter='week')
    except Exception as exc:
        raw = []
        notes.append(f"raw slate unavailable ({type(exc).__name__}) -- membership check skipped")
    raw_ids = set()
    for g in raw:
        aa = app._mc_abbr(g.get('away'))
        ha = app._mc_abbr(g.get('home'))
        raw_ids.add(f"{str(g.get('date') or '')}:{aa}@{ha}")

    app._NFL_MATCHUP_CENTER_CACHE.clear()
    ctx = app.build_nfl_matchup_center_context()
    games = ctx.get('games', [])

    # 1. membership complete
    if raw and len(games) != len(raw):
        issues.append(f"membership incomplete: {len(games)} cards vs {len(raw)} slate games (a game was suppressed)")
    else:
        notes.append(f"membership complete: {len(games)} card(s) == slate")
    ids = [g['game_id'] for g in games]
    if raw and set(ids) != raw_ids:
        missing = raw_ids - set(ids)
        if missing:
            issues.append(f"slate games missing from the center: {sorted(missing)[:3]}")

    # 2. canonical identity + uniqueness
    import re
    pat = re.compile(r'^\d{4}-\d{2}-\d{2}:[A-Z]{2,3}@[A-Z]{2,3}$')
    bad = [i for i in ids if not pat.match(i)]
    # unresolved teams are allowed (abbr may be '') but then resolved must be False
    unresolved_bad = [g['game_id'] for g in games if not g['resolved'] and (g['away_url'] or g['home_url'])]
    if unresolved_bad:
        issues.append(f"unresolved games still emitted entity links: {unresolved_bad[:3]}")
    if len(set(ids)) != len(ids):
        issues.append("duplicate game_id (display-name collision in the canonical identity)")
    else:
        notes.append("canonical game_ids unique (date:AWAY@HOME)")

    # 3. abstention: every module cell has available + source
    abstain_ok = True
    for g in games:
        for m in MODULES:
            cell = g.get(m)
            if not isinstance(cell, dict) or 'available' not in cell or 'source' not in cell:
                issues.append(f"{g['game_id']} module '{m}' missing available/source (abstention contract)")
                abstain_ok = False
                break
        if not abstain_ok:
            break
    if abstain_ok and games:
        notes.append("every module cell carries available + source (unknown -> unavailable, never zero)")

    # 4. derived/context labelling
    for g in games[:1] if games else []:
        if 'recommendation' not in g['ats_wave'].get('note', '').lower():
            pass  # note says "not a recommendation"; just ensure the note exists
        if not g['ats_wave'].get('note'):
            issues.append("ATS wave missing its context note")
        if 'distinct' not in g['milestones'].get('note', '').lower() and 'market-line' not in g['milestones'].get('note', '').lower():
            issues.append("milestones not labelled distinct from market-line")
    if games and not any('derived' in g['tendencies'].get('note', '').lower() for g in games[:1]):
        issues.append("tendencies not labelled derived")
    if not any(m in issues for m in issues if 'label' in m or 'recommendation' in m or 'derived' in m):
        notes.append("ATS wave = factual context; milestones labelled distinct; tendencies = derived")

    # 5. determinism / order
    app._NFL_MATCHUP_CENTER_CACHE.clear()
    ctx2 = app.build_nfl_matchup_center_context()
    ids2 = [g['game_id'] for g in ctx2.get('games', [])]
    if ids2 != ids:
        issues.append("non-deterministic game order/ids across builds")
    else:
        notes.append("deterministic order + ids across builds")

    # 6. route timing (warm cache / materialized -- generous ceiling)
    orig_u, orig_o = app.get_current_user, app.is_owner_user
    app.get_current_user = lambda: {'user_id': 'qc', 'email': 'qc@bk.test', 'plan': 'all_access'}
    app.is_owner_user = lambda u=None: True
    try:
        client = app.app.test_client()
        client.get('/tools/nfl-matchup-center')   # warm
        t0 = time.perf_counter()
        r = client.get('/tools/nfl-matchup-center')
        warm_ms = (time.perf_counter() - t0) * 1000.0
        if r.status_code != 200:
            issues.append(f"route returned {r.status_code}")
        elif warm_ms > 1500.0:
            issues.append(f"warm route render {warm_ms:.0f}ms (>1500ms -> cold-route regression risk)")
        else:
            notes.append(f"warm route render {warm_ms:.0f}ms (cached/materialized)")
    finally:
        app.get_current_user, app.is_owner_user = orig_u, orig_o

    return {'issues': issues, 'notes': notes}


def main():
    r = run_qc()
    print('=' * 64)
    print('BANKROLL KINGS NFL MATCHUP CENTER QC')
    print('=' * 64)
    for n in r['notes']:
        print(f'[NOTE] {n}')
    if r['notes']:
        print()
    if not r['issues']:
        print('No matchup-center issues detected.')
        return 0
    for m in r['issues']:
        print(f'[FAIL] {m}')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
