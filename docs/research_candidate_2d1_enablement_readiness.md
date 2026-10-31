# Research Candidate 2D1 — ON-State Enablement Readiness Audit + Execution Plan (READ-ONLY)

**Status: AUDIT + PLANNING ONLY. No config/dir/DB/unit/flag/write was created or changed.** All measurements
below were taken read-only on prod (`i-08d2fd818875381dd`) via SSM on 2026-10-31 (`host_utc≈20:57Z`), against
the deployed, OFF, scoped release `628657b`. The deployed code is byte-identical to the gate-tested and
OFF-verified release.

## VERDICT: NOT READY — BLOCKED. Do not enable.

A read-only adapter **dry-run over the current live board** proves **0 of 429** future player+event selections
are capturable right now:

| Readiness dimension | Result |
|---|---|
| Props artifact schema (`Player, EventId, EventCommenceAtUTC, SourceUpdatedAtUTC`) | ✅ all 4 present |
| Props freshness (CLOCK-B 30h) | ✅ age 7h |
| Props future-kickoff selections available | ✅ 429 distinct `(Player, EventId)` pairs |
| Roster schema (`player_id, player_display_name, season`) | ✅ present; season all int `2026` |
| **Roster identity completeness** | ❌ **8 null `player_id` + 8 null `player_display_name` rows** |
| Owner `UserId` unique + nonblank | ✅ `OWNER_USERID_OK=True` (not exposed) |
| Service env source | ✅ `EnvironmentFile=/opt/bankrollkings/.env`, `User=ubuntu` |
| State-root writable by service user | ⚠️ **NO** — `/var/lib/bankrollkings` is `root:root 755` |
| **Adapter dry-run: RESOLVED_capturable** | ❌ **0 / 429** — `{ROSTER_SCHEMA_INVALID: 429}` |

### Exact blockers (must clear BEFORE any enablement)

1. **[BLOCKING] Roster artifact has null-identity rows.** `data/tracking/_nflverse_stats_2026.parquet`
   contains **8 rows with a null `player_id` and 8 with a null `player_display_name`**. The adapter
   (`services/nfl_identity_event_adapter.py`, lines ~170–173) **fails closed on the entire roster** if *any*
   identity cell is null — deliberately, because silently dropping a row could conceal a name→id collision.
   Result: **every** `resolve()` returns `ROSTER_SCHEMA_INVALID`, so **no observation can be captured**.
   - **This is a DATA/ARTIFACT blocker, not a code bug.** The adapter's fail-closed behavior is correct and
     must not be weakened. The fix is an **identity-complete** 2026 roster artifact at the `ROSTER` path.
   - **Resolution options (owner decision, each a governed producer change — NOT done here):**
     (a) point `BK_RESEARCH_CANDIDATE_ROSTER` at a roster artifact whose `player_id`/`player_display_name` are
     complete (e.g. a governed nflverse *rosters* snapshot, or a curated filter of the weekly-stats parquet
     that drops only genuine non-player/aggregate rows, produced by a named job — not ad hoc); or
     (b) accept that enablement waits until the upstream roster is identity-complete.
     After the fix, re-run the dry-run (§ Verification) — it must report `RESOLVED_capturable ≥ 1` (feasibility
     measured ~92% of rows resolvable once identities are complete).
2. **[PROVISIONING] State root not writable by `ubuntu`.** `/var/lib/bankrollkings` is `root:root 755`, so the
   service user (`ubuntu`) cannot create `…/research_candidate`. The boundary's `_ensure_secure_dir` runs as
   `ubuntu` and would fail. The dir must be **pre-created by root, chowned `ubuntu:ubuntu`, chmod 0700**
   (exactly how `/var/lib/bankrollkings/decision_journal` already exists: `drwx------ ubuntu ubuntu`).

Until blocker 1 is cleared and re-verified, the ON-state pilot cannot capture anything, so enablement is not
authorized to proceed. Everything below is the exact plan for the later, separately-approved run.

---

## 1. Required `BK_RESEARCH_CANDIDATE_*` environment variables (exact values / sources)

Set in `/opt/bankrollkings/.env` (the service `EnvironmentFile`, mode 600, owner `ubuntu`). Five variables
(names are authoritative in `services/research_candidate_boundary.py`):

| Variable | Proposed value | Source / rationale |
|---|---|---|
| `BK_RESEARCH_CANDIDATE_ENABLED` | `1` | The ONLY on-switch. Absent/`0` ⇒ route 404s, nothing imported. |
| `BK_RESEARCH_CANDIDATE_ROOT` | `/var/lib/bankrollkings/research_candidate` | Approved absolute containment root (own env var). |
| `BK_RESEARCH_CANDIDATE_DB_PATH` | `/var/lib/bankrollkings/research_candidate/store.db` | Absolute; MUST resolve under ROOT (realpath+commonpath). |
| `BK_RESEARCH_CANDIDATE_PROPS` | `/opt/bankrollkings/data/props/NFL_Props.csv` | Live props board; verified schema + 7h fresh + 429 future pairs. |
| `BK_RESEARCH_CANDIDATE_ROSTER` | **identity-complete 2026 roster parquet** (see blocker 1) | NOT the current `_nflverse_stats_2026.parquet` until null-identity rows are removed. |

No `SECRET_KEY`/other new secret is required (already present for the service).

## 2. Approved root/DB paths — containment + permissions

- `ROOT = /var/lib/bankrollkings/research_candidate` ; `DB = ROOT/store.db`. `realpath(DB)` is under
  `realpath(ROOT)` ⇒ containment holds; a relative/out-of-root/symlink-escape path fails closed.
- **Permissions enforced by the boundary on POSIX (fatal on failure):** the DB's containing dir **0700**;
  the DB file and every present WAL sidecar (`-wal`, `-shm`) **0600**, chmod'd and individually re-verified
  after the write (a post-commit permission failure returns 503, never a false success).
- **Pre-provisioning (root, one-time):** `install -d -o ubuntu -g ubuntu -m 700 /var/lib/bankrollkings/research_candidate`
  (because `/var/lib/bankrollkings` itself is root-owned 755). Disk: `/var/lib` has ~12 GB free — ample for a
  tiny SQLite store.

## 3. Live artifacts the adapter reads (schema / season / freshness / permissions)

- **Props — `/opt/bankrollkings/data/props/NFL_Props.csv`** (size ~475 KB, mode 600 `ubuntu`, mtime 2026-10-31
  13:00Z, age 7h). Columns include all four required: `Player, EventId, EventCommenceAtUTC,
  SourceUpdatedAtUTC` (plus pricing columns). Read once (bytes+sha256+mtime from one fd, no TOCTOU). Staleness
  = CLOCK-B `refresh_cadence_hours("props","NFL") = 30h`; **7h ⇒ FRESH**. 429 distinct future-kickoff
  `(Player, EventId)` pairs available as selections.
- **Roster — `/opt/bankrollkings/data/tracking/_nflverse_stats_2026.parquet`** (size ~414 KB, mode 600
  `ubuntu`, mtime 2026-10-31 13:04Z). Has `player_id, player_display_name, season`; **season is all integer
  `2026`** (== governed current season). **Identity completeness FAILS: 8 null `player_id` + 8 null
  `player_display_name`** ⇒ adapter fails closed (blocker 1). Must be replaced with an identity-complete
  artifact before enablement.
- Both artifacts are readable by `ubuntu` (the service user) ✓.

## 4. Owner `UserId` resolves uniquely (not exposed)

Confirmed read-only (count-only, no id printed): `owner_emails_count=1`, `owner_rows=1`,
`owner_blank_userid=0`, `global_nonblank_dup_userid=0` ⇒ **`OWNER_USERID_OK=True`**. The observer is
`get_current_user()['user_id']` = the owner's `UserId` in `data/tracking/NBA_Users.csv`, set server-side from
the session account — never from email or payload. The store rejects a blank/duplicate identity rather than
synthesizing one.

## 5. Exact service configuration change + restart

1. (root) pre-create the store dir (§2 provisioning line).
2. (owner, as `ubuntu`) append the five `BK_RESEARCH_CANDIDATE_*` lines (§1) to `/opt/bankrollkings/.env`
   (keep mode 600). Do **not** edit the unit file.
3. `sudo systemctl restart bankrollkings` — **restart, not reload** (`preload_app=True`; a HUP would keep the
   old env/code).
4. Confirm `systemctl is-active bankrollkings` = active and the env is present:
   `systemctl show bankrollkings -p Environment | tr ' ' '\n' | grep BK_RESEARCH_CANDIDATE` (5 lines).

## 6. First-capture procedure (a real owner observation, no fabrication)

1. Owner signs in (session `user_id` = owner `UserId`).
2. Owner picks **one real selection from the current live board**: a `(Player, EventId)` with a **future**
   kickoff that the adapter **resolves** (after blocker 1 is cleared). No synthetic player/event.
3. Owner writes a **genuine thesis in their own words** (the system never generates a thesis).
4. Authenticated `POST /research-candidate/observe` with JSON `{player_ref, event_id, thesis,
   idempotency_key (owner-chosen opaque token), acted:false, sources:[…owner URLs…]}`; CSRF token required;
   body ≤ 8192 bytes; strict types.
5. The governed adapter resolves identity+event+evidence; the store writes exactly one immutable observation.
   The response is `{ok:true, status:"recorded", id:…}`.

## 7. Verification after the first capture

Read-only against the store (open `create=False`, mode=ro) + the service:
- **Exactly one observation:** `observation_private` row count == 1; it has a `record_registry` binding and a
  claimed `seq_reservation`.
- **Correct provenance:** stored `sources` = owner sources ∪ the resolver's reserved `bkres:` evidence refs;
  `replay_validate()` re-verifies the content hash and ledger order (fails closed on any mismatch).
- **Idempotent retry:** re-POST with the **same** `idempotency_key` and identical intent ⇒ `status:"noop"`,
  **no new row**; a reused key with a *different* fingerprint ⇒ 409 (fail closed).
- **No downstream records:** `research_candidate`, `candidate_outcome`, `evaluated_finding` all **empty**
  (2D1 captures observations only — no freeze/outcome/finding).
- **Sanitized logs:** `research_candidate op=observe corr=… status=… code=…` only — no thesis/identity/email.
- **Service healthy:** `systemctl is-active` active; warm responses normal.

## 8. Backup sequencing (existing-only, after first capture)

- The operator entry point is `ResearchCandidateStore.backup_existing(src, dest)`: it opens the source
  **read-only (`create=False`)** and **fails closed if the store does not exist** — it **never initializes**
  one. So a backup **can only run AFTER the first capture** created `store.db`.
- Order: first capture → `store.db` exists → `backup_existing(store.db, store.db.bak-<utc>)` → `VACUUM INTO`
  consistent snapshot → full `validate_store` (schema+integrity+fk+replay) → fsync → 0600 → **atomic
  create-if-absent hard-link publish (never overwrites)**.
- A backup attempted **before** first capture correctly refuses (no store) — that is the intended guard, not
  an error to work around.
- A scheduled `bk-research-candidate-backup.{service,timer}` (like the decision-journal backup) is a
  **separate later step**, explicitly **out of this phase**.

## 9. Rollback (immediate OFF, preserve data)

1. Remove (or set `0`) `BK_RESEARCH_CANDIDATE_ENABLED` in `/opt/bankrollkings/.env`.
2. `sudo systemctl restart bankrollkings`.
3. Confirm return to the verified OFF state: the route 404s and **no** RC module is imported — reuse the
   OFF-state import proof (flag unset ⇒ `rc_modules_imported = []`). Envs for paths may remain or be removed;
   with `ENABLED` off the feature is inert regardless.
4. **Preserve** `store.db`, its WAL sidecars, and all `store.db.bak-*` backups — do **not** delete. They live
   under `/var/lib/bankrollkings/research_candidate`, outside the git checkout, and are untouched by deploys.
   (Deletion/erasure is deliberately unimplemented.)

## 10. Single execution script + mandatory stop points

The later authorized run is one wrapper with **two approval stop points**; the actual capture is performed by
the owner in the authenticated app (a real human observation), never scripted:

```
# ===== STOP 1 — requires owner approval BEFORE any configuration =====
#   Precondition: blocker 1 cleared — an identity-complete 2026 roster artifact exists at $ROSTER,
#   and a re-run of the §Verification dry-run reports RESOLVED_capturable >= 1.
# (root)  install -d -o ubuntu -g ubuntu -m 700 /var/lib/bankrollkings/research_candidate
# (ubuntu) append the 5 BK_RESEARCH_CANDIDATE_* lines to /opt/bankrollkings/.env   (mode stays 600)
# (root)  systemctl restart bankrollkings
#         systemctl is-active bankrollkings ; confirm 5 env lines present
# ===== STOP 2 — requires owner approval BEFORE the first write =====
#   Owner selects ONE real future board observation and writes a genuine thesis, then performs the
#   authenticated POST /research-candidate/observe themselves.
# Then: run the §7 verification (one observation, provenance, idempotent retry, no downstream rows,
#       sanitized logs, healthy service), then backup_existing (§8).
```

I will prepare that script as a single copy-paste block **only after blocker 1 is cleared and re-verified and
the ON-state pilot is explicitly authorized** — not in this audit phase.

---

**This phase changed nothing on prod.** No env var set, no directory/DB created, no unit installed, no restart,
no flag flip, no observation written. Enabling capture remains a separate, explicit, currently-BLOCKED
decision.
