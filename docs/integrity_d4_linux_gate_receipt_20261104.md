# Integrity + D4 scoped Linux gate receipt — 2026-11-04

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
