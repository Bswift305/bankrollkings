# Slate-turnover correction — scoped Linux pre-production gate receipt

_Run 2026-11-02 in AWS CloudShell (Amazon Linux, outside production). Fresh anonymous clone of the public
repo; nothing read from or written to the prod box; capture OFF untouched; no paid provider request
(`ODDS_API_KEY` blank, every QC stubs the provider). Not merged; `master` still `63060a9`._

## Identity

| Check | Result |
|---|---|
| Branch | `fix/props-slate-turnover` |
| HEAD | `a5de4003e6d6462e448bd1bcef8a965288ff2c05` — **HEAD_OK** (exact) |
| Chain | `a5de400` → `f6b54e7` → `63060a9` (`F6_ANCESTOR_OK`; a pure fast-forward of master) |
| Diff vs `63060a9` | `fetch_player_props.py`, `qc_props_slate_turnover.py`, `services/feed_validation.py` — only (+731/−1) |
| Overlap with the integrity group | none (no shared files) |
| Platform | Linux 6.1.188 (amzn2023), Python 3.13.16, `pip install -r requirements.txt` exit 0 |

## Results

| Step | Exit | Detail |
|---|---|---|
| `py_compile` (3 files) | 0 | COMPILE_OK |
| `qc_props_slate_turnover.py` | 0 | **77/77** |
| `qc_football_props_aggregation.py` | 0 | |
| `qc_nfl_props_source_fields.py` | 0 | |
| `qc_nfl_props_source_time.py` | 0 | |
| `qc_odds_recovery_preflight.py` | 0 | |
| `qc_run_outcomes.py` | 0 | |
| `qc_slate_validation.py` | 0 | |
| `qc_sport_parent_props.py` | 0 | |
| `qc_sport_registry.py` | 0 | |
| `git status` after the run | — | 0 lines (QCs wrote no tracked file) |

Windows (local) agrees: 77/77 plus the same 9 related QCs. `qc_nba_market_only` (not in scope) fails
identically on base `63060a9` — the known no-user-store 401 pair fixed in the integrity group (`ac55194`).

## What the two commits do

- **`f6b54e7`:** NFL + NCAAF props validate per event:
  - identity required;
  - started/completed events removed from both sides and never published;
  - per-event collapse fails closed;
  - sparse new events allowed;
  - provider error or zero usable events rejects;
  - category counts are logged.
- **`a5de400`** (review fixes):
  - a published not-yet-started event that vanishes rejects at **any** size (`EVENT_VANISHED`, 1→0 and 19→0);
  - market-type contract (line vs binary `player_anytime_td`, asserted against every configured market);
  - the shape receipt's `publish` block describes the filtered file, while `rows_fetched` stays raw;
  - kickoff == now excluded, +1s eligible;
  - non-canonical UTC spellings rejected;
  - `--allow-collapse` bypasses nothing;
  - 50%/20-row are documented as **inherited conservative thresholds, not football-validated constants**.

## Deploy — 2026-11-03 00:45 UTC (owner-approved fast-forward)

- Pre-checks (read-only): `origin/master` == `63060a9`; range = exactly `f6b54e7`, `a5de400`; diff = the 3
  files; prod HEAD `63060a9`, tracked tree clean; capture OFF (no `BK_*CAPTURE*`/`BK_RESEARCH_CANDIDATE*`
  in `.env`, unit environment or drop-ins; 0 capture processes); public + local probe 200.
- `git push origin a5de400:refs/heads/master` → `63060a9..a5de400` (fast-forward, no force).
- Post-deploy (read-only): prod HEAD **`a5de4003e6d6462e448bd1bcef8a965288ff2c05`**, tracked tree clean;
  `bankrollkings` active/running since 00:45:04 UTC (restart by bk-deploy, prewarm ok "for a5de400");
  public + local probe **200**; capture still **OFF** (same checks, all zero).
- Not done, per instruction: no integrity-group merge, no cache purge, no producer run, no paid request,
  no artifact change. Prod `NFL_Props.csv` is still Sunday's slate until the ordinary run.

## Next: production acceptance at the ordinary Tue 2026-11-03 13:00 UTC bk-daily (read-only)

Report the overall bk-daily result separately from props acceptance. If validation rejects: no
`--allow-collapse`, no paid retry, no manual replace — report the exact reason code and the event. A
single withdrawn future event = evidence for a future governed withdrawal/cancellation (event-status)
contract, not a reason to weaken the rule.

## Originally pending (each needed owner authorization)

1. Fast-forward `master` `63060a9` → `a5de400` and push (auto-deploy pulls + restarts within ~2 min).
2. No cache purge is needed for this change. It touches only the fetcher, and the board caches key on
   the props file mtime, which a publish advances. No other production write is part of this step.
3. **Production acceptance** = the next ordinary scheduled refresh (bk-daily 13:00 UTC), read-only
   afterwards. It must prove:
   - current/future games replaced Sunday's completed slate, and no completed games remain;
   - `SourceUpdatedAtUTC` is nonblank and source-derived;
   - writer attribution is correct;
   - provider-credit usage is recorded;
   - a failed validation (if any) preserved the prior file atomically.
