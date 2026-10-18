#!/usr/bin/env bash
# Bankroll Kings - Decision Journal recurring backup (runs while the Journal is DARK + the store empty).
#
# WHAT: a daily consistent snapshot (VACUUM INTO) of the private Journal DB plus a monthly snapshot,
# pruned to retention (30 daily / 12 monthly). It uses services.decision_journal.run_scheduled_backup,
# which calls the SAME dj.backup routine the verifier uses (0600 + both integrity checks) -- no fragile
# shell sqlite3. It is a PURE READ of the live DB (VACUUM INTO), never a writer, so it is safe to run
# while the feature flag is off and there are no routes.
#
# Installed OUTSIDE the repo so a mid-run `git pull` (bk-deploy) cannot rewrite the executing script --
# same rationale as bk-auto-deploy.sh. Source of record: ops/bk-decision-journal-backup.sh
#   sudo install -m 755 ops/bk-decision-journal-backup.sh /usr/local/bin/bk-decision-journal-backup.sh
set -uo pipefail

APP=/opt/bankrollkings
PY="$APP/venv/bin/python"
cd "$APP" || exit 0

# No overlapping runs (a slow VACUUM must not race the next tick).
exec 9>/var/lock/bk-dj-backup.lock || exit 0
flock -n 9 || exit 0

# DECISION_JOURNAL_DB_PATH comes from the unit's EnvironmentFile (/opt/bankrollkings/.env). The driver
# no-ops cleanly when the DB does not exist yet. Prints only sanitized counts (never contents).
"$PY" -c "import json, services.decision_journal as dj; print(json.dumps(dj.run_scheduled_backup()))"
