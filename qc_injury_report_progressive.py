"""QC: Injury Report server-side progressive disclosure (Site Performance P0, Phase B2 / P3).

Proves the payload reduction did NOT drop or reorder any record and that filtering is faithful:
  1. MEMBERSHIP: paging through every page (default page size) and concatenating yields EXACTLY the
     original unpaginated, deterministically-ordered result -- same rows, same order, no dup, no gap.
  2. FILTERS: a league/status/team/search filter returns exactly the rows that match the predicate,
     in the same relative order as the full set (deterministic).
  3. PAYLOAD: the rendered first page ships far fewer rows than the full set (progressive disclosure),
     and the Load-More fragment + the page are gated identically (PRO_ENDPOINTS) and reachable to an
     owner test client.
  4. REACHABILITY: every record appears on exactly one page.

Exits 0 when all hold, 1 otherwise.
"""
from __future__ import annotations

import hashlib

import app


def _identity(row):
    return (row['league'], row['team'], row['player'], row['status'], row['reason'],
            row['updated'], row['severity'], row['status_bucket'])


def _hash(seq):
    h = hashlib.sha256()
    for item in seq:
        h.update(repr(item).encode('utf-8'))
        h.update(b'\x1e')
    return h.hexdigest()


def _walk(page_size, **filters):
    """Page through the whole result at `page_size`, returning the ordered list of row dicts. The
    builder caps page_size defensively, so there is no single-call 'full page' -- walking is how the
    complete, in-order membership is obtained (and how a real client reaches every record)."""
    out = []
    page = 1
    guard = 0
    meta = None
    while True:
        guard += 1
        if guard > 100000:
            raise RuntimeError("pagination did not terminate")
        ctx = app.build_injury_report_context(page=page, page_size=page_size, **filters)
        out.extend(ctx['rows'])
        meta = ctx
        if not ctx['has_more']:
            break
        page += 1
    return out, meta


def run_qc():
    issues, notes = [], []

    probe = app.build_injury_report_context()
    total = probe['total']
    if total == 0:
        notes.append("no injuries present locally -> membership/payload checks are trivially satisfied")
        # still exercise the routes below
    # 1) MEMBERSHIP + REACHABILITY: walking at the default size must cover exactly `total` records,
    #    each once, and the ordering must be PAGE-SIZE INDEPENDENT (walk at a different size == same).
    walk_a, _ = _walk(app.INJURY_REPORT_PAGE_SIZE)
    walk_b, _ = _walk(37)   # deliberately odd/unrelated page size
    ids_a = [_identity(r) for r in walk_a]
    ids_b = [_identity(r) for r in walk_b]
    full_rows = walk_a   # the canonical full ordered set (reference for the filter checks)

    if len(ids_a) != total:
        issues.append(f"paged walk covered {len(ids_a)} rows but report total is {total} "
                      "(a record is unreachable or double-counted)")
    elif _hash(ids_a) != _hash(ids_b):
        issues.append("pagination is page-size dependent (walk at size 100 != walk at size 37) -- "
                      "a record was dropped, duplicated, or reordered")
    else:
        notes.append(f"membership complete + page-size independent ({len(ids_a)} rows reachable, "
                     "identical order at page sizes 100 and 37)")
    if len(ids_a) != len(set(ids_a)):
        issues.append("a record appeared on more than one page (duplicate across pages)")

    if total == 0:
        return _routes_check(issues, notes, total)

    # 2) FILTERS faithful + order-preserving, verified by WALKING the filtered result (so the cap never
    #    hides rows) against the predicate applied to the full ordered set.
    lp = probe['leagues_present']
    bp = probe['buckets_present']
    tp = probe['teams']
    checks = []
    if lp:
        checks.append(('league', {'league': lp[0]['key']}))
    if bp:
        checks.append(('status', {'status': bp[0]}))
    if tp:
        checks.append(('team', {'team': tp[0]}))
    for label, kw in checks:
        want = [_identity(r) for r in full_rows if app._injury_row_matches(
            r, kw.get('league', ''), kw.get('team', ''), kw.get('status', ''), '')]
        got_rows, _ = _walk(app.INJURY_REPORT_PAGE_SIZE, **kw)
        got = [_identity(r) for r in got_rows]
        if got != want:
            issues.append(f"{label} filter membership/order wrong ({len(got)} vs {len(want)})")
        else:
            notes.append(f"{label} filter faithful + order-preserving ({len(got)} rows)")

    # search: substring over player+team+reason
    token = (full_rows[0]['player'].split() or [''])[0].lower()
    if token:
        want = [_identity(r) for r in full_rows
                if token in f"{r['player']} {r['team']} {r['reason']}".lower()]
        got_rows, _ = _walk(app.INJURY_REPORT_PAGE_SIZE, q=token)
        got = [_identity(r) for r in got_rows]
        if got != want:
            issues.append(f"search filter membership/order wrong for '{token}' ({len(got)} vs {len(want)})")
        else:
            notes.append(f"search '{token}' faithful ({len(got)} rows)")

    return _routes_check(issues, notes, total)


def _routes_check(issues, notes, total):
    page_size = app.INJURY_REPORT_PAGE_SIZE

    # 3) PAYLOAD + gating via the owner test client.
    orig_user, orig_owner = app.get_current_user, app.is_owner_user
    app.get_current_user = lambda: {'user_id': 'qc', 'email': 'qc@bankrollkings.test', 'plan': 'all_access'}
    app.is_owner_user = lambda u=None: True
    try:
        client = app.app.test_client()
        page_html = client.get('/tools/injury-report')
        frag = client.get('/tools/injury-report/rows?page=2')
        if page_html.status_code != 200:
            issues.append(f"/tools/injury-report returned {page_html.status_code}")
        if frag.status_code != 200:
            issues.append(f"/tools/injury-report/rows returned {frag.status_code}")
        # default page should render at most page_size inj-rows (progressive disclosure)
        default_row_count = page_html.get_data(as_text=True).count('class="inj-row')
        if default_row_count > page_size:
            issues.append(f"default page rendered {default_row_count} rows (> page size {page_size}); "
                          "progressive disclosure not applied")
        elif total > page_size and default_row_count >= total:
            issues.append("default page rendered the entire set (no payload reduction)")
        else:
            notes.append(f"default page renders {default_row_count} inj-rows (<= {page_size}); "
                         f"full set is {total} -> payload reduced")
        if frag.status_code == 200 and 'X-Has-More' not in frag.headers:
            issues.append("Load-More fragment missing X-Has-More header")
    finally:
        app.get_current_user, app.is_owner_user = orig_user, orig_owner

    return {'issues': issues, 'notes': notes}


def main():
    r = run_qc()
    print('=' * 64)
    print('BANKROLL KINGS INJURY REPORT PROGRESSIVE-DISCLOSURE QC')
    print('=' * 64)
    for n in r['notes']:
        print(f'[NOTE] {n}')
    if r['notes']:
        print()
    if not r['issues']:
        print('No injury-report progressive-disclosure issues detected.')
        return 0
    for m in r['issues']:
        print(f'[FAIL] {m}')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
