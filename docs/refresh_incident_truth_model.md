# Refresh incident — monitoring truth model (Oct 2026)

Why the Oct 23–24 refresh incident looked fine in every dashboard while NFL/NCAAF/NBA/MLB
player props sat days stale and CFBD was quota-exhausted — and what now makes the monitoring
tell the truth. Companion to `docs/containment_matrix.md` (which covers the *render* side:
never show a stale current line as live). This doc covers the *supervisory* side: never
report PASS / GREEN when a required feed did not advance.

> **Standing rule (directive #10): never override the row-collapse / empty-slice validator to
> publish an empty file.** An empty or collapsed fetch *preserving last-known-good is correct
> behavior*, not a bug to route around. The bug is always in how that outcome is *reported*.

---

## 1. What was actually true on 2026-10-24

| Feed | State | Honest label |
|---|---|---|
| Game lines (all sports) | fresh | UPDATED |
| WNBA props | fresh | UPDATED |
| NFL / NCAAF / NBA / MLB props | **stale** | needs classification (below) |
| Futures | fresh after recovery | UPDATED |
| CFBD (college data) | **monthly quota exhausted (429)** | SKIP — PROVIDER_QUOTA_EXHAUSTED |
| Odds API account | healthy (upgraded to 100k; ~98,960 remaining) | — |

Two independent external conditions (Odds credit exhaustion, since topped up; and the CFBD
monthly 429), **not** a cascade. The prod operator runs `--continue-on-error`, so the CFBD
outage did not stop the Odds-side refreshes.

## 2. The NBA "9 responses, 0 rows, 0 cost" diagnosis (directive #9)

**Determination: `NO_MARKETS_POSTED`. Not a bug. Do not "fix" it by weakening the validator.**

Trace (`refresh_nba_daily.py` → `fetch_player_props.py`):

1. `refresh_nba_daily.py` runs `player_props` = `fetch_player_props.py --sport basketball_nba --days 5`.
   NBA regular season opens ~late Oct 2026, so early games now fall inside the 5-day window →
   `fetch_events` returned **9 events**.
2. For each event, `fetch_event_props` hit `/v4/sports/basketball_nba/events/{id}/odds`. The books
   had **not posted player-prop markets** for those early games yet → each response carried none of
   the requested markets → `Loaded 0 rows` ×9. The Odds API does **not bill** an `/odds` call that
   returns none of the requested markets → **cost 0** (consistent with the QUOTA RECEIPT).
3. `all_rows` empty → `build_dataframe` empty. `error_count == 0`, so the early
   `if error_count and df.empty:` guard (line ~608) did **not** fire; flow continued.
4. Strong validation (`services/feed_validation.py`, `PLAYER_PROPS_SPEC`, `min_rows=1`) correctly
   rejected the empty slice → `"Strong validation FAILED, preserving existing props CSV"` → **return 1**.
   (Prior file preserved — the right call.)
5. `player_props` is a **blocking** step in `refresh_nba_daily.py` (only `runtime_snapshots` is
   non-blocking), so that exit-1 **aborted the entire NBA chain** — injuries, officiating,
   calibration, board QC never ran — and surfaced to the operator as **`[FAIL] NBA daily refresh`**.

So NBA spent ~0 credits, produced 0 rows, and preserved last-known-good. The failure the operator
reported was **a real exit code from a legitimate `NO_MARKETS_POSTED`** — a monitoring-vocabulary
gap, not a pipeline break.

**Confirm on prod (zero extra spend):**
```bash
cd /opt/bankrollkings && sudo -u ubuntu python3 report_feed_availability.py --sports nba
```
`NBA verdict=PROBE_JUSTIFIED` with `events_next_2d > 0` ⇒ games are scheduled but props not yet
posted ⇒ the 0-row result was `NO_MARKETS_POSTED`, and a narrow re-probe later (once books post) is
the only action — nothing to fix in code.

## 3. Why every dashboard read healthy — the defects

| # | Surface | Defect | Fix (this change) |
|---|---|---|---|
| 1 | `qc_odds_feed.py` | one blanket "odds feed healthy"; only tracked NFL/NCAAF game lines + futures | **Per-family report**: game lines + props **per sport**, futures, grading. Truth rule: game lines FRESH but props STALE ⇒ FAIL (props pipeline broken or no markets). |
| 5 | `generate_run_status.py` | aged 14 analysis artifacts only; never looked at Odds feeds or operator outcomes ⇒ GREEN during the incident | Folds in the Odds **families** + a structured operator summary; new **DEGRADED** state (severity ladder `RED > DEGRADED > WATCH > GREEN`). |
| 2 | `run_daily.py` | free-text log only; nothing machine-readable for Run Status / diag to trust | Writes `data/tracking/Last_Operator_Summary.json` (per-step status, blocking failures, provider-exhausted steps). Additive — control flow unchanged. |
| 6 | `refresh_cfb_data.py` / operator | CFBD 429 / "key not set" → exit 0 → PASS | `.env` now loaded in the QC/CFBD/operator (833c417); 429 short-circuits to exit 3 + `PROVIDER_QUOTA_EXHAUSTED`; operator maps that to `SKIP (PROVIDER_QUOTA_EXHAUSTED)` (not PASS, not FAIL); Run Status → DEGRADED. |
| — | paid-fetch decision | "feeds stale → refetch everything" burned credits on sports with no events | New **`report_feed_availability.py`** (zero-network): PROBE_JUSTIFIED / NO_FETCH / FRESH / NO_SCHEDULE per sport. |

QCs: `qc_odds_feed` (manual), `qc_run_status_degraded.py`, `qc_feed_availability.py`,
`qc_freshness_contract.py` (registered in `run_all_scorecards.py`).

### 3a. One declared freshness contract (directive #1)

The incident also exposed a *contradiction between monitoring tools*: the availability report called
39–40h NFL/NCAAF props STALE (`>6h`) while `qc_odds_feed` called the same files FRESH (`<40h`). Two
hand-picked thresholds, opposite verdicts on one file. Resolved by a single declared source,
`services/freshness_contract.py`, with **two labeled clocks** (they answer different questions, so they
may differ for one feed — but no two tools answering the *same* question may differ):

| Clock | Reads | Window | Question | Used by |
|---|---|---|---|---|
| **A — render / live-market** | the feed's own `LastUpdated` timestamp | `LIVE_MARKET_MAX_AGE_HOURS = 6h` | is this current price fresh enough to show as live? | `app.py` `get_props_refresh_meta` / `get_lines_refresh_meta` / board fail-closed gates |
| **B — refresh cadence** | file mtime | `refresh_cadence_hours(family,sport)` = 30h props/lines/futures, 54h grading | did the daily job advance this artifact? | `qc_odds_feed`, `generate_run_status`, `report_feed_availability` |

30h = one ~24h daily-operator cycle + 6h margin (the window Run Status already uses for daily
artifacts); it does not flap under healthy daily operation and flags a *missed* cycle (the NFL/NCAAF
39h case — correctly STALE, not a legitimate slower feed). No sport has a longer cadence today;
`REFRESH_CADENCE_OVERRIDES` is the one place to declare one, with a rationale, if that ever changes.
`qc_freshness_contract.py` proves all three monitoring surfaces agree a 39h props file is STALE.

## 4. The per-sport outcome vocabulary

The honest states a props/line refresh can end in — what the operator/Run Status should record
instead of a binary PASS/FAIL:

| Outcome | Meaning | Alert? |
|---|---|---|
| `UPDATED` | artifact advanced with new rows | no |
| `NO_ACTIVE_EVENTS` | no events in the fetch window (off-season / between slates) | no |
| `NO_MARKETS_POSTED` | events exist, books have not posted the markets yet (the NBA case) | no |
| `VALIDATION_FAILED` | fetch produced rows but they failed semantic validation; prior preserved | **yes** |
| `PROVIDER_ERROR` | the provider errored / timed out | **yes** |
| `PROVIDER_QUOTA_EXHAUSTED` | documented external quota outage with backoff (CFBD 429) | watch (DEGRADED, not FAIL) |
| `STALE` | artifact did not advance and none of the benign reasons above apply | **yes** |
| `SKIP` | deliberately not run (season gate, missing-key guard) | no |

`NO_MARKETS_POSTED` vs `STALE` is decided by the availability signal in §5: events scheduled +
books-not-yet-posting = `NO_MARKETS_POSTED`; events scheduled + markets that *should* be up but the
file did not advance = `STALE` (a real break).

## 5. Operating procedure before any paid fetch (directive: "do not run another paid fetch yet")

1. **Availability gate (free):**
   ```bash
   cd /opt/bankrollkings && sudo -u ubuntu python3 report_feed_availability.py
   ```
   Act only on sports it prints under **PAID PROBE JUSTIFIED**. `NO_FETCH` / `FRESH` → do not spend.
   `NO_SCHEDULE` → refresh the (free) schedule feed first.
2. **Confirm the monitoring now tells the truth (free):**
   ```bash
   sudo -u ubuntu python3 qc_odds_feed.py        # per-family; FAILs on stale active-sport props
   sudo -u ubuntu python3 generate_run_status.py  # overall should read DEGRADED, not GREEN
   ```
3. **Narrow paid probe — one sport at a time**, only for a `PROBE_JUSTIFIED` sport, through the
   receipt wrapper (`recover_odds_fetch.py`) so the cost is proven from usage headers and
   last-known-good is preserved on any validation failure. A `NO_MARKETS_POSTED` result at 0 cost is
   a complete, correct answer — not a reason to re-run.

## 6. Write-side aggregation + the NBA proof (directives #2/#3) — BUILT

- **Response-shape receipt (directive #2):** `fetch_player_props.py` now writes a SANITIZED receipt
  `data/tracking/_last_props_fetch_<slug>.json` (market keys + counts only — never prices/names) with
  `events_found`, `rows_fetched`, `provider_error_count`, `markets_present_anywhere`, and
  `shape_proves_no_markets_posted`. The proof requires events in window, zero provider errors, zero
  rows, and NOT ONE requested market present on ANY event's response. Zero rows / zero cost alone never
  prove it.
- **Outcome classifier (directive #3):** `services/run_outcomes.py` maps a child to the §4 vocabulary
  from (exit code, artifact advanced, receipt). Key rule: zero rows is **VALIDATION_FAILED** unless the
  receipt proves NO_MARKETS_POSTED.
- **Football parent:** `refresh_football_props.py` aggregates its two children and PASSes only when both
  are benign; a non-advancing artifact without proof degrades it (non-zero) — even though the child
  exits 1 in BOTH the benign and failing cases (the exit code alone cannot tell them apart; the receipt
  can).
- **NBA parent:** `refresh_nba_daily.py` no longer aborts the whole chain when props are unavailable —
  it classifies props from the receipt, continues the safe work (injuries / officiating / calibration /
  QC), and leaves the run DEGRADED (non-zero) only on a non-benign props outcome. This is the direct fix
  for the incident's "NBA daily FAIL aborted injuries+calibration on a benign empty slate."

QCs: `qc_run_outcomes.py`, `qc_football_props_aggregation.py` (both registered).

> Until a prod run produces the receipt, the NBA props outcome is **VALIDATION_FAILED** (the
> conservative default), NOT NO_MARKETS_POSTED — the classifier will only call it NO_MARKETS_POSTED once
> a receipt proves it.

## 7. Quota reconciliation (directive #4/#8) — BUILT

- **Append-only ledger:** `services/odds_quota.py` `QuotaRecorder.write_ledger(...)` appends one line per
  paid call (cumulative `x-requests-used`/`-remaining` + sport + endpoint family) to
  `data/tracking/odds_quota_ledger.jsonl`. Wired into the three fetchers (`fetch_game_lines`,
  `fetch_player_props`, `fetch_futures_odds`) via `print_receipt(..., ledger_base_dir=BASE_DIR)`.
- **Reconciler:** `reconcile_odds_quota.py` attributes the account delta by sport + endpoint family from
  the ORDERED cumulative `remaining` drops — correct even when `x-requests-last` is 0/absent (the NBA
  probe). It **FAILS** when any portion is unattributed: a ledger call missing its `remaining` header, a
  non-monotonic counter, or a tail of spend below the ledger's last reading (calls the ledger never saw).
- **Historical window:** for the incident's `100000 → 98960` (1,040 credits) there was no ledger, so the
  reconciler honestly reports **1,040 unattributed → FAIL**. That is the correct answer — full
  attribution begins now that the ledger records every paid call. Run with the owner-read endpoints:
  `python reconcile_odds_quota.py --baseline-remaining <start> --final-remaining <end>`.

QC: `qc_quota_reconciliation.py` (registered).

## 8. CFBD isolation (directive #5) — in force
CFBD stays isolated and honest: `refresh_cfb_data.py` short-circuits a 429 to exit 3 +
`PROVIDER_QUOTA_EXHAUSTED` with a persistent backoff (does not call CFBD again until reset/override),
preserves last-known-good CFB artifacts, and the operator records `SKIP (PROVIDER_QUOTA_EXHAUSTED)` (not
PASS, not FAIL); Run Status reflects it as DEGRADED. CFB current-market surfaces fail closed per
`docs/containment_matrix.md`. QC: `qc_cfb_quota_shortcircuit.py`.
