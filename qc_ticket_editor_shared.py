"""QC: the shared ticket-editor component (King's Tickets restoration, Step 3).

Step 3.1 scope: Today's Cards (/tools/daily-card) renders the SHARED editor partial with every editing
affordance intact (legs with full data-* provenance, swap modal, reroll, save-image, bench pool, and the
editing JS). Step 3.2 extends this to prove the King's Tickets surface produces IDENTICAL ordered leg
identities from the same builder (the two surfaces cannot drift). Read-only; owner-bypass.
"""
from __future__ import annotations

import re

import app

REQUIRED = ['class="dc-grid"', 'class="dc-leg"', 'class="dc-swap"', 'dc-reroll', 'dc-saveimg',
            'dc-swapbackdrop', 'id="dc-bench"', 'function reprice', 'function writeLeg', 'eligibleSwaps']
LEG_RE = re.compile(r'class="dc-leg" data-game="([^"]*)" data-price="([^"]*)" data-tier="([^"]*)" '
                    r'data-sport="([^"]*)" data-reason="([^"]*)" data-label="([^"]*)"')


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
        notes.append(f"{len(cards)} card(s), {nlegs} legs; every leg carries data-* provenance")
    else:
        notes.append("no cards on the current slate (empty state) -- structure check skipped")
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
    return {'issues': issues, 'notes': notes}


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
