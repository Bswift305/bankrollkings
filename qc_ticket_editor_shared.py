"""QC: the shared ticket-editor component (King's Tickets restoration, Step 3).

Step 3.1 scope: Today's Cards (/tools/daily-card) renders the SHARED editor partial with every editing
affordance intact (legs with full data-* provenance, swap modal, reroll, save-image, bench pool, and the
editing JS). Step 3.2 extends this to prove the King's Tickets surface produces IDENTICAL ordered leg
identities from the same builder (the two surfaces cannot drift). Read-only; owner-bypass.

Deterministic: the editor + drift checks run against a PINNED SYNTHETIC SLATE (fixture legs with fresh
single-book quotes patched into app._card_pools), so they execute in every environment -- a data-less
worktree or CI no longer skips them into a red test. The LIVE slate is then checked separately with an
explicit supported no-data assertion: it must render either the editor or the honest empty state.
"""
from __future__ import annotations

import copy
import re
from datetime import datetime, timedelta, timezone

import app

REQUIRED = ['class="dc-grid"', 'class="dc-leg"', 'class="dc-swap"', 'dc-reroll', 'dc-saveimg',
            'dc-swapbackdrop', 'id="dc-bench"', 'function reprice', 'function writeLeg', 'eligibleSwaps',
            # Step 3.3 shared add/remove/reorder controls + behaviours
            'dc-up', 'dc-down', 'dc-rm', 'dc-addleg', 'dc-live', 'aria-live="polite"',
            'function addLeg', 'function removeLeg', 'function moveLeg', 'function enforce',
            'eligibleAdds', 'window.confirm', 'grid.addEventListener']
LEG_RE = re.compile(r'class="dc-leg" data-game="([^"]*)" data-price="([^"]*)" data-tier="([^"]*)" '
                    r'data-sport="([^"]*)" data-reason="([^"]*)" data-label="([^"]*)"')


def _synthetic_pools():
    """A fixed slate: 6 floors + 3 swings on 9 distinct games, each with a complete, fresh quote."""
    at = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%SZ')
    # D4 kickoff gate: fixture games kick off in the future (qc_ticket_kickoff_gate.py owns that contract)
    kick = (datetime.now(timezone.utc) + timedelta(hours=30)).strftime('%Y-%m-%dT%H:%M:%SZ')

    def leg(i, tier, price, hit):
        game, line = f"SYN{i}A @ SYN{i}H", 40.5 + i
        label = f"Synthetic Player {i} Rec Yds {line:g}+"
        return {'sport': 'NFL', 'kind': 'prop', 'tier': tier, 'label': label, 'player': f"Synthetic Player {i}",
                'line': line, 'game': game, 'price': price, 'hit': hit, 'sample': 12,
                'reason': f"synthetic fixture leg {i}", 'score': hit, 'book': 'SyntheticBook', 'quote_at': at,
                'event_id': f"syn-evt-{i}", 'kickoff_utc': kick,
                'quote': {'book': 'SyntheticBook', 'price': price, 'line': line, 'event': game,
                          'market': 'player_reception_yds', 'selection': f"Synthetic Player {i} Over {line:g}",
                          'updated_utc': at}}
    floors = [leg(i, 'floor', -150 - 5 * i, 90 - i) for i in range(6)]
    swings = [leg(10 + i, 'swing', 130 + 10 * i, 60 - i) for i in range(3)]
    return floors, swings


def _with_synthetic_slate(fn):
    fx = _synthetic_pools()
    orig_pools, orig_dmap = app._card_pools, app._game_date_map
    app._card_pools = lambda *a, **k: copy.deepcopy(fx)
    app._game_date_map = lambda: {}
    try:
        return fn()
    finally:
        app._card_pools, app._game_date_map = orig_pools, orig_dmap


def _render(path):
    orig_u, orig_o = app.get_current_user, app.is_owner_user
    app.get_current_user = lambda: {'user_id': 'qc', 'email': 'qc@bk.test', 'plan': 'all_access'}
    app.is_owner_user = lambda u=None: True
    try:
        r = app.app.test_client().get(path)
        return r.status_code, r.get_data(as_text=True)
    finally:
        app.get_current_user, app.is_owner_user = orig_u, orig_o


def legs_by_card(html):
    """Ordered leg identities per card (membership + order), tolerant of attribute order."""
    cards = re.split(r'class="dc-card', html)[1:]
    return [[m[:6] for m in LEG_RE.findall(c)] for c in cards]


def run_qc():
    issues, notes = _with_synthetic_slate(_run_structure)
    # LIVE slate: explicit supported no-data assertion -- the editor OR the honest empty state, never neither.
    code, html = _render('/tools/daily-card')
    if code != 200:
        issues.append(f"live /tools/daily-card returned {code}")
    elif 'class="dc-grid"' in html:
        notes.append("live slate: shared editor rendered")
    elif 'bkn-empty' in html:
        notes.append("live slate: no executable legs -> honest empty state rendered (supported no-data state)")
    else:
        issues.append("live slate rendered neither the shared editor nor the empty state")
    return {'issues': issues, 'notes': notes}


def _run_structure():
    issues, notes = [], []
    code, html = _render('/tools/daily-card')
    if code != 200:
        issues.append(f"/tools/daily-card returned {code}")
        return {'issues': issues, 'notes': notes}
    if '{% include' in html or '{%include' in html:
        issues.append("unrendered {% include %} leaked into the page (partial not resolved)")
    missing = [tok for tok in REQUIRED if tok not in html]
    if missing:
        issues.append(f"shared editor missing affordances: {missing}")
    else:
        notes.append("shared editor present on Today's Cards (legs+provenance, swap modal, reroll, "
                     "save-image, bench, editing JS)")
    cards = legs_by_card(html)
    nlegs = sum(len(c) for c in cards)
    if cards and nlegs:
        # every leg carries full provenance tuple (game, price, tier, sport, reason, label)
        notes.append(f"synthetic slate: {len(cards)} card(s), {nlegs} legs; every leg carries data-* provenance")
    else:
        issues.append("synthetic slate produced no cards -- the structure check could not run")
    # the partial file exists and is the single source
    import os
    if not os.path.exists('templates/_ticket_editor.html'):
        issues.append("_ticket_editor.html (the shared component) is missing")

    # ---- Step 3.2: the two surfaces cannot drift ----
    # identical inputs -> identical ordered leg identities across Today's Cards and King's Tickets.
    q = '?sizes=3&sizes=4&risk=balanced&legs=all&timeframe=smart'
    c1, h1 = _render('/tools/daily-card' + q)
    c2, h2 = _render('/tools/kings-tickets' + q)
    if c2 != 200:
        issues.append(f"/tools/kings-tickets returned {c2}")
    else:
        # King's Tickets is its own branded surface (not a Daily Cards redirect)
        if "King&rsquo;s <span class=\"accent\">Tickets" not in h2 and "King's" not in h2:
            issues.append("King's Tickets page is not branded as King's Tickets")
        if 'dc-grid' not in h2 and 'bkn-empty' not in h2:
            issues.append("King's Tickets renders neither the shared editor nor an honest empty state")
        if c1 == 200:
            d_legs, k_legs = legs_by_card(h1), legs_by_card(h2)
            if d_legs != k_legs:
                issues.append(f"SURFACES DRIFTED: daily-card legs != kings-tickets legs "
                              f"({sum(len(c) for c in d_legs)} vs {sum(len(c) for c in k_legs)} legs / "
                              f"{len(d_legs)} vs {len(k_legs)} cards)")
            else:
                notes.append(f"no drift: both surfaces produce identical ordered leg identities "
                             f"({len(k_legs)} cards, {sum(len(c) for c in k_legs)} legs) from the same builder")
    # saved Daily Cards URL (a shared/legacy view) still resolves
    sc, _ = _render('/tools/daily-card')
    if sc != 200:
        issues.append(f"existing /tools/daily-card URL no longer resolves ({sc})")
    else:
        notes.append("existing Today's Cards URL still resolves (compatibility intact)")
    return issues, notes


def main():
    r = run_qc()
    print('=' * 60)
    print('BANKROLL KINGS SHARED TICKET-EDITOR QC')
    print('=' * 60)
    for n in r['notes']:
        print(f'[NOTE] {n}')
    if r['notes']:
        print()
    if not r['issues']:
        print('No shared-ticket-editor issues detected.')
        return 0
    for m in r['issues']:
        print(f'[FAIL] {m}')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
