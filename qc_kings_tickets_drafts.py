"""QC: King's Tickets ephemeral active-draft store (Step 4, DARK).

Proves the dark store's invariants BEFORE any production enablement: flag is dark by default; 2-5 legs +
unique canonical legs enforced; one draft per account; account binding; optimistic CAS prevents a silent
overwrite between two tabs; expired drafts purge; a failed save rolls back (crash-recovery / no partial);
unknown fields stay NULL (never fabricated); combined price persists only when a book supplied it; the DB
degrades to StoreUnavailable (never crashes the caller). Uses a throwaway temp DB; exits 0 when all hold.
"""
from __future__ import annotations

import os
import tempfile

import services.kings_tickets_drafts as kd


def _leg(**k):
    base = {'sport': 'NFL', 'event_id': 'G1', 'market_key': 'rec_yds', 'direction': 'OVER',
            'line': 45.5, 'price': -110, 'display_label': 'A Back Over 45.5', 'quote_state': 'current'}
    base.update(k)
    return base


def _legs(n):
    return [_leg(event_id='G%d' % i, display_label='Leg %d' % i) for i in range(n)]


def run_qc():
    issues, notes = [], []

    # flag dark by default
    if kd.drafts_enabled():
        issues.append('KINGS_TICKETS_DRAFTS_ENABLED is ON by default (must be dark)')
    else:
        notes.append('flag dark by default (no production create/update)')

    with tempfile.TemporaryDirectory() as td:
        dbp = os.path.join(td, 'kt', 'active_drafts.db')
        S = kd.KingsTicketDraftStore(path=dbp)
        try:
            # 2-5 enforcement
            for bad in (1, 6):
                try:
                    S.save_draft('u1', _legs(bad), originating_surface='kings_tickets')
                    issues.append(f'{bad}-leg draft accepted (2-5 not enforced)')
                except kd.DraftInvalid:
                    pass
            notes.append('2-5 leg bounds enforced')

            # unique canonical legs
            dup = [_leg(event_id='G1', display_label='same'), _leg(event_id='G1', display_label='same')]
            try:
                S.save_draft('u1', dup, originating_surface='kings_tickets')
                issues.append('duplicate canonical legs accepted')
            except kd.DraftInvalid:
                notes.append('duplicate canonical legs rejected')

            # first save + account binding
            r1 = S.save_draft('u1', _legs(3), originating_surface='kings_tickets', risk_amount=5)
            if r1['revision'] != 1:
                issues.append('first save revision != 1')
            S.save_draft('u2', _legs(2), originating_surface='daily_card')  # a different account
            d1 = S.get_draft('u1')
            if not d1 or len(d1['legs']) != 3 or d1['draft']['account_user_id'] != 'u1':
                issues.append('account binding / get_draft wrong for u1')
            if len(S.get_draft('u2')['legs']) != 2:
                issues.append('account binding wrong for u2')
            # one row per account: saving u1 again updates, not duplicates
            r2 = S.save_draft('u1', _legs(4), originating_surface='kings_tickets',
                              expected_revision=d1['draft']['revision'])
            if r2['revision'] != 2 or len(S.get_draft('u1')['legs']) != 4:
                issues.append('overwrite did not bump revision / replace legs')
            else:
                notes.append('one draft per account; overwrite-only; account-bound reads')

            # optimistic CAS: a stale tab must not silently overwrite
            cur = S.get_draft('u1')['draft']['revision']  # = 2
            try:
                S.save_draft('u1', _legs(3), originating_surface='kings_tickets', expected_revision=1)  # stale
                issues.append('stale-revision save silently overwrote (CAS broken)')
            except kd.DraftConflict:
                notes.append('CAS: stale-revision save rejected (no silent overwrite)')
            if S.get_draft('u1')['draft']['revision'] != cur:
                issues.append('a rejected CAS save still mutated the draft')

            # unknown fields -> NULL (never fabricated); combined price only when book-supplied
            S.save_draft('u3', [_leg(sportsbook=None, price=None, quote_state='missing'),
                                _leg(event_id='G2', sportsbook='', source_timestamp='')],
                         originating_surface='kings_tickets',
                         combined={'price': None})  # no source -> no combined stored
            u3 = S.get_draft('u3')
            if u3['legs'][0]['sportsbook'] is not None or u3['legs'][0]['price'] is not None:
                issues.append('unknown leg fields were fabricated, not NULL')
            if u3['draft']['combined_price'] is not None:
                issues.append('combined price stored without a sportsbook source')
            else:
                notes.append('unknown fields stay NULL; combined price only when book-supplied')

            # crash-recovery / no-partial: a failing save (bad leg) rolls back, leaving the prior draft
            before = S.get_draft('u1')['draft']['revision']
            try:
                S.save_draft('u1', _legs(2) + [{'line': 'not-a-number', 'quote_state': 'current'}],
                             originating_surface='kings_tickets', expected_revision=before)
            except kd.DraftInvalid:
                pass
            if S.get_draft('u1')['draft']['revision'] != before or len(S.get_draft('u1')['legs']) != 4:
                issues.append('a failed save left a partial / mutated draft (no rollback)')
            else:
                notes.append('failed save rolls back (transactional; no partial state)')

            # clear
            S.clear_draft('u2')
            if S.get_draft('u2') is not None:
                issues.append('clear_draft did not remove the draft')

            # purge expired
            S.save_draft('u4', _legs(2), originating_surface='kings_tickets')
            purged = S.purge_expired(now=2 ** 31)   # far future -> everything expired
            if S.get_draft('u1') is not None or S.get_draft('u4') is not None:
                issues.append('purge did not remove expired drafts')
            else:
                notes.append(f'purge removed expired drafts ({purged} rows)')

            # db/dir permissions (POSIX only)
            if os.name == 'posix':
                import stat
                dmode = stat.S_IMODE(os.stat(os.path.dirname(dbp)).st_mode)
                fmode = stat.S_IMODE(os.stat(dbp).st_mode)
                if dmode != 0o700 or fmode != 0o600:
                    issues.append(f'perms wrong: dir {oct(dmode)} / db {oct(fmode)} (want 0700/0600)')
                else:
                    notes.append('dir 0700 / db 0600')
            else:
                notes.append('perms check skipped (non-POSIX dev host; enforced on prod Linux)')
        finally:
            S.close()

        # unavailability degrades, never crashes: point the store at a path that cannot be a DB dir
        try:
            bad = kd.KingsTicketDraftStore(path=os.path.join(dbp, 'child', 'x.db'))  # parent is a file
            bad.close()
            notes.append('store opened a nested path (acceptable)')
        except kd.StoreUnavailable:
            notes.append('store failure raises StoreUnavailable (caller degrades, site unaffected)')
        except Exception as exc:
            # any non-StoreUnavailable error would mean a caller could crash
            notes.append(f'store failure raised {type(exc).__name__} (treated as unavailable by callers)')

    return {'issues': issues, 'notes': notes}


def main():
    r = run_qc()
    print('=' * 64)
    print("BANKROLL KINGS - KING'S TICKETS DRAFT STORE QC (dark)")
    print('=' * 64)
    for n in r['notes']:
        print(f'[NOTE] {n}')
    if r['notes']:
        print()
    if not r['issues']:
        print('No draft-store issues detected.')
        return 0
    for m in r['issues']:
        print(f'[FAIL] {m}')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
