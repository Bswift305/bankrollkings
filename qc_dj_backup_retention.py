"""QC: Decision Journal recurring-backup driver (ops/bk-decision-journal-backup.*).

Proves, on a throwaway store, the five things the dark-rollout requires before the timer is trusted:
manual backup, permissions, integrity, retention (30 daily / 12 monthly), and restore. Reuses the same
`dj.backup` routine the verifier uses. Controlled fixtures; exits 0 on success, 1 otherwise.
"""
from __future__ import annotations

import glob
import os
import sqlite3
import tempfile

import services.decision_journal as dj


def _integrity_ok(path: str) -> bool:
    try:
        c = sqlite3.connect(path)
        try:
            return c.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        finally:
            c.close()
    except sqlite3.Error:
        return False


def run():
    issues = []
    tmp = tempfile.mkdtemp(prefix='bk_dj_backup_')
    db = os.path.join(tmp, 'journal.db')
    bkdir = os.path.join(tmp, 'backups')
    saved_env = os.environ.get('DECISION_JOURNAL_DB_PATH')
    os.environ['DECISION_JOURNAL_DB_PATH'] = db
    try:
        dj.init_db(db)

        # 1) manual / first run: a daily AND a monthly snapshot, both integrity-valid + 0600 (POSIX)
        r1 = dj.run_scheduled_backup(db, bkdir)
        if not (r1.get('ok') and r1.get('daily_made') and r1.get('monthly_made')):
            issues.append(f'first run did not create daily+monthly: {r1}')
        made = sorted(glob.glob(os.path.join(bkdir, 'daily_*.db'))) + \
            sorted(glob.glob(os.path.join(bkdir, 'monthly_*.db')))
        for f in made:
            if not _integrity_ok(f):
                issues.append(f'backup failed integrity: {os.path.basename(f)}')
            if os.name != 'nt' and (os.stat(f).st_mode & 0o777) != 0o600:
                issues.append(f'backup not 0600: {os.path.basename(f)}')
        if os.name != 'nt' and (os.stat(bkdir).st_mode & 0o777) != 0o700:
            issues.append('backup dir not 0700')

        # 2) same-month second run: another daily, monthly NOT re-made (one per UTC month)
        r2 = dj.run_scheduled_backup(db, bkdir)
        if r2.get('monthly_made'):
            issues.append('monthly re-made within the same month (must be once/month)')
        if len(glob.glob(os.path.join(bkdir, 'daily_*.db'))) < 2:
            issues.append('second daily snapshot not created')

        # 3) retention: fresh dir, 35 daily + 15 monthly dummies -> prune to 30 / 12, newest kept
        rdir = os.path.join(tmp, 'retention')
        os.makedirs(rdir)
        for i in range(35):
            open(os.path.join(rdir, f'daily_2020{i:04d}T000000Z.db'), 'w').close()
        for i in range(15):
            open(os.path.join(rdir, f'monthly_2020{i:04d}T000000Z.db'), 'w').close()
        dj._prune_backups(rdir, 'daily', 30)
        dj._prune_backups(rdir, 'monthly', 12)
        nd = len(glob.glob(os.path.join(rdir, 'daily_*.db')))
        nm = len(glob.glob(os.path.join(rdir, 'monthly_*.db')))
        if nd != 30:
            issues.append(f'daily retention kept {nd}, expected 30')
        if nm != 12:
            issues.append(f'monthly retention kept {nm}, expected 12')
        names = {os.path.basename(x) for x in glob.glob(os.path.join(rdir, 'daily_*.db'))}
        if 'daily_20200000T000000Z.db' in names:
            issues.append('retention kept the OLDEST daily (should prune oldest)')
        if 'daily_20200034T000000Z.db' not in names:
            issues.append('retention pruned the NEWEST daily (should keep newest)')

        # 4) restore: corrupt the live DB, restore from a healthy backup, assert recovery; refuse a bad one
        good = sorted(glob.glob(os.path.join(bkdir, 'daily_*.db')))[-1]
        for sfx in ('-wal', '-shm'):
            p = db + sfx
            if os.path.exists(p):
                os.remove(p)
        with open(db, 'wb') as fh:
            fh.write(b'not a sqlite database ' * 500)
        if _integrity_ok(db):
            issues.append('test setup: corruption did not take')
        if not dj.restore(good, db):
            issues.append('restore returned False on a healthy backup')
        if not _integrity_ok(db):
            issues.append('restored DB failed integrity_check')
        bad = os.path.join(tmp, 'bad.db')
        with open(bad, 'wb') as fh:
            fh.write(b'garbage not a db')
        if dj.restore(bad, db):
            issues.append('restore ACCEPTED a corrupt backup (must refuse)')
        if not _integrity_ok(db):
            issues.append('refused restore left the DB unhealthy (must not touch it)')
    finally:
        if saved_env is None:
            os.environ.pop('DECISION_JOURNAL_DB_PATH', None)
        else:
            os.environ['DECISION_JOURNAL_DB_PATH'] = saved_env
    return issues


def main():
    print('=' * 60)
    print('DECISION JOURNAL BACKUP / RETENTION / RESTORE QC')
    print('=' * 60)
    issues = run()
    if issues:
        for i in issues:
            print(f'[FAIL] {i}')
        print('-' * 60)
        print(f'{len(issues)} check(s) FAILED.')
        return 1
    print('[PASS] manual daily+monthly backup, integrity-valid, 0600/0700 (POSIX)')
    print('[PASS] one monthly per UTC month; daily each run')
    print('[PASS] retention prunes to 30 daily / 12 monthly, keeping the newest')
    print('[PASS] restore recovers a corrupt store from a healthy backup; refuses a bad backup')
    print('-' * 60)
    print('Decision Journal backup driver verified.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
