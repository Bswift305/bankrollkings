# NBA P0 Board Remediation — Verification Status (living record)

Tracks verification for the two accepted, shipped NBA board commits. **No code is pending.** This
record exists so the populated-row visual check is **completed automatically when the first NBA slate
appears**, without manufacturing or injecting production rows to force it.

Commits covered:
- **`9fcf691`** — Commit C: remove Confidence / Tier / Locks; neutral Tip-off default sort (NBA-only).
- **`a24a919`** — Residual-Authority remediation rev 2 (R1–R8): Edge→"Market lean gap", EV removed,
  Fair→"De-vigged market price", model output confined to the "Legacy model estimate" disclosure,
  Simulation Leaders removed, `/overs`&`/unders` coerced to the direction-filtered board (NBA-only).

---

## 1. Implementation verification — COMPLETE

- `qc_nba_commit_c_guard.py` — Commit C guards, both views × all five sports, incl. the omitted-flag
  fail-safe and column alignment. **PASS.**
- `qc_nba_residual_authority.py` — R1–R6 presentation (both views × all sports, incl. omitted flag),
  R2 market-only fallback, R7-A semantic equivalence (`/overs` ≡ `?direction=over`), R7-B exact
  added-back membership on the real `build_live_props_board` filter. **PASS.**
- Cross-sport regression (Quick Tools, Player Check, NBA Postseason) and `py_compile`. **PASS.**
- Local authenticated test-client render: routes return 200, NFL's Edge column renders from real
  in-season rows (non-NBA unchanged). Valid **pre-production** evidence.

These are registered in `run_all_scorecards.py` and run with the suite.

## 2. Production route / empty-state smoke — PENDING DEPLOYMENT

After `a24a919` deploys, in the **authenticated production browser** confirm on `bankrollkings.com`:
- `/sports/nba/props`, `/sports/nba/props/floor`, `/sports/nba/props/locks`, `/sports/nba/props/overs`,
  `/sports/nba/props/unders` all return healthy (no 500 / no empty-state crash);
- the NBA board filter row shows **All Props / Floor Plays** only (no Locks tab) and the sort control
  reads **Tip-off**;
- no Confidence tile, no Tier tile, no Conf column header;
- `/overs` and `/unders` render the ordinary board (no "Best … Plays (70%+)" title);
- NFL / MLB / WNBA / CFB props pages are unchanged.

This smoke check does **not** require live rows — it verifies route health, sort control, and the
absence of the removed chrome, all of which render on the empty-state page.

## 3. Populated-row visual verification — PENDING NBA FEED (auto-complete on first slate)

A zero-row NBA board cannot visually prove the per-row labels. These are confirmed by the injected-row
QC (§1) as pre-production evidence; the live visual confirmation waits for the first real NBA slate
(season opens ~late Oct 2026). When a populated NBA board is available, confirm on a real row:
- the market column header reads **"Market lean gap"** with the tooltip, not "Edge";
- no "% EV" in the play cell (it falls through to the market-lean / book display);
- the Model-Read disclosure is titled **"Legacy model estimate"** and carries the banner
  "not validated and not used for ordering or selection"; inside it "De-vigged market price",
  "Market lean gap", and "Legacy model" replace "Fair"/"Edge"/"Model";
- **no Simulation Leaders** block (Team Prior Leaders may remain);
- the default row order is tip-off ascending, then player A–Z.

**Do not inject or manufacture production rows to force this check.** Complete it against the first
genuine slate.

## 4. Non-blocking / optional

- NFL `fetch_nfl_player_week.py --check-only` permission-hardening check on prod (`ssm-user` → exit 3,
  `ubuntu` → exit 0) — optional, non-blocking.

Unrelated approved work must not be blocked while §2/§3 wait on deployment and the NBA feed.
