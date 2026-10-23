# Daily-refresh incident — 2026-10-23 (`daily_operator_20261023_130000.log`)

**Status: ACTIVE P0. Feature work on Entity Links / Streaks is STOPPED until the refresh fully recovers
or has a documented provider outage with safe fail-closed behavior.**

**Access constraint (honest):** the session diagnosing this has **no SSH, no AWS CLI/SSM, and no path to
the authed prod host** — so it cannot `cat` the prod log or run prod commands directly. This document is
the code-level diagnosis + a **ready-to-run** diagnostic you execute via AWS Session Manager (us-east-1 →
Systems Manager → Session Manager; `ssm-user`, passwordless sudo), whose output is then analyzed to
confirm the root cause before any recovery.

> The commits `90dbae0`, `6fbc4dc`, `2ccc914` (and the incident fix below) are **pushed to `master`, not
> production-verified**: the deployed working-copy HEAD was never confirmed. A successful `/healthz` and a
> cache prewarm are **not** freshness proof. Treat them as pushed until the recovery receipt proves the SHA.

---

## Diagnostic results (2026-10-23, from the prod logs — supersedes the code-level hypotheses below)

The prod operator runs **`--continue-on-error`**: the Oct 23 run executed all 155 steps (Finished
13:36:24), so **the failures are INDEPENDENT, not an abort cascade** (my earlier abort hypothesis was
wrong for prod; the preseason gate fix is still valid defense, just not the cause). The chronology shows
small failures Oct 10–17 escalating to **29 fails Oct 22 and 36 fails Oct 23** — the real incident is
Oct 22–23.

**Three independent problem clusters — do not bundle them:**

1. **Odds API — all PAID endpoints failing (leading cause of the freshness incident).** The health guard
   reports **key VALID** (`/v4/sports` OK — a free endpoint) and tripped only on **`Futures 48h old`**.
   But every *paid* Odds call fails fast (~0.7–1.0s) across **all** sports — game lines, player props,
   futures for NFL/NCAAF/NBA/WNBA/MLB. Key-valid + account-wide paid-endpoint failure + instant rejection
   = the **usage-credits-exhausted (HTTP 429 `OUT_OF_USAGE_CREDITS`)** signature. **Confirm** with diag §2b
   (now surfaces the nested HTTP body) + the credits-header probe below.
2. **CFBD — independent provider failure since ~Oct 12.** `CFB data refresh` and every sub-step
   (results/coaches/ATS/roster/stats/returning-production/portal) FAIL with exit 1. Different provider
   from Odds; **not** downstream of it. Likely a CFBD **key (401)** or schema change — confirm via §2b /
   the probe. `schedules/NCAAF_Odds.csv` is 7h fresh but ~empty (120 B), consistent with CFB lines thin.
3. **QC regressions (not freshness):** `NBA Residual-Authority QC` and `CFB Wave Canon QC` fail the
   scorecards; the `NBA/WNBA 99` + `Prelaunch` scorecards then FAIL downstream of stale NBA/WNBA data.
   These are code/data, independent of the provider outages.

**Customer impact (item 7):** STALE (>36h) — `NBA_Odds` 55h, `NBA_Props` 55h, `WNBA_Props` 55h,
`MLB_Props` 55h; ~31h — `NFL_Odds`, `NFL_Props`, `NCAAF_Props`, `WNBA_Odds`. **FRESH** — the nflverse
graded records `NFL_AllPropResults.csv` (7h) + `NFL_PropLines_Graded.csv` (7h), so the **NFL Wave /
milestone record is current** (the earlier item-5 staleness is not present now). Surfaces bound to the
stale odds/props feeds must fail closed (show unavailable), not present 2-day-old lines as live.

**Confirm root cause — run as `ubuntu` (NOT ssm-user; do NOT edit ssm-user git config), NO keys in any
command, NOT a job re-run.** The provider confirmation is a **secret-safe probe built into the
diagnostic** (`--probe`): it loads the key internally, makes exactly ONE health request per provider,
prints HTTP status + nonsecret quota headers + a sanitized error, redacts keys/query-strings/Authorization/
response-ids, and refuses repeat calls within a cooldown (`--force` to override). It never prints or
persists a key — so no API key ever goes into a curl URL or the terminal.
```
# 1) existing-log analysis only (zero API calls) -- §2b prints the real 429 / CFBD body
sudo -u ubuntu bash -lc 'cd /opt/bankrollkings && git log --oneline -1 && \
  venv/bin/python3 diag_refresh_incident.py --log logs/daily_operator_20261023_130000.log'

# 2) + 3) one Odds health/quota probe AND one CFBD auth probe (one request each; no keys printed)
sudo -u ubuntu bash -lc 'cd /opt/bankrollkings && venv/bin/python3 diag_refresh_incident.py --probe'

# the two failing QCs, run directly for their REAL failing assertion (local QCs, no API calls)
sudo -u ubuntu bash -lc 'cd /opt/bankrollkings && venv/bin/python3 qc_nba_residual_authority.py 2>&1 | tail -8; \
  echo ---; venv/bin/python3 qc_cfb_wave_canon.py 2>&1 | tail -8'
```
Paste the literal sanitized §2b + the `--probe` classification. **Classification:** `429
OUT_OF_USAGE_CREDITS` or `x-requests-remaining=0` → Odds exhaustion; `401`/`403` → auth (deactivated/
expired key — note a *deactivated* key from a payment lapse also shows 401, distinct from quota); HTTP
200 + schema/validation error → provider-contract change; DNS/TLS/timeout → infrastructure.

**Root-cause fixes (item 9) — ONLY after the production probe proves the class; each separate + reversible:**
- *Odds `x-requests-remaining=0` / 429:* an **account action (yours)** — top up / wait for the monthly
  reset. Do **not** re-run fetches. (The local dev key currently returns 401 `DEACTIVATED_KEY`, a payment
  lapse — if prod shares it the fix is **reactivate the subscription**, not buy credits. The probe
  distinguishes these: 401 DEACTIVATED vs `x-requests-remaining=0`.)
- *Odds / CFBD `401`/`403`:* reactivate/rotate the relevant key in `/opt/bankrollkings/.env` (SSM getpass
  method), restart. **Do not rotate CFBD until the probe shows 401/403** (it may be HTTP 200 + schema).
- *QC regressions:* **CFB Wave Canon QC passes locally** → its prod FAIL is almost certainly **downstream
  of the CFBD outage** (stale/empty CFB data); re-check after CFB refresh recovers. **NBA Residual-Authority
  QC** fails locally only on a local-env auth artifact (no owner row) → get its real prod assertion from the
  command above and fix as its own commit.

**Containment posture (item 7) — code-level, confirm on the authed pages:**
- **Props boards fail closed:** many surfaces call `load_*_live_props_feed(require_fresh=True)` (stale > 6h
  → empty) and `props.html` / dashboards render `is_stale` + the stale warning, so the 31–55h-stale props
  show as **unavailable**, not old-as-current. The nflverse graded records are **fresh (7h)** and are a
  *historical* record, correctly distinct from the stale *current* markets.
- **Game-LINES gate ADDED (football):** `get_lines_refresh_meta` + the football game-lines/totals board now
  render a visible **"Game Lines Are Stale"** banner when the odds feed is older than 24h (it previously
  surfaced only the *props* feed's freshness, so stale lines could read as current). Guarded by
  `qc_game_lines_freshness.py`. **Remaining:** wire the same `get_lines_refresh_meta` banner into the
  **NBA / MLB / WNBA command-center** line boards (same pattern) — confirm on the authed pages whether a
  31–55h-stale line there still renders as current, and patch identically.

---

## Code-level findings (from the repo — these shaped the initial hypothesis; prod reality above)

1. **The operator aborts on the first `FAIL`.** `run_daily.py` breaks out of the step loop on the first
   non-skipped failure (no `--continue-on-error`). **Every step after the first FAIL never runs** and its
   feed goes stale. So a "mass" incident is very likely **one root cause + an abort cascade**, not N
   independent provider failures. The diagnostic distinguishes *FAILed* from *never-reached* (absent from
   the log).
2. **The first step is a loud, fatal Odds-feed guard.** `qc_odds_feed.py` runs first and FAILs the run on
   a dead/expired/rotated key (**free `/v4/sports` → 401**), **or** when the always-on odds feeds are
   already **stale** (> `STALE_HOURS`). Because it is first and fatal, any Odds-feed problem aborts the
   whole chain before anything refreshes.
3. **Stale-feed trips are self-perpetuating.** Once a fetch failure leaves feeds stale, the step-1 guard
   FAILs on staleness every subsequent run → the chain aborts every night → the feeds stay stale. A run
   can therefore stay "stuck" long after the original transient cause cleared.
4. **Fetchers are fail-closed + atomic on error.** `fetch_game_lines.main` returns exit 1 and **preserves
   the existing CSV** when a fetch raises and the new frame is empty (it never overwrites good data with an
   empty on an exception). `refresh_cfb_data` self-skips (exit 0) with no `CFBD_API_KEY`. So a provider
   outage does **not** corrupt last-known-good; it leaves it stale (correct) and the surface should abstain.
5. **Item 5 (NFL Wave stale `NFL_AllPropResults.csv`) is almost certainly downstream of the abort.** The
   grading/archive steps (`All prop results grading`, `Football candidate archive`, `NFL prop-line grade`)
   run late in the chain; if the run aborts at step 1 they never execute, so the graded record cannot
   advance. The diagnostic confirms this by whether those step labels appear in the log at all.

## FIXED in this change — Item 8 (season-gate NFL preseason)
On Oct 23 the regular-season gate keys on `NFL_Props.csv` (populated in-season) → `NFL` is "active" → the
**"NFL preseason lines"** step was **not** treated as off-season, so an out-of-window preseason fetch that
errored (e.g. a transient Odds API 4xx) would hard-FAIL and abort the chain. `run_daily.py` now **SKIPs**
any preseason step outside the `nfl_preseason_active()` window (Jul 20 – Sep 12): it is **not run**, costs
no credits, and **cannot FAIL the operator**. Guarded permanently by `qc_daily_operator_season_gate.py`
(registered in `run_all_scorecards.py`). This removes one abort vector; it is **not** a claim that preseason
was the Oct 23 root cause — that needs the log (below).

---

## Run this on production (SSM), then paste the output back

### A. Log + feed analysis (steps 1, 2, 3, 6, 7) — read-only, no secrets printed
```
cd /opt/bankrollkings && git pull --ff-only    # get diag_refresh_incident.py (or scp it)
venv/bin/python3 diag_refresh_incident.py --log logs/daily_operator_20261023_130000.log
venv/bin/python3 diag_refresh_incident.py      # also the latest run, to see if it is still aborting
```
This prints the chronology (last all-PASS run, first degraded run, every recent run), the first sanitized
failure (step, provider, HTTP status / exception — **API keys redacted**), the provider step table, and the
feed-age / preservation / customer-impact table.

### B. Shared-infrastructure probes (step 4) — need the service env + network
```
# service loads the expected env + which timer runs it
systemctl cat bankrollkings | grep -i environment
systemctl is-active bankrollkings ; systemctl list-timers | grep -i bk

# required credential NAMES present (NOT values)
sudo grep -oE '^[A-Z0-9_]+=' /opt/bankrollkings/.env | sort

# Odds API key validity + quota + staleness, without printing the key (uses the existing guard)
venv/bin/python3 qc_odds_feed.py ; echo "exit=$?"

# DNS + TLS reachability to each provider (status only)
for h in api.the-odds-api.com api.collegefootballdata.com site.api.espn.com; do \
  echo -n "$h -> "; curl -sS -o /dev/null -w '%{http_code} dns=%{time_namelookup}s tls=%{time_appconnect}s\n' "https://$h" || echo "UNREACHABLE"; done

# disk + inodes + runtime dir ownership/writability
df -h /opt/bankrollkings ; df -i /opt/bankrollkings
ls -ld /var/lib/bankrollkings 2>/dev/null ; sudo -u ubuntu bash -lc 'test -w ${BK_RUNTIME_DIR:-/var/lib/bankrollkings} && echo RUNTIME_WRITABLE || echo RUNTIME_NOT_WRITABLE'

# python deps import cleanly (schema/dep failures)
venv/bin/python3 -c "import pandas,numpy,requests,urllib3; print('core imports ok')"
```

### C. Step 5 — CFBD independent or downstream?
In the diagnostic's provider table: if **`CFB data refresh` has no status line**, the run aborted before it
→ CFBD is **downstream of the abort**, not an independent failure. If it shows `FAIL`, read its sanitized
output (CFBD 401/403/429/schema) and treat CFBD as an **independent** provider issue. Do **not** bundle
distinct providers under one assumed root cause.

### D. Step 6 — artifact preservation (last-known-good)
```
for f in data/odds/NFL_Odds.csv data/odds/NBA_Odds.csv data/odds/WNBA_Odds.csv \
  data/props/NFL_Props.csv data/props/NBA_Props.csv data/props/MLB_Props.csv \
  data/tracking/NFL_AllPropResults.csv; do \
  [ -s "$f" ] && echo "$f  size=$(stat -c%s "$f")  mtime=$(date -r "$f" '+%F %T')  sha=$(sha256sum "$f"|cut -c1-12)" \
             || echo "$f  ZERO-BYTE-OR-MISSING"; done
```
No zero-byte / partial / malformed replacement is expected (fetchers preserve on error). Flag any that are.

---

## Recovery — run ONE controlled refresh ONLY after the root cause is fixed (step 10)
Fix the actual root cause first, in a **separate reversible commit/config change** (e.g. rotate the Odds
API key if 401; top up / wait out quota if 429; fix a provider/schema break). Then **one** pass:
```
cd /opt/bankrollkings && venv/bin/python3 run_daily.py --sports <active sports>   # one controlled run
venv/bin/python3 diag_refresh_incident.py        # confirm the new run is ALL-PASS (or documented outage)
```

### Recovery receipt must include
- deployed production HEAD (`sudo -u ubuntu git -C /opt/bankrollkings log --oneline -1`);
- service + timer status (`systemctl is-active bankrollkings`; `systemctl list-timers | grep bk`);
- every refresh step + its status/exit (the new `daily_operator_*.log` via the diagnostic);
- feed ages (the diagnostic's table — all key feeds < ~a day, none zero-byte);
- API/provider health (`qc_odds_feed.py` clean; CFBD/ESPN reachable);
- atomic-publish verification (step D — no zero-byte/partial, sha/mtime of last-known-good);
- NFL/CFB Wave synchronization (`NFL_AllPropResults.csv` advanced; `report_cfb_wave_sync.py`);
- props/futures freshness (props files fresh; futures file age);
- full scorecard result (`venv/bin/python3 run_all_scorecards.py` — 0 hard FAILs);
- affected-route render verification (owner test-client / authed visual on the stale surfaces);
- next scheduled-run monitoring plan (watch the next `bk-daily` run; the diagnostic on its log).

**If a provider remains externally unavailable:** keep last-known-good, **visibly mark the affected
surfaces stale/unavailable** (they already fail closed), and **do not claim recovery** — document it as a
provider outage with safe fail-closed behavior.

---

## What this change contains (reversible)
- `season_utils.py`: `nfl_preseason_active()` + `is_preseason_step()`.
- `run_daily.py`: pre-skip out-of-window preseason steps (visible SKIP, never run, never FAIL/abort).
- `qc_daily_operator_season_gate.py` (+ registered in `run_all_scorecards.py`): permanent guard.
- `diag_refresh_incident.py`: the read-only, secret-redacting incident diagnostic.
- this document.

The **actual Oct 23 root-cause fix (item 9)** is deliberately NOT guessed here — it is applied after the
diagnostic output confirms which provider/step failed first.
