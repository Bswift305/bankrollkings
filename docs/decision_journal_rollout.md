# Decision Journal V1 — Rollout Readiness

Ships **dark**: `DECISION_JOURNAL_ENABLED` defaults OFF, so `/journal*` return 404 until the flag is
set. Nothing is user-visible on deploy. Built to `docs/decision_journal_implementation_design.md`
(design rev 3). All 15 acceptance checks pass (`qc_decision_journal.py`, registered in
`run_all_scorecards.py`).

## Pieces
- `services/decision_journal.py` — storage + `JournalRepository` (the single access boundary). Stdlib
  `sqlite3`, WAL, `synchronous=FULL`. No Flask import.
- `app.py` — `/journal`, `/journal/new`, `/journal/<id>/settle`, `/journal/report`, all flag-gated,
  login-gated, CSRF-protected, and catching `JournalUnavailable` → "temporarily unavailable" page.
- `templates/decision_journal/` — list / entry / settle / report / unavailable.
- `qc_decision_journal.py` — the frozen acceptance suite.

## Config (prod, via SSM — nothing auto-created)
1. Create the private store dir **outside** the checkout, owned by the app user, restricted:
   ```bash
   sudo install -d -o www-data -g www-data -m 700 /var/lib/bankrollkings/decision_journal
   ```
   (use the actual service user; the app sets the DB file to `0600` on first init.)
2. Set env for the service (systemd drop-in or the app's env file):
   ```
   DECISION_JOURNAL_DB_PATH=/var/lib/bankrollkings/decision_journal/journal.db
   DECISION_JOURNAL_ENABLED=0      # keep OFF until verified
   ```
3. Deploy normally (`git push origin master` → auto-pull + restart). With the flag off, the feature is
   inert. The DB is created lazily on first journal request (after the flag flips).

## Enable + verify
1. Flip `DECISION_JOURNAL_ENABLED=1`, `sudo systemctl restart bankrollkings`.
2. Signed in, open `/journal`, log one prospective decision, grade it, open `/journal/report`.
3. Take a first snapshot immediately: `sqlite3 journal.db "VACUUM INTO '…/backups/journal_<ts>.db'"`.

## Backups / integrity (freeze: 30 daily, 12 monthly)
- A `bk-*` systemd timer runs `VACUUM INTO` daily (retain 30) + monthly (retain 12) into a private
  backup dir. Install via SSM like the other `bk-*` units (not auto-created).
- `integrity_check` + `foreign_key_check` run on first open and after each snapshot; failure disables
  journal writes (banner) and alerts — it never takes down other pages.

## Rollback (zero data loss to the existing tracker)
- **Instant:** set `DECISION_JOURNAL_ENABLED=0` + restart → feature invisible.
- **Full:** `git revert <implementation commit>` + restart. The DB is additive and migration is
  non-destructive (the JSON Bet Tracker is never modified), so reverting loses nothing from the
  existing tracker. The `journal.db` file can be left inert or archived.

## Migration (optional, when authorized)
`JournalRepository.migrate_user_json(user_id, bets)` is reversible and idempotent (straight → one-leg,
parlay → `legacy_flat_ticket` with zero legs; `reverse_migration` removes only migrated rows). Not run
automatically; a later gate decides if/when the tracker is subsumed. Until then both coexist.

## Out of V1 (schema supports; deferred)
Sportsbook import / OCR, model tuning, causal conclusions, near-duplicate UI, and **post-lock
corrections**. The `decision_revisions` table + append-only triggers exist so the base rows stay the
immutable decision-time snapshot, but **no correction write-path is exposed in V1** — applying revision
overlays consistently across `get_ticket` / `list_tickets` / `report` is its own gate, so until then
product reads always return the base rows and a locked record is simply immutable.

## Timezone note
Event-start times come from a tz-free `datetime-local`; the entry page captures the browser's IANA
timezone and its own UTC conversion, and the server converts via `zoneinfo`. A tz-free time is **never**
read as UTC — if the zone can't be determined the entry is refused, not silently shifted.
