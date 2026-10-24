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

QCs: `qc_odds_feed` (manual), `qc_run_status_degraded.py`, `qc_feed_availability.py` (both
registered in `run_all_scorecards.py`).

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

## 6. Deliberately deferred (needs prod verification, do not ship blind)

These change the operator's **control flow / exit semantics** and are held for a reviewed, prod-verified
follow-on rather than shipped unverified during an active incident:

- **Parent-step child aggregation (directive #2/#3):** make `refresh_football_props.py` and the sport
  daily refreshes emit the §4 outcome per child (verify the child's target artifact advanced, or the
  child documented NO_ACTIVE_EVENTS / NO_MARKETS_POSTED) and surface it to the operator, so a parent
  never reports a bare PASS when its child artifact did not advance. Today the monitoring-read side
  (qc_odds_feed, Run Status) already refuses the false all-clear; this closes the operator-write side.
  It also means `fetch_player_props.py` should distinguish a `NO_MARKETS_POSTED` exit from a hard
  error, so a blocking parent (e.g. NBA) stops aborting the whole sport on a benign empty slate.
- **Quota reconciliation tool (directive #8):** reconcile the account delta (100000 → ~98960) against
  the per-family/per-sport QUOTA RECEIPT costs in the operator log; fail if the spend is unattributable.
  Self-contained; builds on `services/odds_quota.py`.

Both are specced here so they can be built and verified deliberately.
