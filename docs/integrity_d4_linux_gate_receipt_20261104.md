# Integrity + D4 scoped Linux gate receipt — 2026-11-04

> **Owner decision 2026-11-04 (after the `86b6aae` gate): deployment stays ON HOLD; `86b6aae` is Linux-gate-passed
> but NOT the final candidate.** Two more silent-mutation paths must close in narrowly scoped successor commits:
> (1) **quote-change atomicity** — at final submission compare user-confirmed sportsbook/event/market/selection/line/
> price with the current canonical server quote (canonicalize formatting first); any changed book/line/price — even a
> better price — or a stale/missing quote rejects the whole ticket with sanitized 409 (`BOOK_CHANGED`,
> `LINE_CHANGED`, `PRICE_CHANGED`, `QUOTE_STALE`, `QUOTE_UNAVAILABLE`) and current safe display terms; no payout,
> image, export, handoff or partial save; forged client values never control execution. (2) **`/parlay/save`** — no
> truncation to 20 and no silent drops; frozen documented review-record range; over-limit or invalid pick → 422 with
> indexed safe reasons, no save; stored record exactly equals the accepted set. (3) **Executable ticket range frozen at
> 2–8 legs** across editor, Green Light, Menu, images, exports and handoffs (1 → clear minimum message; 9+ → rejected,
> never truncated). Then the complete offline gate and full exact-SHA Linux gate (43 QCs + quote-change + parlay-save
> exactness + `qc_odds_feed` exit 3 + isolation + clean tree). If green, the approved deploy plan proceeds, no purge.
> **NBA timeout contract approved:** lines 30 s, props 60 s, lock wait 30 s, daily lines 60 s, daily props 90 s,
> orchestrator 180 s.

## FINAL RESULT — successor `4afcab9` (quote-change atomicity + exact `/parlay/save` + 2–8 legs)

**Verdict: PASS for exact `4afcab9178f189341140223eecb7f5f96ce67f6e`** — the final deployment candidate. It supersedes
`86b6aae` and `e1e33dc`. Gate only: nothing is deployed, and `master` and production remain `6bdb73f`. Under the owner's
direction ("if green, the already-approved deployment plan may proceed with no cache purge"), deployment now waits only
on the owner's go-ahead (`docs/integrity_d4_deploy_plan_20261104.md`).

**Successor commits on `86b6aae`** (fast-forward; no amend, rewrite or force push):

| Commit | Change |
|---|---|
| `1b1eb03` | A changed quote rejects the whole ticket. Price (worse **or** better), line or book changed, or the quote stale or missing → sanitized 409 with per-leg `PRICE_CHANGED` / `LINE_CHANGED` / `BOOK_CHANGED` / `QUOTE_STALE` / `QUOTE_UNAVAILABLE` and the current safe display terms. Never a silent reprice. Executable range frozen at 2–8 legs (`TICKET_SUBMIT_MIN_LEGS` / `TICKET_SUBMIT_MAX_LEGS`). |
| `268ba20` | `/parlay/save` stores exactly the accepted picks. The frozen range is 1–20 (`PARLAY_REVIEW_MIN_PICKS` / `PARLAY_REVIEW_MAX_PICKS`). 0 or 21+ picks → 422; an invalid pick → 422 with indexed reasons. Nothing saved, trimmed or dropped. |
| `63adfa3` | QCs `qc_ticket_quote_change.py` and `qc_parlay_save_exact.py` (registered additively). |
| `4afcab9` | `docs/ticket_submission_contract.md` |

**How formatting is canonicalized before the comparison:**
- **Price:** whole American odds (`150 == "+150" == 150.0`); a fractional, boolean or text price → 422.
- **Line:** numeric (`-3.5 == "-3.50"`).
- **Book:** case, spacing and punctuation folded, plus a provider-alias table checked against
  `fetch_player_props.BOOKMAKER_TITLES`; "consensus" is never a book.
- **Event, market and selection:** case, spacing, `_` and punctuation folded.

**Extras beyond the owner's list, for review:**
- `QUOTE_MISMATCH` — the event, market or selection differs.
- `QUOTE_UNCONFIRMED` — a leg was sent with no confirmed terms (an older client). It is rejected, and the current terms
  come back for confirmation.

**Gate environment and run:**

| Item | Value |
|---|---|
| Host | AWS CloudShell us-east-1, kernel `6.1.188-233.393.amzn2023.x86_64`, Python 3.13.16 |
| Clone | fresh anonymous clone; work dir `/tmp/integgate4` |
| Gate script | sha256 `e54b6eab…61c03b6aa8` (identical on both sides; differs from the `86b6aae` script only in `EXPECT`, work dir, the commit list, `SCOPE_62` and the two added QCs) |
| Log | sha256 `0723ae62…5f0c60f744a` |
| Time | 2026-11-04 13:24:49Z → 13:28:15Z |

**Results:**

| Check | Result |
|---|---|
| Identity | `IDENTITY_OK`; `ORIGIN_MASTER_IS_BASE_OK` (`6bdb73f`); `BASE_ANCESTOR_OK`; commits `6bdb73f..HEAD` = 28; all 18 named SHAs present (no `MISSING`) |
| Scope | **62 files, +7111/−399** (`SCOPE_62_OK`) |
| D1 preserved | 8 D1-only files `identical_to_base`; union hunk 4/4 markers; `run_all_scorecards.py` `removed_lines=0`, `d1_registration=1` |
| Tree | before / after install / after QCs = 0 / 0 / 0 entries; HEAD after = exact `4afcab9…` |
| `pip install` | rc 0 |
| No network | `sudo unshare --net`, loopback up, no routes: `NO_NETWORK_CONFIRMED: gaierror [Errno -2]`, `lo: UNKNOWN` (up), `curl_http=000`, curl rc 6 |
| `py_compile` | 45 changed `.py` files, rc 0 |
| QCs | **`QC_TOTAL=45 QC_FAIL=0`.** The 43 prior QCs all rc 0, incl. `unpriced_line_legs` 173/173, `ticket_submission_atomic` 68/68, `ticket_kickoff_gate` 119/119, `sgp_kickoff_gate` 53/53, `props_slate_turnover` 77/77, `matchup_center_cache_version` 16/16, D1 `nfl_weather_venue_integrity` 275/275, `route_qc_harness` 8/8, `ncaaf_odds_single_writer` ok=65 fail=0, `nfl_roster_single_writer` ok=36 fail=0. New: **`ticket_quote_change` 114/114**, **`parlay_save_exact` 117/117**. |
| Blocked connections | 5, all inside `unpriced_line_legs`' own socket-guard self-tests (expected); 0 in every other QC |
| Warnings (rc 0) | `wnba_readiness` (off-season WNBA props absent) and `nba_visual_trust` (gated route), as before |
| `qc_odds_feed` via `qc_offline.py` | **rc 3** — `NOT RUN: … REQUIRES_NETWORK = True` |

**Also green:**
- the builder's gate in the worktree and in a clean `git archive` export (45/45, `qc_odds_feed` exit 3, export tree =
  HEAD tree);
- my own local re-run of `ticket_quote_change` 114/114, `parlay_save_exact` 117/117, `ticket_submission_atomic` 68/68
  and `unpriced_line_legs` 173/173.

**Mutation checks (builder):**
- repricing restored → 24/24 image checks fail and 8/8 SGP checks fail;
- leg-count gate removed → 4/4 fail;
- 20-pick truncation restored → 2/2 fail;
- silent drop of invalid picks restored → 60/60 fail.

**Not covered:**
- No real-browser run of the "Confirm current terms" resubmission flows (editor, Menu slip, SGP). This is acceptance
  matrix rows A12–A14 after deploy.
- No deploy; no production data.

**Owner items:**
- The two extra reason codes listed above.
- The shared editor still *builds* at most 5 legs (`TICKET_EDITOR_MAX_LEGS`, King's Tickets "2–5"). This is inside the
  frozen 2–8 contract; the server accepts 2–8. Raising the editor cap to 8 is the owner's call.

---

## SUPERSEDED RESULT — successor `86b6aae` (atomic submission + Matchup Center cache isolation)

**Verdict: PASS for exact `86b6aae902d8f0ff938c4f538bdc5601f120d948`** — superseded by `4afcab9` (above).
`e1e33dc` (below) is superseded and must not be deployed on its own. Gate only; nothing deployed; `master` and
production remain `6bdb73f`.

- Successor commits on `e1e33dc` (fast-forward, no rewrite): `9d3dfbf` atomic user-submitted tickets (whole-ticket
  409/422 with per-leg reason codes; no payout, no partial image, nothing persisted; editor shows per-leg remove/
  rebuild), `161669e` Matchup Center disk-cache key `nfl_matchup_center` → `nfl_matchup_center::src2` (file
  `nfl_matchup_center_src2.pkl`; old file never read, not deleted; prewarm uses the new key), `117b3d3` QCs, `86b6aae`
  synthetic-fixture tags for the new QC's `-110` placeholders.
- Clone: `IDENTITY_OK`; `ORIGIN_MASTER_IS_BASE_OK` (`6bdb73f`); `BASE_ANCESTOR_OK`; commits `6bdb73f..HEAD` = 24
  (the prior 20 + 4); all 14 named SHAs present (no `MISSING`).
- **Scope: 58 files, +5398/−349** (`SCOPE_58_OK`); files changed since `e1e33dc`: `app.py`, `qc_matchup_center_cache_
  version.py`, `qc_sgp_workbench.py`, `qc_ticket_kickoff_gate.py`, `qc_ticket_submission_atomic.py`,
  `qc_unpriced_line_legs.py`, `run_all_scorecards.py`, `templates/_ticket_editor.html`, `templates/menu_board.html`,
  `templates/sgp_workbench.html`.
- **D1 preserved:** the 8 D1-only files identical to `6bdb73f` (no `CHANGED`); union hunk 4/4 markers;
  `run_all_scorecards.py` change is additive only (`removed_lines=0`, D1 registration present).
- F7 resolution intact (`KNOWN_PENDING = {}`).
- Environment: CloudShell, kernel 6.1.188, Python 3.13.16, `pip` rc 0; gate script sha256 `57efba2f…ae8f349f`; log
  sha256 `e226ed0b…46b0b9f74b`; 2026-11-04 02:34:10Z → 02:37:40Z; work dir `/tmp/integgate3`.
- **No network:** `sudo unshare --net`, loopback up, no routes — `NO_NETWORK_CONFIRMED gaierror`, `lo: UNKNOWN` (up),
  `curl_http=000` rc 6.
- **Results:** tree 0 / 0 / 0 entries, HEAD unchanged; `py_compile` 43 changed `.py` rc 0; **`QC_TOTAL=43 QC_FAIL=0`**
  — the 41 prior QCs all rc 0 (incl. `unpriced_line_legs` 172/172, `props_slate_turnover` 77/77, `ticket_kickoff_gate`
  119/119, `sgp_kickoff_gate` 53/53, D1 `nfl_weather_venue_integrity` 275/275) plus **`ticket_submission_atomic`
  67/67** and **`matchup_center_cache_version` 16/16**; `qc_odds_feed` via `qc_offline.py` → **rc 3** NOT RUN; blocked
  connections only the 5 expected inside `unpriced_line_legs`' guard self-tests.
- Offline (builder, worktree + clean export) and coordinator re-runs also green (atomic 67/67, cache-version 16/16,
  kickoff 119/119, SGP kickoff 53/53, unpriced 172/172, sgp_workbench).
- Behaviour notes for the owner: the server now accepts 2–8 legs (previously 2-leg editor tickets got 400 and > 8 were
  silently cut); new reason codes `NOT_ON_BOARD`, `MALFORMED_LEG`, `DUPLICATE_LEG`. **A client-supplied price that
  differs from the server quote is still re-priced from the server quote rather than rejected** (required by
  `qc_unpriced_line_legs` so the client can never inject a price) — owner may prefer a `PRICE_CHANGED` rejection
  under the "no silent alteration" rule. **`/parlay/save`** (legacy NBA Parlay Builder review record) still truncates
  at 20 picks and drops invalid picks silently — not an image/export/handoff/payout, left unchanged, open. Browser-side
  per-leg marking not yet verified in a real browser (covered by the post-deploy acceptance matrix).

---

## Original result — `e1e33dc` (superseded)

**Verdict: PASS.** Gate only — nothing deployed; `master` and production remain `6bdb73f`. Deployment needs separate
owner approval.

## Gated commit

- **Exact SHA: `e1e33dc32777e2a9ec69f04293dbbc546eb00faf`**, branch `integration/integrity-d4-6bdb73f`, fresh
  anonymous public clone (`IDENTITY_OK`).
- Base: clone's `origin/master` = `6bdb73fcf3aea9ea003ea981e579854a22af9b04` (`ORIGIN_MASTER_IS_BASE_OK`; production
  HEAD verified = `6bdb73f` on 2026-11-03 23:21Z) and an ancestor of HEAD (`BASE_ANCESTOR_OK`).
- Commits `6bdb73f..e1e33dc`: 20 = **16 non-merge** (the 16 that `range-diff` showed `=`) + **4 merges**. Present:
  merges `8d9189a` (F1), `ef1dcb1` (qc-wnba-nba-self-contained), `2fda677` (daily-card-no-fabricated-price), `cbef5bb`
  (F7); D4 `4005e2f`, `25b13a7`, `17e35e1`, `03e4f83`, `e7692dc`, `e1e33dc`.
- **Scope: 55 files, +4422/−334** (`SCOPE_55_OK`).
- **D1 preserved:** all 9 D1-only files `identical_to_base` (`fetch_nfl_weather.py`, `qc_cfb_board.py`,
  `qc_nfl_board.py`, `qc_nfl_visual_trust.py`, `qc_nfl_weather_venue_integrity.py`, `run_all_scorecards.py`, the three
  NFL templates). The single overlapping `app.py` line (`build_nfl_game_board_context` Totals `cands.append`) carries
  the union: 4/4 marker lines present (D1 `wind`/`weather_label`, `roof`/`roof_label`, WIND `flag`; Integrity
  `line_source`/`updated_utc`).
- **Approved F7 resolution:** `qc_unpriced_line_legs.py:58` `KNOWN_PENDING: dict = {}   # emptied at integration`.

## Environment and no-network proof

AWS CloudShell us-east-1, kernel `6.1.188-233.393.amzn2023.x86_64`, Python 3.13.16, fresh venv, `pip install -r
requirements.txt` rc 0 (network allowed only for install). Work dir `/tmp/integgate2`. Gate script sha256
`93bf47b0…f29cce5`; log sha256 `4ef29438…3542eccb`. Started 01:46:49Z, finished 01:50:38Z.

Compile + every QC ran inside `sudo unshare --net` (fresh network namespace, as the normal user) with **only loopback
up and no routes**: `NO_NETWORK_CONFIRMED: gaierror [Errno -2]`; `iface: lo: UNKNOWN` (up); `ip -o route` empty;
`curl https://api.the-odds-api.com/` → `curl_http=000`, rc 6. This blocks every process, not only Python.

## Results

| Check | Result |
|---|---|
| Tree before / after install / after QCs (`--untracked-files=all`) | 0 / 0 / 0 entries; HEAD unchanged |
| `py_compile` — 40 changed `.py` files incl. `app.py` | rc 0 |
| 34 Integrity QCs (via `qc_offline.py`) | **all rc 0** — `unpriced_line_legs` 172/172, `route_qc_harness` 8/8, `ncaaf_odds_single_writer` ok=65 fail=0, `decision_journal` 18/18, `lookup_change_store` 11/11, `lookup_change_views` 3/3, `model_observations` 3/3, `nfl_props_source_time` ok=14 fail=0, `nfl_roster_single_writer` ok=36 fail=0, rest Clean/verified |
| `qc_ticket_kickoff_gate` | 119/119 |
| `qc_sgp_kickoff_gate` | 53/53 |
| `qc_nfl_weather_venue_integrity` (D1) | 275/275 |
| `qc_props_slate_turnover` | 77/77 |
| `qc_nfl_board`, `qc_cfb_board`, `qc_football_board`, `qc_nfl_visual_trust` | rc 0 |
| **Total** | **`QC_TOTAL=41 QC_FAIL=0`** |
| `qc_odds_feed` via `qc_offline.py` | **rc 3** — `NOT RUN: qc_odds_feed.py declares REQUIRES_NETWORK = True (not an offline QC)` |
| Blocked connections | 5 lines, all inside `qc_unpriced_line_legs`' own socket-guard self-tests (expected); 0 elsewhere |
| Non-blocking warnings (rc 0) | `wnba_readiness` (WNBA live props absent, off-season), `nba_visual_trust` (gated route renders) |

## First run — not a result (disclosed)

The identical script first ran with the namespace's loopback **down** (`/tmp/integgate`, log sha256
`7ca5f1fc…54682e1`, 01:3x–01:45:42Z): `QC_TOTAL=41 QC_FAIL=1`. The one failure was `qc_unpriced_line_legs` 171/172:
`[FAIL] F: loopback wrongly blocked: OSError(101, 'Network is unreachable')` — the QC's self-test that its socket guard
must **not** block loopback, which cannot pass when the namespace has no loopback. A gate-harness defect, not a code
defect; every other QC and assertion matched the final run. Fixed by bringing `lo` up inside the namespace (still no
routes); the full gate was re-run from a fresh clone.

## Not covered

No browser rendering; no deploy; no production data. Deployment of `e1e33dc` is not authorized.
