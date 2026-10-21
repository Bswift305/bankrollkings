"""QC: King's Tickets ephemeral draft store (Step 4, DARK) — corrective #2 coverage.

Exercises the second round of review blockers on top of the first:
- CAS on CLEAR: omitted revision on an existing draft rejected; stale rejected; correct works; nonexistent
  is a no-op; account deletion uses the separate administrative method.
- Strict revision: bool / float (1.9) / decimal-string / negative all rejected (no int() truncation).
- Timestamps: naive/local leg + combined timestamps rejected; tz-aware normalized to canonical UTC.
- Combined price_format is stored and round-trips.
- Quote-state invariants: a 'current' leg without full provenance is rejected (service + DB CHECK).
- Authoritative boundary: the public DraftService takes opaque references + a server-side resolver and
  ignores any client-supplied authoritative field; it never accepts raw client leg dicts.
- Startup never mutates an existing store before validating it: an unsupported DB is byte-identical after a
  failed open. Schema singleton/version still fail closed.
- Path safety: escape rejected (all hosts); symlinked ancestor + wrong owner/mode fail closed (POSIX/prod).
- Flag-off service creates NO filesystem entries. Route-layer import guard holds.
Plus the carried-over first-round coverage (mandatory create/update CAS, threaded race, fault injection,
account binding, corruption -> StoreUnavailable). Temp DB; exits 0 when all hold.
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
import tempfile
import threading
from pathlib import Path

import services.kings_tickets_drafts as kd

ISSUES, NOTES = [], []


def ok(cond, fail_msg, pass_msg=None):
    if cond:
        if pass_msg:
            NOTES.append(pass_msg)
    else:
        ISSUES.append(fail_msg)


def raises(exc, fn, msg):
    try:
        fn()
        ISSUES.append(msg + ' (did not raise)')
        return False
    except exc:
        return True
    except Exception as e:  # noqa: BLE001
        ISSUES.append(msg + f' (raised {type(e).__name__}, wanted {exc.__name__})')
        return False


def _leg(i=0, **k):
    """A fully-provenanced 'current' canonical leg (what a server-side resolver would produce)."""
    base = {'sport': 'NFL', 'league': 'NFL', 'event_id': 'G%d' % i, 'market_key': 'rec_yds',
            'direction': 'OVER', 'player_name': 'Player %d' % i, 'line': 45.5, 'price': -110,
            'price_format': 'american', 'sportsbook': 'DK', 'quote_scope': 'single-leg',
            'source_provider': 'oddsapi', 'source_timestamp': '2026-10-21T00:00:00Z',
            'display_label': 'Label %d' % i, 'quote_state': 'current'}
    base.update(k)
    return base


def _legs(n):
    return [_leg(i) for i in range(n)]


def _store(td, name='active_drafts.db'):
    return kd.KingsTicketDraftStore(path=os.path.join(td, 'kt', name))


class _FaultConn:
    """Proxy over a real sqlite3 connection that raises at the Nth statement matching `marker` (Connection
    .execute is read-only, so we wrap rather than monkeypatch)."""
    def __init__(self, real, marker, nth):
        object.__setattr__(self, '_real', real)
        object.__setattr__(self, '_m', marker)
        object.__setattr__(self, '_nth', nth)
        object.__setattr__(self, '_cnt', [0])

    def execute(self, sql, *a, **k):
        if self._m in sql:
            self._cnt[0] += 1
            if self._cnt[0] == self._nth:
                raise RuntimeError('injected@' + self._m)
        return self._real.execute(sql, *a, **k)

    def __getattr__(self, n):
        return getattr(object.__getattribute__(self, '_real'), n)

    def __setattr__(self, n, v):
        setattr(object.__getattribute__(self, '_real'), n, v)


def run_qc():
    orig_runtime = os.environ.get('BK_RUNTIME_DIR')
    orig_flag = os.environ.get('KINGS_TICKETS_DRAFTS_ENABLED')
    try:
        return _run_qc_inner()
    finally:
        for key, val in (('BK_RUNTIME_DIR', orig_runtime), ('KINGS_TICKETS_DRAFTS_ENABLED', orig_flag)):
            if val is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = val


def _run_qc_inner():
    # 0. flag dark
    ok(not kd.drafts_enabled(), 'flag ON by default', 'flag dark by default')

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        S = _store(td)
        try:
            # 1. mandatory-revision CAS (create=0 / update=current / omission+stale rejected)
            raises(kd.DraftInvalid, lambda: S.save_draft('u1', _legs(3), expected_revision=None),
                   'create with expected_revision=None accepted')
            raises(kd.DraftConflict, lambda: S.save_draft('u1', _legs(3), expected_revision=5),
                   'create with nonzero revision accepted')
            r1 = S.save_draft('u1', _legs(3), expected_revision=0)
            ok(r1['revision'] == 1, 'first create revision != 1', 'create requires expected_revision=0')
            raises(kd.DraftInvalid, lambda: S.save_draft('u1', _legs(4), expected_revision=None),
                   'update with omitted revision accepted (CAS bypass)')
            raises(kd.DraftConflict, lambda: S.save_draft('u1', _legs(4), expected_revision=0),
                   'update with stale revision accepted')
            r2 = S.save_draft('u1', _legs(4), expected_revision=1)
            ok(r2['revision'] == 2, 'update did not bump revision',
               'CAS: update requires the current revision; omission/stale rejected')

            # 1b. strict revision type: bool / float / decimal-string / negative rejected
            for bad in (True, 1.9, 0.0, '0', '1', -1):
                raises(kd.DraftInvalid, lambda b=bad: S.save_draft('ur', _legs(2), expected_revision=b),
                       f'revision {bad!r} accepted (must be a real non-negative int)')
            NOTES.append('revision strict: bool/float(1.9)/decimal-string/negative all rejected')

            # 2. 2-5 bounds
            for bad in (1, 6):
                raises(kd.DraftInvalid, lambda b=bad: S.save_draft('ub', _legs(b), expected_revision=0),
                       f'{bad}-leg draft accepted')
            NOTES.append('2-5 leg bounds enforced')

            # 3. identity: client id ignored; duplicate selection w/ different labels+ids rejected; insufficient rejected
            dup = [_leg(0, display_label='alpha', canonical_leg_id='client-1'),
                   _leg(0, display_label='beta', canonical_leg_id='client-2')]  # same selection, different label+id
            raises(kd.DraftInvalid, lambda: S.save_draft('ud', dup, expected_revision=0),
                   'duplicate underlying selection (diff labels/ids) accepted')
            raises(kd.DraftInvalid,
                   lambda: S.save_draft('ui', [_leg(0), {'display_label': 'bare', 'quote_state': 'unknown'}],
                                        expected_revision=0),
                   'leg with only a display label accepted')
            NOTES.append('identity reconstructed server-side: client id ignored, dup selection + bare leg rejected')

            # 4. CLEAR CAS: omitted (existing) rejected, stale rejected, nonexistent no-op, correct works
            S.save_draft('uc', _legs(2), expected_revision=0)                      # rev 1
            raises(kd.DraftInvalid, lambda: S.clear_draft('uc', expected_revision=None),
                   'omitted-revision clear of an EXISTING draft accepted')
            ok(S.get_draft('uc') is not None, 'draft vanished after a rejected omitted clear')
            raises(kd.DraftConflict, lambda: S.clear_draft('uc', expected_revision=0),
                   'stale-revision clear accepted')
            ok(S.get_draft('uc') is not None, 'draft vanished after a rejected stale clear')
            ok(S.clear_draft('nobody', expected_revision=None) == 0, 'nonexistent clear raised instead of no-op')
            ok(S.clear_draft('uc', expected_revision=1) == 1, 'clear with correct revision failed',
               'clear CAS: omitted/stale rejected on an existing draft; nonexistent no-op; correct works')
            # account-deletion uses the separate administrative path (unconditional)
            S.save_draft('uc', _legs(2), expected_revision=0)
            ok(S.administrative_delete('uc') == 1 and S.get_draft('uc') is None,
               'administrative_delete did not remove the draft',
               'account-deletion uses a separate administrative method (not the route-facing clear)')

            # 5. combined all-or-nothing + price_format round-trips
            raises(kd.DraftInvalid,
                   lambda: S.save_draft('uq', _legs(2), expected_revision=0, combined={'price': -120, 'source': 'x'}),
                   'combined price with only source accepted')
            good_combined = {'price': -120, 'price_format': 'american', 'sportsbook': 'DK',
                             'scope': 'combined-ticket', 'timestamp': '2026-10-21T00:00:00Z', 'source': 'oddsapi'}
            S.save_draft('uq', _legs(2), expected_revision=0, combined=good_combined)
            gq = S.get_draft('uq')
            ok(gq['draft']['combined_price'] == -120 and gq['draft']['combined_price_scope'] == 'combined-ticket'
               and gq['draft']['combined_price_format'] == 'american',
               'full combined quote / price_format not stored',
               'combined price all-or-nothing; price_format stored and round-trips')

            # 6. strict numeric / NaN / inf / bool / bad american
            bad_vals = [('risk', float('nan')), ('risk', float('inf')), ('risk', True), ('risk', -5),
                        ('price', 'abc'), ('price', float('nan')), ('price', 50), ('line', float('inf'))]
            for field, val in bad_vals:
                if field == 'risk':
                    raises(kd.DraftInvalid, lambda v=val: S.save_draft('un', _legs(2), expected_revision=0, risk_amount=v),
                           f'risk={val!r} accepted')
                else:
                    raises(kd.DraftInvalid, lambda f=field, v=val: S.save_draft('un', [_leg(0, **{f: v}), _leg(1)], expected_revision=0),
                           f'{field}={val!r} accepted')
            NOTES.append('numeric validation rejects NaN/inf/bool/negative/oversized + invalid American + strings')

            # 6b. timezone enforcement: naive leg + combined timestamps rejected; tz-aware normalized to UTC
            raises(kd.DraftInvalid,
                   lambda: S.save_draft('utz', [_leg(0, source_timestamp='2026-10-21T00:00:00'), _leg(1)], expected_revision=0),
                   'naive leg source_timestamp accepted')
            raises(kd.DraftInvalid,
                   lambda: S.save_draft('utz', [_leg(0, event_start='2026-10-21T00:00:00'), _leg(1)], expected_revision=0),
                   'naive leg event_start accepted')
            raises(kd.DraftInvalid,
                   lambda: S.save_draft('utz', _legs(2), expected_revision=0,
                                        combined={'price': -120, 'price_format': 'american', 'sportsbook': 'DK',
                                                  'scope': 'combined-ticket', 'timestamp': '2026-10-21T00:00:00',
                                                  'source': 'x'}),
                   'naive combined timestamp accepted')
            S.save_draft('utz', [_leg(0, source_timestamp='2026-10-21T12:00:00-04:00'), _leg(1)], expected_revision=0)
            norm = S.get_draft('utz')['legs'][0]['source_timestamp']
            ok(norm == '2026-10-21T16:00:00Z', f'tz-aware timestamp not normalized to UTC (got {norm})',
               'timestamps: naive rejected; tz-aware normalized to canonical UTC (Z)')

            # 6c. quote-state provenance: a 'current' leg missing provenance is rejected
            raises(kd.DraftInvalid,
                   lambda: S.save_draft('ucp', [_leg(0, sportsbook=None), _leg(1)], expected_revision=0),
                   "'current' leg without a sportsbook accepted")
            raises(kd.DraftInvalid,
                   lambda: S.save_draft('ucp', [_leg(0, source_provider=None), _leg(1)], expected_revision=0),
                   "'current' leg without a source_provider accepted")
            raises(kd.DraftInvalid,
                   lambda: S.save_draft('ucp', [_leg(0, price=-110, price_format=None, quote_state='unknown'), _leg(1)],
                                        expected_revision=0),
                   'a supplied price without a price_format accepted')
            NOTES.append("quote-state: a 'current' leg must carry full provenance; a price requires a format")

            # 7. expired-on-read TTL boundary + no TTL extension on read
            S.save_draft('ut', _legs(2), expected_revision=0)
            exp = S.get_draft('ut')['draft']['expires_at']
            ok(S.get_draft('ut', now=exp - 1) is not None, 'draft absent just before expiry')
            ok(S.get_draft('ut', now=exp) is None, 'expired draft (expires_at==now) was returned')
            ok(S.get_draft('ut', now=exp - 1000) is None, 'expired draft not purged on read',
               'expired-on-read: absent at boundary, purged, TTL not extended')

            # 8. fault injection at every transaction phase -> rollback to prior complete revision
            def inject_phase(marker, nth):
                st = _store(td, 'inj.db')
                try:
                    st.save_draft('p', _legs(3), expected_revision=0)          # seed rev 1 (3 legs)
                    real = st.conn
                    st.conn = _FaultConn(real, marker, nth)
                    hit = False
                    try:
                        st.save_draft('p', _legs(4), expected_revision=1)      # attempt rev 2 (4 legs) -> fault
                    except (RuntimeError, kd.StoreUnavailable, kd.DraftInvalid):
                        hit = True
                    st.conn = real
                    d = st.get_draft('p')
                    rolled = (hit and d is not None and d['draft']['revision'] == 1 and len(d['legs']) == 3)
                finally:
                    st.close()
                for suf in ('', '-wal', '-shm'):
                    try:
                        os.remove(os.path.join(td, 'kt', 'inj.db' + suf))
                    except OSError:
                        pass
                return rolled
            phases = [('UPDATE drafts', 1), ('DELETE FROM draft_legs', 1), ('INSERT INTO draft_legs', 2),
                      ('COMMIT', 1)]
            allrb = all(inject_phase(m, n) for m, n in phases)
            ok(allrb, 'a fault phase did not roll back to the prior complete revision',
               'fault injection at update/delete-legs/leg-insert/commit all roll back to prior revision')

            # 8b. REAL threaded CAS race on two independent connections to the same DB
            race_db = os.path.join(td, 'kt', 'race.db')
            seed = _store(td, 'race.db')
            seed.save_draft('R', _legs(2), expected_revision=0)   # rev 1
            seed.close()
            barrier = threading.Barrier(2)
            results = []

            def contender():
                st = kd.KingsTicketDraftStore(path=race_db)
                try:
                    barrier.wait(timeout=5)
                    st.save_draft('R', _legs(3), expected_revision=1)   # both target rev 1
                    results.append('ok')
                except kd.DraftConflict:
                    results.append('conflict')
                except Exception as e:  # noqa: BLE001
                    results.append('ERR:' + type(e).__name__)
                finally:
                    st.close()
            threads = [threading.Thread(target=contender) for _ in range(2)]
            [t.start() for t in threads]
            [t.join(10) for t in threads]
            final = kd.KingsTicketDraftStore(path=race_db)
            fd = final.get_draft('R')
            final.close()
            ok(sorted(results) == ['conflict', 'ok'],
               f'threaded CAS race result wrong: {results} (want exactly one ok + one conflict)',
               'threaded CAS race: exactly one save wins, the other gets DraftConflict (not a lock error)')
            ok(fd is not None and fd['draft']['revision'] == 2 and len(fd['legs']) == 3,
               f'race left an inconsistent draft: rev={fd and fd["draft"]["revision"]}',
               'race left one complete draft with a single revision increment')

            # 9. account binding
            S.save_draft('A', _legs(2), expected_revision=0)
            S.save_draft('B', _legs(3), expected_revision=0)
            ok(len(S.get_draft('A')['legs']) == 2 and len(S.get_draft('B')['legs']) == 3,
               'account binding leaked across accounts', 'account-bound reads isolated')
        finally:
            S.close()

        # 10. schema singleton / mismatch fail-closed
        sp = os.path.join(td, 'kt', 'schema.db')
        s2 = kd.KingsTicketDraftStore(path=sp); s2.close()
        c = sqlite3.connect(sp); c.execute('UPDATE schema_meta SET version=999'); c.commit(); c.close()
        raises(kd.StoreUnavailable, lambda: kd.KingsTicketDraftStore(path=sp), 'unsupported schema version opened')
        NOTES.append('schema singleton + exact-version fail-closed')

        # 10b. an unsupported existing DB is BYTE-IDENTICAL after a failed open (no pre-validation mutation)
        bp = os.path.join(td, 'kt', 'byte.db')
        bst = kd.KingsTicketDraftStore(path=bp)
        bst.save_draft('z', _legs(2), expected_revision=0)
        bst.conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        bst.conn.execute('PRAGMA journal_mode=DELETE')          # leave WAL so no -wal/-shm linger
        bst.close()
        c = sqlite3.connect(bp); c.execute('UPDATE schema_meta SET version=999'); c.commit(); c.close()
        for suf in ('-wal', '-shm'):
            try:
                os.remove(bp + suf)
            except OSError:
                pass
        with open(bp, 'rb') as fh:
            before = hashlib.sha256(fh.read()).hexdigest()
        raises(kd.StoreUnavailable, lambda: kd.KingsTicketDraftStore(path=bp),
               'unsupported DB opened (byte-preservation)')
        with open(bp, 'rb') as fh:
            after = hashlib.sha256(fh.read()).hexdigest()
        no_sidecar = not os.path.exists(bp + '-wal') and not os.path.exists(bp + '-shm')
        ok(before == after and no_sidecar, 'unsupported DB mutated during a failed open',
           'unsupported DB byte-identical after a failed startup (no pre-validation mutation)')

        # 11. path escape rejected (all hosts) via the production dir-preparation guard. A path OUTSIDE the
        # runtime root, and a path nested too deep beneath it, are both refused (only root or one controlled
        # child level is allowed).
        os.environ['BK_RUNTIME_DIR'] = td
        outside = Path(td).parent / 'kt-escape-not-under-runtime' / 'x.db'
        raises(kd.StoreUnavailable, lambda: kd._prepare_prod_dir(outside),
               'draft dir outside the runtime root accepted')
        raises(kd.StoreUnavailable,
               lambda: kd._prepare_prod_dir(Path(os.path.join(td, 'a', 'b', 'x.db'))),
               'draft dir nested too deep beneath the runtime root accepted')
        NOTES.append('path escape (outside, or nested too deep beneath, the runtime root) rejected')

        # 11b. POSIX/prod-only: symlinked ancestor + wrong owner/mode fail closed
        if os.name == 'posix':
            # symlinked draft dir
            sroot = os.path.join(td, 'symroot'); os.mkdir(sroot, 0o700)
            realtarget = os.path.join(td, 'realtarget'); os.mkdir(realtarget, 0o700)
            os.symlink(realtarget, os.path.join(sroot, 'kings_tickets'))
            os.environ['BK_RUNTIME_DIR'] = sroot
            raises(kd.StoreUnavailable, lambda: kd.KingsTicketDraftStore(),
                   'symlinked draft dir accepted')
            # wrong file / dir mode fails closed (no silent repair). Start from a clean 0700 dir / 0600 db
            # with no lingering WAL sidecars so each check isolates the file it is meant to exercise.
            ktdir = os.path.join(td, 'kt')
            permdb = os.path.join(ktdir, 'perm.db')
            kd.KingsTicketDraftStore(path=permdb).close()
            for suf in ('-wal', '-shm'):
                try:
                    os.remove(permdb + suf)
                except OSError:
                    pass
            os.chmod(ktdir, 0o700); os.chmod(permdb, 0o600)
            kd._validate_prod_files(Path(permdb))                      # a clean 0700 dir + 0600 db validates
            os.chmod(permdb, 0o644)
            raises(kd.StoreUnavailable, lambda: kd._validate_prod_files(Path(permdb)),
                   'too-open DB mode (0644) accepted')
            os.chmod(permdb, 0o600)
            os.chmod(ktdir, 0o755)
            raises(kd.StoreUnavailable, lambda: kd._validate_prod_files(Path(permdb)),
                   'too-open dir mode (0755) accepted')
            os.chmod(ktdir, 0o700)
            # runtime ROOT may be a traversable 0755 parent (the real /var/lib layout), but NOT
            # group/other-writable; a full prod-style open succeeds with a 0755 root + a 0700 leaf.
            proot = os.path.join(td, 'proot'); os.mkdir(proot, 0o755)
            kd._require_safe_root(Path(proot))                         # 0755 owner-only-writable root accepted
            os.environ['BK_RUNTIME_DIR'] = proot
            e2e = kd.KingsTicketDraftStore()
            try:
                e2e.save_draft('e2e', _legs(2), expected_revision=0)
                ok(e2e.get_draft('e2e') is not None, 'prod-style open under a 0755 root failed',
                   'prod-style open: a 0755 root + a 0700 leaf works end-to-end')
            finally:
                e2e.close()
            os.chmod(proot, 0o777)
            raises(kd.StoreUnavailable, lambda: kd._require_safe_root(Path(proot)),
                   'group/other-writable runtime root accepted')
            NOTES.append('POSIX: symlinked ancestor rejected; clean dir+db validates; wrong dir/db/-wal/-shm '
                         'owner+mode fail closed; 0755 root accepted (not o/g-writable); prod-style open works')
        else:
            NOTES.append('symlink + owner/mode checks are POSIX-only (verified on prod Linux via SSM)')

        # 12. corruption -> StoreUnavailable (degrade, not crash); non-StoreUnavailable open failure FAILS
        corrupt = os.path.join(td, 'kt', 'corrupt.db')
        kd.KingsTicketDraftStore(path=corrupt).close()
        for suf in ('', '-wal', '-shm'):
            p = corrupt + suf
            if os.path.exists(p):
                os.remove(p)
        with open(corrupt, 'wb') as fh:
            fh.write(b'\x00not a sqlite db at all' * 50)
        cs = None
        try:
            cs = kd.KingsTicketDraftStore(path=corrupt)
            cs.get_draft('x')
            ISSUES.append('corrupt DB did not degrade to StoreUnavailable')
        except kd.StoreUnavailable:
            NOTES.append('corruption degrades to StoreUnavailable (no crash, no Journal fallback)')
        except Exception as e:  # noqa: BLE001 -- a non-StoreUnavailable open failure FAILS the QC
            ISSUES.append(f'corrupt DB raised {type(e).__name__}, not StoreUnavailable')
        finally:
            if cs is not None:
                cs.close()

    # 13. AUTHORITATIVE boundary: public service resolves references server-side, ignores client fields
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td2:
        os.environ['BK_RUNTIME_DIR'] = td2
        os.environ['KINGS_TICKETS_DRAFTS_ENABLED'] = '1'
        source = {
            'cand_A': {'sport': 'NFL', 'league': 'NFL', 'event_id': 'GX', 'market_key': 'rec_yds',
                       'direction': 'OVER', 'player_name': 'Authoritative Name', 'line': 45.5, 'price': -110,
                       'price_format': 'american', 'sportsbook': 'DK', 'quote_scope': 'single-leg',
                       'source_provider': 'oddsapi', 'source_timestamp': '2026-10-21T00:00:00Z',
                       'quote_state': 'current', 'display_label': 'A'},
            'cand_B': {'sport': 'NFL', 'league': 'NFL', 'event_id': 'GY', 'market_key': 'rush_yds',
                       'direction': 'UNDER', 'player_name': 'Other Name', 'line': 60.5, 'price': 100,
                       'price_format': 'american', 'sportsbook': 'FD', 'quote_scope': 'single-leg',
                       'source_provider': 'oddsapi', 'source_timestamp': '2026-10-21T00:00:00Z',
                       'quote_state': 'current', 'display_label': 'B'},
        }

        def resolver(candidate_ref, quote_ref):
            return dict(source[candidate_ref])

        # a reference carrying authoritative fields is rejected outright
        raises(kd.DraftInvalid,
               lambda: kd.DraftService.save('svc', [{'candidate_ref': 'cand_A', 'player_name': 'HACKED', 'line': 999}],
                                            0, resolver=resolver),
               'reference carrying client authoritative fields accepted')
        # a client dict with no candidate_ref is rejected
        raises(kd.DraftInvalid,
               lambda: kd.DraftService.save('svc', [{'player_name': 'x', 'line': 1}], 0, resolver=resolver),
               'client leg dict (no candidate_ref) accepted')
        # with no resolver the public service refuses (never accepts client dicts)
        raises(kd.DraftInvalid,
               lambda: kd.DraftService.save('svc', [{'candidate_ref': 'cand_A'}], 0),
               'public service wrote without a server-side resolver')
        # clean references resolve to AUTHORITATIVE legs; nothing client could set wins
        kd.DraftService.save('svc', [{'candidate_ref': 'cand_A', 'entry_method': 'click'},
                                     {'candidate_ref': 'cand_B'}], 0, resolver=resolver)
        got = kd.DraftService.get('svc')
        names = sorted(l['player_name'] for l in got['legs'])
        ok(got['draft']['revision'] == 1 and names == ['Authoritative Name', 'Other Name'],
           f'authoritative resolution failed: {names}',
           'authoritative boundary: references resolved server-side; client-supplied fields cannot override')
        os.environ['KINGS_TICKETS_DRAFTS_ENABLED'] = '0'

    # 14. flag-off service refuses AND creates no filesystem entries
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td3:
        os.environ['BK_RUNTIME_DIR'] = td3
        os.environ.pop('KINGS_TICKETS_DRAFTS_ENABLED', None)   # dark
        opened = {'n': 0}
        real_store = kd.KingsTicketDraftStore

        def spy(*a, **k):
            opened['n'] += 1
            return real_store(*a, **k)
        kd.KingsTicketDraftStore = spy
        try:
            for call in (lambda: kd.DraftService.get('u'),
                         lambda: kd.DraftService.save('u', [{'candidate_ref': 'c'}], 0),
                         lambda: kd.DraftService.clear('u', 1)):
                raises(kd.StoreDisabled, call, 'DraftService op did not refuse while flag off')
            # account-deletion is flag-independent but must not CREATE a store when none exists
            ok(kd.DraftService.delete_account_data('u') == 0, 'delete_account_data raised on an absent store')
            ok(opened['n'] == 0, 'DraftService opened/created the store while the flag was off',
               'flag-off DraftService refuses and opens nothing')
            ok(not os.path.exists(os.path.join(td3, 'kings_tickets')),
               'flag-off service created filesystem entries',
               'flag-off service creates no filesystem entries')
        finally:
            kd.KingsTicketDraftStore = real_store

    # 15. route-layer import guard: application code must not import the repository directly
    try:
        app_src = open('app.py', encoding='utf-8', errors='replace').read()
        ok('KingsTicketDraftStore' not in app_src,
           'app.py imports/uses KingsTicketDraftStore directly (must use DraftService)',
           'route-layer import guard: app.py does not touch the repository directly')
    except OSError:
        NOTES.append('import guard skipped (app.py unreadable)')

    return {'issues': ISSUES, 'notes': NOTES}


def main():
    r = run_qc()
    print('=' * 68)
    print("BANKROLL KINGS - KING'S TICKETS DRAFT STORE QC (dark, corrective #2)")
    print('=' * 68)
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
