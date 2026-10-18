# Decision Journal — Dark-Production Setup Runbook

**Scope:** the Director's scoped scorecard waiver for **dark-production setup only** (the Oct 16 full
scorecard's MLB + Prelaunch FAILs are pre-existing, present Oct 12–15 before the Journal change; the
Journal section itself passes). This runbook creates the private store and proves it healthy **with
routes still disabled**. It does **not** enable the feature.

**Do NOT in this step:** migrate JSON records, create a test ticket, enable routes, or install the
recurring backup timer. Those come only after this dark setup passes and are separately authorized.

The feature flag `DECISION_JOURNAL_ENABLED` stays **OFF** (unset) throughout, so `/journal*` return 404.

---

The verifier is **non-destructive to the live store**. It initializes the schema **only when the store
does not yet exist** (fresh setup); an **existing** store is verified strictly **read-only** (`mode=ro`
/ `PRAGMA query_only=ON`) and is never re-initialized, migrated, repaired, truncated or replaced — a
failed integrity check never triggers schema creation. The live DB and the verified backup are opened
read-only; the corrupt/restore test runs only on a temporary copy (both `integrity_check` and
`foreign_key_check`), and all temporary artifacts are removed afterward.

## What the verifier proves (sanitized — no contents, IDs, counts, secrets, or bytes)
`verify_decision_journal_setup.py <expected_service_user>` (deployed to the box) checks and prints
PASS/FAIL for:
- running as the **expected service user** (passed in and compared) and **non-root**;
- `DECISION_JOURNAL_DB_PATH` resolves **outside** the deploy checkout (realpath + `commonpath`,
  symlink/sibling-prefix safe);
- directory mode **0700**, DB file mode **0600**, **backup dir 0700**, **backup file 0600** (Linux);
- **schema version** correct;
- **`foreign_keys=ON`, `journal_mode=WAL`, `synchronous=FULL`**;
- **`integrity_check=ok`** and **`foreign_key_check` returns no rows** (+ orphan/invariant checks);
- the **new store is empty** (tickets/legs/revisions — asserted, count never printed);
- **`DECISION_JOURNAL_ENABLED` is OFF** and the **journal routes return 404 while dark**;
- a **consistent backup** via the same Python routine (`dj.backup`) that **opens + passes both integrity
  checks**;
- **corruption is detected and restore recovers** a healthy store — tested **only on a temporary copy**,
  never the live DB.

### Local proof (Windows dev; mechanics only — Linux asserts the perm bits)
```
[PASS] running as the expected service user (<svc>)
[PASS] DECISION_JOURNAL_DB_PATH resolves outside the checkout
[PASS] empty database initializes cleanly
[PASS] schema version is 1
[PASS] foreign_keys=ON
[PASS] journal_mode=WAL
[PASS] synchronous=FULL
[PASS] integrity_check=ok
[PASS] foreign_key_check returns no rows
[PASS] orphan / invariant checks clean
[PASS] new store is empty (tickets/legs/revisions)
[PASS] DECISION_JOURNAL_ENABLED is OFF
[PASS] journal routes return 404 while dark
[PASS] backup created via dj.backup, opens, passes both integrity checks
[PASS] corruption detected and restore recovers a healthy store (temp copy only)
DARK SETUP VERIFIED — ready for dark operation (routes still disabled).
```
(On Linux the run also asserts dir 0700 / file 0600 / backup dir 0700 / backup file 0600 and non-root;
those show as POSIX NOTEs on the Windows dev box.)

---

## Production procedure (run in the AWS SSM console, us-east-1 → Session Manager)
Run as `ssm-user` (passwordless sudo). First deploy so the verifier is on the box
(`git push origin master` → bk-deploy auto-pulls within ~2 min; confirm with
`journalctl -u bk-deploy.service -n 20 --no-pager`). Then:

```bash
cd /opt/bankrollkings

# identify the service user and the interpreter the service actually uses
SVC=$(systemctl show -p User --value bankrollkings); SVC=${SVC:-ubuntu}; echo "service user: $SVC"
PY=$(systemctl show -p ExecStart --value bankrollkings | grep -oE '/[^ ]*/bin/(python3?|gunicorn)' | head -1)
PY=${PY%/gunicorn}/python3; [ -x "$PY" ] || PY=$(command -v python3); echo "interpreter: $PY"
DBP=/var/lib/bankrollkings/decision_journal/journal.db

# 1. private directory OUTSIDE the checkout, owned by the service user, 0700
sudo install -d -o "$SVC" -g "$SVC" -m 700 /var/lib/bankrollkings/decision_journal

# 2. set ONLY the DB path; keep the flag OFF (never add DECISION_JOURNAL_ENABLED=1 here).
#    READ/EDIT .env AS THE SERVICE USER: .env is 0600/$SVC, so a bare `grep` runs as ssm-user and fails
#    "Permission denied" -- that silently defeats the idempotency guard and risks a DUPLICATE key
#    (duplicate env assignments resolve unpredictably). Append via `sudo -u "$SVC" tee` so the file stays
#    owned by $SVC, then ASSERT exactly one assignment exists.
sudo -u "$SVC" grep -q '^DECISION_JOURNAL_DB_PATH=' /opt/bankrollkings/.env \
  || echo "DECISION_JOURNAL_DB_PATH=$DBP" | sudo -u "$SVC" tee -a /opt/bankrollkings/.env >/dev/null
n=$(sudo -u "$SVC" grep -c '^DECISION_JOURNAL_DB_PATH=' /opt/bankrollkings/.env); \
  [ "$n" -eq 1 ] && echo "DB path assignment count OK (exactly 1)" \
                 || echo "ERROR: $n DECISION_JOURNAL_DB_PATH lines present -- dedupe to one before continuing"
sudo -u "$SVC" grep -q '^DECISION_JOURNAL_ENABLED=' /opt/bankrollkings/.env \
  && echo "WARNING: DECISION_JOURNAL_ENABLED present -- ensure it is 0" || echo "flag unset -> OFF (correct)"

# 3. restart the service so it reads the new env
sudo systemctl restart bankrollkings

# 4. initialize the empty database AS THE SERVICE USER
sudo -u "$SVC" env DECISION_JOURNAL_DB_PATH="$DBP" "$PY" \
  -c "import services.decision_journal as dj; dj.init_db(); print('init ok')"

# 5. run the verifier AS THE SERVICE USER, passing the expected user so the match is asserted
sudo -u "$SVC" env DECISION_JOURNAL_DB_PATH="$DBP" "$PY" verify_decision_journal_setup.py "$SVC"

# 6. create + keep a named first backup via the SAME Python routine the verifier uses
#    (dj.backup: VACUUM INTO + chmod 0600 + both integrity checks). No fragile shell sqlite3.
FIRST="/var/lib/bankrollkings/decision_journal/backups/first_$(date -u +%Y%m%dT%H%M%SZ).db"
sudo -u "$SVC" env DBP="$DBP" FIRST="$FIRST" "$PY" -c \
  "import os,services.decision_journal as dj; ok=dj.backup(os.environ['DBP'],os.environ['FIRST']); print('first backup OK' if ok else 'FIRST BACKUP FAILED')"

# 7. copy ONLY the sanitized verifier PASS/FAIL report back for the record.
```

Notes:
- The verifier imports `app` to confirm the routes are 404, so step 5 must use the **app venv
  interpreter** (`$PY`), not a bare system python that lacks the app's dependencies.
- If step 5 shows any FAIL, stop — do not enable anything. Fix the flagged item (usually ownership/mode
  or the path still being inside the checkout) and re-run.
- After a passing report: the next authorized steps (separate) are the recurring backup timer
  (`ops/bk-decision-journal-backup.*`, 30 daily / 12 monthly via SSM), then a limited single-account
  test, then — only later — `DECISION_JOURNAL_ENABLED=1`.
