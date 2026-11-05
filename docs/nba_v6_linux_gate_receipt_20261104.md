# NBA v6 scoped Linux gate receipt — exact `479e8c4` (2026-11-04) — **FAIL**

**Verdict: FAIL.** Do not deploy; fixes required, then the full gate reruns from scratch. Nothing deployed; no timers,
paid calls or capture changes. Run in AWS CloudShell us-east-1 (kernel 6.1, Python 3.13), fresh anonymous clone, work
dir `/tmp/nbagate`. Gate script sha256 `b6f47ca4…ce21ba66f`.

## Passed
- **Identity and scope:** HEAD `479e8c4cdd4a0699c0dfa5be684a0300a5372bc9`, base `17b5e69`, **53-file scope**, D1 files
  identical, `run_all_scorecards.py` removed_lines=0.
- **Production markers in `app.py`** (**corrected 2026-11-05**; the original line wrongly said "all SAME"): **all 18
  prior markers preserved**, plus **one intentional new `SourceUpdatedAtUTC` Elite-label reference**.
  - That reference is `'quote_updated_utc': _elite_live_text(row.get('SourceUpdatedAtUTC'))`, so `SourceUpdatedAtUTC`
    count is base 18 → head 19.
  - Every other marker count is unchanged: `_quote_from_row`, `_quote_clock_status`, skew constant,
    `_source_time_label`, `q1k2s3`, matchup `src2`, `_judge_submitted_ticket`, 2–8 leg constants,
    `PARLAY_REVIEW_MAX_PICKS`, `Weather unavailable`, `srcutc1`, …
- **POSIX lock/receipt tests executed, 0 skipped:** `nba_lines_lock` 58/0/0, `nba_props_lock` 41/0/0,
  `nba_run_receipt_contract` 37/0/0 (platform linux). The "skip" lines in those logs are outcome names
  (`SKIPPED_LOCKED`), not test skips.
- **Other checks:** D14 retired scan 22/0. `qc_odds_feed` via `qc_offline.py` rc 3. No network (`unshare --net`, loopback
  only).

## Failed
1. **`qc_game_lines_event_slate` 51/59 and `qc_nba_no_game_governance` 39/41 — QC runtime isolation.**
   - On POSIX, `services/nba_lines_publisher.py:76-94 runtime_root()` falls back to the **production**
     `/opt/bankrollkings-runtime` when `BK_RUNTIME_DIR` is unset, and these QCs don't set it.
   - On CloudShell the directory is absent, so the publisher can't lock or write receipts and nothing is published.
   - **On the production box these QCs would write into production runtime data.**
   - With a per-run `BK_RUNTIME_DIR`, the slate QC rises to 58/59.
2. **Line-movement receipt freshness by mtime.** The remaining 3 failures are the line-movement "receipt-proven
   NO_ACTIVE_EVENTS / NO_GAMES_SCHEDULED → benign skip" and "exit 0 + fresh VALIDATION_FAILED → FAILED".
   - `refresh_line_movement_snapshots.py:45-94` treats a receipt as fresh when `mtime > mtime_before`.
   - Successive writes inside the filesystem timestamp granularity compare equal, so the receipt reads as stale and the
     step is misclassified.
   - This is product logic, and prod `bk-linemove` runs it.
3. **`qc_nba_credit_attribution` check (6) non-deterministic on Linux:** **45/50** in the parallel loop (failed runs
   12, 15, 33, 46, 48). Message: "foreign NBA rows … provably landed DURING the stage". The interleaving precondition
   depends on scheduling.
4. **Gate-script defect (mine):**
   - The loop function used `$2` (its own argument, the clone folder) for logs, so loop logs landed inside the clone.
   - The orchestrator/lines-lock/props-lock 50-run loops were **stopped at run ~6** once the gate had already failed.
     They are not evidence either way.
   - The next gate fixes the log path and reruns all four loops ×50.

## Retired-phrase positions (for the owner's allowlist ruling)
- **Code strings:** none on rendered surfaces; the D14 scan passes.
- **Explanatory docstring/comments:** `services/elite_live_labels.py:3-4`, plus QC sources (`qc_elite_live_labels.py`,
  `run_all_scorecards.py:139,144` comments).
- **Rendered disclaimers** that negate the term:
  - `templates/how_we_analyze.html:89` — "We never claim to see 'sharp money' we can't actually observe."
  - `templates/market_movers.html:109` — "We do not label 'sharp money' or 'steam'…".

  The owner's rule allows only non-rendered documentation, so these two need a ruling (keep as disclaimers, or
  reword).

## Next
Fixes are with the NBA builder:
- per-run `BK_RUNTIME_DIR` in every publisher-reaching QC, plus a guard that a QC can never resolve the prod default;
- token-identified line-movement receipts instead of mtime;
- deterministic synchronization for credit check (6).

Then a full rerun of this gate, including 4×50 loops on Linux.
