# Decision Journal — Dark-Production Setup Runbook

**Scope:** the Director's scoped scorecard waiver for **dark-production setup only** (the Oct 16 full
scorecard's MLB + Prelaunch FAILs are pre-existing, present Oct 12–15 before the Journal change; the
Journal section itself passes). This runbook creates the private store and proves it healthy **with
routes still disabled**. It does **not** enable the feature.

**Do NOT in this step:** migrate JSON records, create a test ticket, enable routes, or install the
recurring backup timer. Those come only after this dark setup passes and are separately authorized.

The feature flag `DECISION_JOURNAL_ENABLED` stays **OFF** (unset) throughout, so `/journal*` return 404.

---

## What the verifier proves (sanitized — no contents, IDs, counts, secrets, or bytes)
`verify_decision_journal_setup.py` (deployed to the box) checks and prints PASS/FAIL for:
- running as a **non-root** service user (the report prints the user to confirm it's the app account);
- `DECISION_JOURNAL_DB_PATH` resolves **outside** the deploy checkout;
- directory mode **0700**, DB file mode **0600** (asserted on Linux);
- **schema version** correct;
- **`foreign_keys=ON`, `journal_mode=WAL`, `synchronous=FULL`**;
- **`integrity_check=ok`** and **`foreign_key_check` returns no rows** (+ orphan/invariant checks);
- **`DECISION_JOURNAL_ENABLED` is OFF** and the **journal routes return 404 while dark**;
- a **consistent backup** can be created and **opens + passes both integrity checks**;
- **corruption is detected and restore recovers** a healthy store — tested **only on a temporary copy**,
  never the live DB.

### Local proof (Windows dev; mechanics only — Linux asserts the perm bits)
```
[PASS] DECISION_JOURNAL_DB_PATH resolves outside the checkout
[PASS] empty database initializes cleanly
[PASS] schema version is 1
[PASS] foreign_keys=ON
[PASS] journal_mode=WAL
[PASS] synchronous=FULL
[PASS] integrity_check=ok
[PASS] foreign_key_check returns no rows
[PASS] orphan / invariant checks clean
[PASS] DECISION_JOURNAL_ENABLED is OFF
[PASS] journal routes return 404 while dark
[PASS] backup created, opens, passes both integrity checks (rows match live)
[PASS] corruption detected and restore recovers a healthy store (temp copy only)
DARK SETUP VERIFIED — ready for dark operation (routes still disabled).
```

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

# 2. set ONLY the DB path; keep the flag OFF (never add DECISION_JOURNAL_ENABLED=1 here)
grep -q '^DECISION_JOURNAL_DB_PATH=' /opt/bankrollkings/.env \
  || echo "DECISION_JOURNAL_DB_PATH=$DBP" | sudo tee -a /opt/bankrollkings/.env
grep -q '^DECISION_JOURNAL_ENABLED=' /opt/bankrollkings/.env \
  && echo "WARNING: flag present — ensure it is 0" || echo "flag unset -> OFF (correct)"

# 3. restart the service so it reads the new env
sudo systemctl restart bankrollkings

# 4. initialize the empty database AS THE SERVICE USER
sudo -u "$SVC" env DECISION_JOURNAL_DB_PATH="$DBP" "$PY" \
  -c "import services.decision_journal as dj; dj.init_db(); print('init ok')"

# 5. run the verifier AS THE SERVICE USER (flag stays unset in this shell)
sudo -u "$SVC" env DECISION_JOURNAL_DB_PATH="$DBP" "$PY" verify_decision_journal_setup.py

# 6. create + keep a named first backup (the verifier also makes a throwaway one)
sudo -u "$SVC" env DBP="$DBP" bash -c \
  'sqlite3 "$DBP" "VACUUM INTO '"'"'/var/lib/bankrollkings/decision_journal/backups/first_'"$(date -u +%Y%m%dT%H%M%SZ)"'.db'"'"'"'

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
