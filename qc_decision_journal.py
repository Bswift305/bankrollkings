"""QC: Decision Journal V1 acceptance tests (the 15 frozen checks).

Drives `services/decision_journal.JournalRepository` against throwaway temp databases (no live
network, no shared state). Implements the §13 acceptance table of
`docs/decision_journal_implementation_design.md` as named check functions. Exits 0 iff all pass.
"""
from __future__ import annotations

import os
import sqlite3
import tempfile
import threading
import uuid

import services.decision_journal as dj


def _tmp():
    d = tempfile.mkdtemp(prefix='dj_qc_')
    return os.path.join(d, 'journal.db')


def _repo():
    return dj.JournalRepository(db_path=_tmp())


# -- leg builders ------------------------------------------------------------------------------------
def _prosp_leg(**kw):
    leg = {
        'selection_origin': 'user-selected', 'entry_method': 'manual',
        'user_reviewed_before_bet': 'yes', 'surfaces_known': True, 'surfaces': [],
        'sport': 'NFL', 'game': 'KC@BUF 2099-12-31', 'event_start': '2099-12-31T18:00:00Z',
        'player': 'P. Mahomes', 'market': 'passing yards', 'selection': 'over', 'line': 274.5,
        'quote_scope': 'individual-leg', 'price': -110, 'book': 'DK',
        'decision_time': '2099-12-30T12:00:00Z', 'reason_tags': ['matchup'],
    }
    leg.update(kw)
    return leg


def _past_leg(**kw):
    leg = {
        'selection_origin': 'user-selected', 'entry_method': 'manual',
        'user_reviewed_before_bet': 'unknown', 'surfaces_known': True, 'surfaces': [],
        'sport': 'NFL', 'game': 'OLD GAME', 'event_start': '2000-01-01T00:00:00Z',
        'market': 'spread', 'selection': 'KC -3.5', 'line': -3.5,
        'quote_scope': 'individual-leg', 'price': -110, 'reason_tags': ['other'],
    }
    leg.update(kw)
    return leg


def _locked_ticket(repo, uid='userA'):
    """A historical ticket whose single leg already kicked off -> locked immediately."""
    tid = repo.create_ticket(uid, ticket_type='straight', record_provenance='historical-documented',
                             legs=[_past_leg()])
    return tid


# -- checks ------------------------------------------------------------------------------------------
def qc_dj_concurrency():
    repo = _repo()
    n_each, errs = 6, []

    def worker(tag):
        try:
            for _ in range(n_each):
                tid = repo.create_ticket('userA', ticket_type='straight',
                                         record_provenance='prospective-captured', legs=[_prosp_leg()])
                repo.settle_ticket('userA', tid, book_ticket_result='win',
                                   cash_stake_cents=1000, total_returned_cents=1909)
        except Exception as e:  # noqa
            errs.append(repr(e))

    ts = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    got = len(repo.list_tickets('userA', limit=1000))
    if errs:
        return False, f'worker errors: {errs[:2]}'
    if got != 2 * n_each:
        return False, f'expected {2 * n_each} tickets, got {got} (lost update?)'
    return True, f'{got} tickets written by 2 concurrent writers, none lost'


def qc_dj_crash_recovery():
    path = _tmp()
    dj.init_db(path)
    # simulate a crash: open a write txn, insert ticket + leg, then close WITHOUT commit
    conn = dj.connect(path)
    conn.execute('BEGIN IMMEDIATE')
    tid = str(uuid.uuid4())
    conn.execute("""INSERT INTO tickets(ticket_id,user_id,ticket_type,record_provenance,created_at,updated_at)
                    VALUES(?,?,'straight','historical-documented','x','x')""", (tid, 'userA'))
    conn.execute("""INSERT INTO legs(leg_id,ticket_id,leg_index,selection_origin,entry_method,
                    user_reviewed_before_bet,sport,game,market,selection,quote_scope)
                    VALUES(?,?,0,'unknown','manual','unknown','NFL','g','spread','x','unavailable')""",
                 (str(uuid.uuid4()), tid))
    conn.close()  # no commit -> rollback on close
    conn2 = dj.connect(path)
    tickets = conn2.execute('SELECT count(*) FROM tickets').fetchone()[0]
    legs = conn2.execute('SELECT count(*) FROM legs').fetchone()[0]
    conn2.close()
    if tickets or legs:
        return False, f'partial write survived: {tickets} tickets / {legs} legs'
    return True, 'aborted transaction left no ticket and no leg'


def qc_dj_unknown_fields():
    repo = _repo()
    leg = _prosp_leg(line=None, quote_scope='unavailable', price=None)
    tid = repo.create_ticket('userA', ticket_type='straight',
                             record_provenance='prospective-captured', legs=[leg])
    repo.settle_ticket('userA', tid, book_ticket_result='pending')  # no stake/returned
    t = repo.get_ticket('userA', tid)
    if t['legs'][0]['line'] is not None or t['legs'][0]['price'] is not None:
        return False, 'unknown line/price were coerced'
    if t['net_cash_pl_cents'] is not None or t['roi'] is not None:
        return False, 'net/roi fabricated from missing inputs'
    return True, 'NULL line/price/net/roi preserved as unknown'


def qc_dj_selection():
    repo = _repo()
    # missing selection rejected
    try:
        repo.create_ticket('userA', ticket_type='straight', record_provenance='prospective-captured',
                           legs=[_prosp_leg(selection='')])
        return False, 'leg without selection was accepted'
    except dj.ValidationError:
        pass
    # over vs under distinct fingerprints
    over = [_prosp_leg(selection='over')]
    under = [_prosp_leg(selection='under')]
    fp_o = dj.compute_fingerprint('userA', 'DK', '2099-12-30T12:00:00Z', over)
    fp_u = dj.compute_fingerprint('userA', 'DK', '2099-12-30T12:00:00Z', under)
    if fp_o == fp_u:
        return False, 'over/under produced the same fingerprint'
    t1 = repo.create_ticket('userA', ticket_type='straight', record_provenance='prospective-captured', legs=over)
    t2 = repo.create_ticket('userA', ticket_type='straight', record_provenance='prospective-captured', legs=under)
    if t1 == t2:
        return False, 'over/under produced the same ticket'
    return True, 'selection required; over vs under are distinct records + fingerprints'


def qc_dj_sgp_pricing():
    repo = _repo()
    # combined-ticket leg with no price SAVES
    sgp = [_prosp_leg(quote_scope='combined-ticket', price=None),
           _prosp_leg(selection='under', quote_scope='combined-ticket', price=None, leg_index=1)]
    repo.create_ticket('userA', ticket_type='same-game-parlay',
                       record_provenance='prospective-captured', legs=sgp)
    # individual-leg leg with NULL price REJECTED
    try:
        repo.create_ticket('userA', ticket_type='straight', record_provenance='prospective-captured',
                           legs=[_prosp_leg(quote_scope='individual-leg', price=None)])
        return False, 'individual-leg with NULL price accepted'
    except dj.ValidationError:
        return True, 'SGP combined-only saved; individual-leg NULL price rejected'


def qc_dj_push_void_cashout_promo():
    f = dj.compute_net_cash_pl
    cases = {
        'cash win': (f(1000, 1909, 'win', None), 909),
        'void': (f(1000, 1000, 'void', None), 0),
        'push': (f(1000, 1000, 'push', None), 0),
        'free-bet-only win': (f(0, 900, 'win', None), 900),
        'full cashout': (f(1000, 1200, 'cashout', 1200), 200),
        'partial cashout + settle': (f(1000, 1500, 'cashout', 500), 500),
        'missing returned': (f(1000, None, 'win', None), None),
        'cashout missing amount': (f(1000, 1200, 'cashout', None), None),
    }
    for name, (got, want) in cases.items():
        if got != want:
            return False, f'{name}: net={got} want {want}'
    # ROI zero-denominator: free-bet-only shows profit but ROI unavailable
    if dj.compute_roi(900, 0) is not None:
        return False, 'ROI computed with zero cash stake'
    if dj.compute_roi(909, 1000) is None:
        return False, 'ROI missing when it should be available'
    return True, 'settlement math + zero-denominator ROI all correct'


def qc_dj_immutability():
    repo = _repo()
    tid = _locked_ticket(repo)
    t = repo.get_ticket('userA', tid)
    lid = t['legs'][0]['leg_id']
    conn = dj.connect(repo.db_path)
    blocked = []

    def expect_block(label, sql, params=()):
        try:
            conn.execute('BEGIN IMMEDIATE'); conn.execute(sql, params); conn.execute('COMMIT')
            blocked.append(f'{label} NOT blocked')
        except sqlite3.Error:
            conn.execute('ROLLBACK')

    expect_block('ticket frozen col', "UPDATE tickets SET game_thesis='x' WHERE ticket_id=?", (tid,))
    expect_block('leg frozen col', "UPDATE legs SET line=-7 WHERE leg_id=?", (lid,))
    expect_block('leg insert', """INSERT INTO legs(leg_id,ticket_id,leg_index,selection_origin,entry_method,
        user_reviewed_before_bet,sport,game,market,selection,quote_scope)
        VALUES(?,?,9,'unknown','manual','unknown','NFL','g','spread','x','unavailable')""",
                 (str(uuid.uuid4()), tid))
    expect_block('leg delete', "DELETE FROM legs WHERE leg_id=?", (lid,))
    expect_block('tag add', "INSERT INTO leg_reason_tags(leg_id,tag) VALUES(?,'streak')", (lid,))
    expect_block('tag delete', "DELETE FROM leg_reason_tags WHERE leg_id=?", (lid,))
    expect_block('surface add', "INSERT INTO leg_bk_surfaces(leg_id,surface) VALUES(?,'wave-watch')", (lid,))
    expect_block('earliest_kickoff', "UPDATE tickets SET earliest_kickoff='2099-01-01T00:00:00Z' WHERE ticket_id=?", (tid,))
    conn.close()
    if blocked:
        return False, '; '.join(blocked)
    return True, 'all frozen columns + child inserts/deletes + earliest_kickoff blocked after lock'


def qc_dj_corrections_append_only():
    repo = _repo()
    tid = _locked_ticket(repo)
    repo.correct('userA', 'tickets', tid, 'game_thesis', 'corrected thesis', 'fat-fingered', 'userA')
    eff = repo.effective_value('userA', 'tickets', tid, 'game_thesis')
    if eff != 'corrected thesis':
        return False, f'effective value not overlaid: {eff!r}'
    conn = dj.connect(repo.db_path)
    for op, sql in (('update', "UPDATE decision_revisions SET reason='x'"),
                    ('delete', "DELETE FROM decision_revisions")):
        try:
            conn.execute('BEGIN IMMEDIATE'); conn.execute(sql); conn.execute('COMMIT')
            conn.close()
            return False, f'decision_revisions {op} was allowed'
        except sqlite3.Error:
            conn.execute('ROLLBACK')
    conn.close()
    return True, 'correction appends + overlays; revisions are append-only (no update/delete)'


def qc_dj_prospective_timing():
    repo = _repo()
    checks = []
    # missing event_start
    try:
        repo.create_ticket('userA', ticket_type='straight', record_provenance='prospective-captured',
                           legs=[_prosp_leg(event_start=None)]); checks.append('missing event_start accepted')
    except (dj.ValidationError, sqlite3.Error):
        pass
    # decision_time after event_start
    try:
        repo.create_ticket('userA', ticket_type='straight', record_provenance='prospective-captured',
                           legs=[_prosp_leg(decision_time='2099-12-31T19:00:00Z')])
        checks.append('late decision_time accepted')
    except (dj.ValidationError, sqlite3.Error):
        pass
    # thesis after kickoff
    try:
        repo.create_ticket('userA', ticket_type='straight', record_provenance='prospective-captured',
                           game_thesis='late', game_thesis_at='2099-12-31T20:00:00Z',
                           legs=[_prosp_leg()]); checks.append('late thesis accepted')
    except (dj.ValidationError, sqlite3.Error):
        pass
    # zero legs
    try:
        repo.create_ticket('userA', ticket_type='straight', record_provenance='prospective-captured',
                           legs=[]); checks.append('zero-leg prospective accepted')
    except dj.ValidationError:
        pass
    # leg added after kickoff (locked historical ticket)
    tid = _locked_ticket(repo)
    conn = dj.connect(repo.db_path)
    try:
        conn.execute('BEGIN IMMEDIATE')
        conn.execute("""INSERT INTO legs(leg_id,ticket_id,leg_index,selection_origin,entry_method,
            user_reviewed_before_bet,sport,game,market,selection,quote_scope)
            VALUES(?,?,5,'unknown','manual','unknown','NFL','g','spread','x','unavailable')""",
                     (str(uuid.uuid4()), tid))
        conn.execute('COMMIT'); checks.append('leg added after kickoff accepted')
    except sqlite3.Error:
        conn.execute('ROLLBACK')
    conn.close()
    if checks:
        return False, '; '.join(checks)
    return True, 'event_start required; decision_time<start; thesis<kickoff; >=1 leg; no leg after kickoff'


def qc_dj_bk_origin():
    repo = _repo()
    # BK leg without origin rejected
    try:
        repo.create_ticket('userA', ticket_type='straight', record_provenance='prospective-captured',
                           legs=[_prosp_leg(selection_origin='BK-rule-assembled')])
        return False, 'BK-rule-assembled leg without bk_origin accepted'
    except dj.ValidationError:
        pass
    # with a valid origin it saves
    origin = {'surface': 'wave-watch', 'candidate_id': 'cand-1', 'rule_version': 'v1',
              'captured_at': '2099-12-30T11:00:00Z', 'displayed_line': 274.5, 'displayed_price': -108}
    tid = repo.create_ticket('userA', ticket_type='straight', record_provenance='prospective-captured',
                             legs=[_prosp_leg(selection_origin='BK-rule-assembled', bk_origin=origin)])
    t = repo.get_ticket('userA', tid)
    if not t['legs'][0]['bk_origin']:
        return False, 'bk_origin not stored'
    # captured_at after decision_time rejected (trigger)
    bad = dict(origin, captured_at='2099-12-30T13:00:00Z')  # after decision_time 12:00
    try:
        repo.create_ticket('userA', ticket_type='straight', record_provenance='prospective-captured',
                           legs=[_prosp_leg(selection_origin='BK-rule-assembled', bk_origin=bad)])
        return False, 'captured_at after decision_time accepted'
    except (dj.ValidationError, sqlite3.Error):
        return True, 'BK-origin required+stored; captured_at<=decision_time enforced'


def qc_dj_import_idempotent():
    repo = _repo()
    legs = [_prosp_leg()]
    fp = dj.compute_fingerprint('userA', 'DK', '2099-12-30T12:00:00Z', legs)
    repo.create_ticket('userA', ticket_type='straight', record_provenance='prospective-captured',
                       legs=legs, import_fingerprint=fp)
    try:
        repo.create_ticket('userA', ticket_type='straight', record_provenance='prospective-captured',
                           legs=[_prosp_leg()], import_fingerprint=fp)
    except dj.ValidationError:
        pass
    n = len(repo.list_tickets('userA', limit=100))
    if n != 1:
        return False, f'duplicate fingerprint produced {n} tickets'
    return True, 're-import of the same fingerprint is a no-op (1 ticket)'


def qc_dj_migration():
    repo = _repo()
    bets = [
        {'id': 'b1', 'sport': 'NFL', 'description': 'KC -3', 'selection': 'KC -3', 'odds': -110,
         'stake': 100, 'result': 'win', 'placed': '2026-10-01', 'book': 'DK'},
        {'id': 'b2', 'sport': 'NFL', 'description': '3-leg parlay', 'result': 'loss', 'stake': 50,
         'legs': [{}, {}, {}], 'placed': '2026-10-02'},
    ]
    m1 = repo.migrate_user_json('userA', bets)
    straight = [t for t in repo.list_tickets('userA') if t['ticket_type'] == 'straight']
    legacy = [t for t in repo.list_tickets('userA') if t['ticket_type'] == 'legacy_flat_ticket']
    if m1 != 2 or len(straight) != 1 or len(legacy) != 1:
        return False, f'migrated={m1} straight={len(straight)} legacy={len(legacy)}'
    if straight[0]['legs_count'] != 1 or legacy[0]['legs_count'] != 0:
        return False, f"leg counts wrong: straight={straight[0]['legs_count']} legacy={legacy[0]['legs_count']}"
    m2 = repo.migrate_user_json('userA', bets)  # re-run
    if m2 != 0 or len(repo.list_tickets('userA')) != 2:
        return False, f're-run not idempotent: migrated={m2} total={len(repo.list_tickets("userA"))}'
    repo.reverse_migration('userA')
    if repo.list_tickets('userA'):
        return False, 'reverse migration left rows'
    return True, 'straight->1 leg, parlay->legacy 0 legs; idempotent; reverse removes only migrated'


def qc_dj_access_isolation():
    repo = _repo()
    tid = repo.create_ticket('userA', ticket_type='straight', record_provenance='prospective-captured',
                             legs=[_prosp_leg()])
    if repo.get_ticket('userB', tid) is not None:
        return False, 'user B read user A ticket'
    try:
        repo.settle_ticket('userB', tid, book_ticket_result='win', cash_stake_cents=100, total_returned_cents=190)
        return False, 'user B settled user A ticket'
    except dj.ValidationError:
        pass
    try:
        repo.correct('userB', 'tickets', tid, 'game_thesis', 'x', 'r', 'userB')
        return False, 'user B corrected user A ticket'
    except dj.ValidationError:
        pass
    if repo.list_tickets('userB'):
        return False, 'user B list returned rows'
    return True, 'every public op denies another user (read/settle/correct/list)'


def qc_dj_failure_mode():
    repo = _repo()
    repo.create_ticket('userA', ticket_type='straight', record_provenance='prospective-captured',
                       legs=[_prosp_leg()])
    # corrupt the store
    for suffix in ('-wal', '-shm', ''):
        p = repo.db_path + suffix
        if os.path.exists(p):
            try:
                os.remove(p) if suffix else None
            except OSError:
                pass
    with open(repo.db_path, 'wb') as fh:
        fh.write(b'this is not a sqlite database' * 50)
    if repo.integrity_ok():
        return False, 'corrupt store reported healthy'
    try:
        repo.create_ticket('userA', ticket_type='straight', record_provenance='prospective-captured',
                           legs=[_prosp_leg()])
        return False, 'write to corrupt store did not raise'
    except dj.JournalUnavailable:
        return True, 'corrupt store -> integrity fails, writes raise JournalUnavailable (catchable)'
    except Exception as e:  # noqa
        return False, f'wrong exception type: {type(e).__name__}'


def qc_dj_reporting():
    repo = _repo()
    # two prospective settled tickets + one historical (must be excluded from prospective cuts)
    t1 = repo.create_ticket('userA', ticket_type='straight', record_provenance='prospective-captured',
                            legs=[_prosp_leg(reason_tags=['streak', 'matchup'])])
    repo.settle_ticket('userA', t1, book_ticket_result='win', cash_stake_cents=1000, total_returned_cents=1909,
                       leg_results=[{'leg_id': repo.get_ticket('userA', t1)['legs'][0]['leg_id'],
                                     'leg_result': 'win'}])
    _locked_ticket(repo)  # historical
    rep = repo.report('userA', prospective_only=True)
    if 'by_origin' not in rep or 'by_ticket_type' not in rep:
        return False, 'report missing cuts'
    # sample size present
    if rep['by_origin']['user-selected'].get('n') is None:
        return False, 'no sample size on origin cut'
    # overlapping-tag disclosure + non-causal disclosure present
    d = rep['disclosures']
    if 'overlap' not in d['overlapping_tags'].lower() or 'not causal' not in d['descriptive_only'].lower():
        return False, 'disclosures missing/!'
    # a leg tagged with 2 tags shows up under both (overlap) -> tag counts can exceed leg count
    tags = rep['by_reason_tag']
    if 'streak' not in tags or 'matchup' not in tags:
        return False, 'overlapping tags not both reported'
    # historical excluded: straight prospective bucket counts only the 1 prospective ticket
    if rep['by_ticket_type']['straight']['n'] != 1:
        return False, f"historical leaked into prospective cut: n={rep['by_ticket_type']['straight']['n']}"
    return True, 'sample sizes + overlap/non-causal disclosure present; historical excluded'


CHECKS = [
    ('qc_dj_concurrency', qc_dj_concurrency),
    ('qc_dj_crash_recovery', qc_dj_crash_recovery),
    ('qc_dj_unknown_fields', qc_dj_unknown_fields),
    ('qc_dj_selection', qc_dj_selection),
    ('qc_dj_sgp_pricing', qc_dj_sgp_pricing),
    ('qc_dj_push_void_cashout_promo', qc_dj_push_void_cashout_promo),
    ('qc_dj_immutability', qc_dj_immutability),
    ('qc_dj_corrections_append_only', qc_dj_corrections_append_only),
    ('qc_dj_prospective_timing', qc_dj_prospective_timing),
    ('qc_dj_bk_origin', qc_dj_bk_origin),
    ('qc_dj_import_idempotent', qc_dj_import_idempotent),
    ('qc_dj_migration', qc_dj_migration),
    ('qc_dj_access_isolation', qc_dj_access_isolation),
    ('qc_dj_failure_mode', qc_dj_failure_mode),
    ('qc_dj_reporting', qc_dj_reporting),
]


def main() -> int:
    print('=' * 60)
    print('BANKROLL KINGS DECISION JOURNAL V1 ACCEPTANCE QC')
    print('=' * 60)
    failed = 0
    for name, fn in CHECKS:
        try:
            ok, detail = fn()
        except Exception as e:  # noqa
            ok, detail = False, f'EXCEPTION {type(e).__name__}: {e}'
        print(f'[{"PASS" if ok else "FAIL"}] {name} — {detail}')
        if not ok:
            failed += 1
    print('-' * 60)
    print(f'FAIL: {failed}' if failed else 'All 15 Decision Journal acceptance checks passed.')
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
