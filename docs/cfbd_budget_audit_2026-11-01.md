# CFBD call-budget audit (read-only) — 2026-11-01

Status: **audit + design only.** Latch untouched, `.env` untouched, no CFB fetch, no deploy, master untouched
(`63060a9`). Sequence agreed with the owner: 11-02 RC receipt → CFBD budget correction → controlled latch
release + CFB recovery.

Disclosure: the approved probe (`4f282454`, one CFBD `/conferences` call, 2026-11-01 16:03 UTC, HTTP 200)
also wrote its cooldown timestamp to `logs/.diag_probe_cooldown.json` — operational telemetry, not a governed
data or latch change. All other evidence commands were read-only (`5cb540b5`, CFB log extracts, key
fingerprints).

## 1. Plan allowance and reset boundary

| Fact | Evidence | Confidence |
|---|---|---|
| Monthly quota, 429 body "Monthly call quota exceeded" | `qc_cfb_quota_shortcircuit.py:3,27`; prod 10-22/10-23 sub-steps all `HTTP Error 429` | confirmed |
| Allowance ≈ **1,000 calls/month** | ~43 calls/run × ~21 daily runs ≈ 900 by 10-21, 429 from 10-22 | **inferred** — repo names no tier; confirm in the CFBD account |
| Reset at the calendar-month boundary | blocked 10-22..10-24; probe 200 on 11-01 16:03 UTC; `docs/refresh_incident_2026-10-23.md:82-83` | boundary between 10-24 and 11-01 16:03 confirmed; exact instant **not** confirmed (assume 00:00 UTC on the 1st, verify) |
| CFBD exposes no quota header we read | no `X-CallLimit*` read anywhere in the repo | confirmed (whether CFBD *sends* one is unverified) |
| Prod and dev box use **different keys** | fingerprints `65980f84` (prod) vs `ba6787f3` (dev `.env.local`), sha256 prefix only | confirmed — dev-box tasks do not spend prod quota |

## 2. October consumption

Exact per-date/per-endpoint reconstruction is **not possible**: no CFB script logs its request count, and there
is no CFBD call ledger (only `odds_quota_ledger.jsonl`). Reconstruction from structure:

| Window | Runs | Calls |
|---|---|---|
| 10-01 .. 10-21 | 1 `bk-daily` per day (13:00 UTC) | ≈ 43 each → ≈ 900 |
| 10-22 .. 10-23 | daily | 429 on every CFB sub-step (exhausted) |
| 10-24 | 3 daily-operator logs (incident reruns) | 429 → latch written 13:04:29 UTC |
| 10-25 .. 11-01 | daily | 0 (latched; SKIP) |
| manual/diag | `diag --probe`, `diagnose_cfb_line_coverage.py`, research scripts | unknown — unlogged |

**Finding:** the absence of a CFBD ledger is itself a defect — budget can't be governed if it can't be counted.

## 3. Cost of one complete CFB refresh (`refresh_cfb_data._steps`, season 2026)

≈ **43 requests** (44 with weather enabled; up to 46 with roster/returning fallbacks; roster has 429 retries
×4). Largest items: slate fetcher ≈14 (one `/games` per week incl. past weeks + `/lines` per in-window week),
game-lines history 12 (6 years × 2 season types), player stats 4, totals pace 3.

## 4. Waste

| Waste | Calls/run |
|---|---|
| identical `/lines?year=2026&seasonType=regular` fetched by 6 scripts | 5 redundant |
| `/games?year=2026&seasonType=regular` fetched twice | 1 |
| history refetches finished 2021–2025 seasons every day | 10 |
| player stats refetches finished 2025 season every day | 4 |
| slate fetcher calls `/games` per past week instead of once per season | ≈ 8 |
| roster / returning production / portal / coaches / rankings daily though they change ~weekly | ≈ 4 (on non-change days) |

## 5. Proposed design (for review — not implemented)

**5.1 One shared client `services/cfbd_client.py`** used by every CFB script: per-run memo (same URL+params
served once per run), JSONL ledger `cfbd_call_ledger.jsonl` (ts, script, endpoint, params, status, quota
header if present) under `BK_RUNTIME_DIR`, uniform status classification, no secrets logged.

**5.2 Cadence, honest about freshness:**
- daily: one `/games?year=S` + one `/lines?year=S&seasonType=regular`, shared by all builders; `/lines` for
  in-window weeks only if not already in the season pull.
- weekly (Mon after the slate) or on change: roster, returning production, coaches, rankings (rankings also
  after poll release), portal (in-window only).
- immutable: finished seasons (history 2021–2025, player stats 2025) fetched once, then only on explicit
  backfill.
- Every CFB surface keeps showing its data's real as-of time; a skipped refresh is reported as
  "unchanged since <ts> (scheduled weekly)", never as fresh.

Projected ≈ **9–12 calls/day ≈ 300–370/month**.

**5.3 Budget:** monthly allowance A (confirm; assume 1,000). Reserve 15% for diagnostics/recovery (150).
Operating budget 850 → daily soft cap ≈ 25, hard stop when the ledger shows month-to-date ≥ 850: non-essential
steps SKIP-with-reason; reserve only for probes and a governed recovery run.

**5.4 Monthly-reset latch contract** (replaces "block until an unset env var"):
1. On 429-quota the latch records `detected_at`, `reset_at` = explicit `BK_CFBD_RESET_AT` if configured, else
   the **policy boundary** = next calendar month 00:00 UTC, plus `reset_source` (`configured` | `policy`).
   **`reset_at` is never absent → no indefinite lock.**
2. Before `reset_at`: no CFBD request at all; last-known-good artifacts preserved (fail-closed).
3. At/after `reset_at`: release for **one** probe call; 200 → clear latch and run; 429 → re-latch to the next
   boundary (provider reset later than assumed), recorded.
4. 401/403 → **not** a quota latch: FAIL loudly as auth (key revoked/rotated), no retry storm.
5. Visible status: Run Status reports `PROVIDER_QUOTA_EXHAUSTED (until <reset_at>)`; CFB pages show
   "CFB data as of <date> — provider quota exhausted" instead of silently aging.
6. Operator overrides stay (`BK_CFBD_FORCE=1`, delete file) and are logged in the ledger.

**5.5 Adversarial tests** (`qc_cfbd_budget.py`, synthetic, no network): 200 (counted, ledgered, memo hit on
the repeat call); 401 and 403 (auth FAIL, no latch); 429 (latch with a policy `reset_at`, never None); missing
quota headers (counts locally, never fabricates "remaining"); reset rollover (one second before → blocked and
zero requests; at boundary → exactly one probe; probe 429 → re-latched to the next boundary); exhausted budget
(MTD ≥ operating budget → non-essential SKIP, reserve still allows one probe); memo (6 identical `/lines` calls
→ 1 request); immutable seasons (finished season on disk → 0 requests).

## 6. Recovery procedure (after the 11-02 receipt; each prod step owner-approved)
1. Back up CFB artifacts + latch file (permission-preserving, SHA-256 manifest).
2. Deploy the budget correction (5.1–5.4) via reviewed commit + QC; no master push before the receipt.
3. Correct the latch: set the explicit monthly boundary (or let the new contract compute it).
4. One governed CFB refresh with the ledger on; validate call count ≈ projection, artifacts fresh, schema OK.
5. Rollback: restore artifacts + latch file from the manifest; revert the commit.
