# NBA P0 — Authenticated Production Acceptance — DIRECT AUTHENTICATED PRODUCTION EVIDENCE

**Status: OPEN** (not closed). Date: 2026-10-25. Surface: `https://bankrollkings.com/sports/nba/props`
(live authenticated All-Access session, first NBA slate of the 2026-27 season — 728 licensed market
quotes). This is **direct authenticated production evidence**, kept distinct from the public-preview
evidence (`/free/nba`). No production change was made; this is a read-only acceptance + triage record.

The NBA data-rights gate (`BK_NBA_STATS_ENABLED`) is **OFF** on prod, so the authenticated board is the
**stats-free, licensed-odds-only "market quotes" fallback** (see Attribution #3). That changes how two
criteria are scored (A1, A6–A7), noted below.

---

## Receipt (corrected)

```
A1:   NOT APPLICABLE (raw-quotes fallback) — the tip-off sorter lives in the stats-ENABLED branch of
      render_nba_props_page; the gated market-only board has no confidence/tip-off sort by construction.
      (No Confidence ordering is possible in this code path.)
A2:   PASS — no Confidence column/tile/score anywhere.
A3:   PASS — no Tier tile/ordering/filter.
A4:   PASS — no LOCKS filter/tab/badge; /sports/nba/props/locks coerces to the full board (728 rows).
A5:   PASS — header "NBA · MARKET QUOTES / NBA Markets"; no "Top Plays / strongest" framing.
A6:   CONTAINED_FALLBACK — INTENT CONFIRMED — no "Edge" column at all (the entire analytical/model
      layer is suppressed under the gate; the de-vigged/lean-gap columns exist only in the stats-ENABLED
      branch). Nothing mislabeled. See Attribution #3.
A7:   CONTAINED_FALLBACK — INTENT CONFIRMED — no model estimate shown at all; the honest data-rights
      banner stands in. No ungoverned model authority present.
A8:   PASS — no Simulation Leaders.
B9:   PASS — overs title: "NBA Markets" (no "Best Over Plays"); unders title: "NBA Markets" (no "Best
      Under Plays"). Both /overs and /unders coerce to the ordinary board.
C10:  PASS — no "Run REFRESH_DATA" / "Verify the Odds API key" operator text on the authed board.
      (The injuries page has a user "🔄 REFRESH" button + "Last updated: Unknown" — a P1 nicety, NOT the
      P0 operator-command leak.)
D11:  PASS (season mode only) — regular-season framing; no postseason/playoff-series framing; no
      "20-team field". NOTE: the Data-Pulse contradiction is a SEPARATE P1 (below), not part of D11.
E12:  PASS — NBA injuries gated. Exact banner:
      "The NBA & WNBA injury and boost board is temporarily unavailable. NBA/WNBA injury status,
       teammate-boost averages, percentages, and the role-change reads built from league game logs are
       paused during a data-rights review, so they are not shown right now. This does not affect our
       licensed odds data or other sports, and nothing is deleted. The board returns once sourcing is
       cleared."
F13 desktop: FAIL — console: ~40× "Uncaught EvalError … 'unsafe-eval' … script-src 'self'
      'unsafe-inline' https://unpkg.com" + 2× "Failed to load resource: 401 (Unauthorized)".
      failed resources: 2× 401 (transient, load-time; see Attribution #2 — exact per-request URL not
      isolable via page tooling). redirects: none.
F13 375px: PASS — page overflow: none (8-col table scrolls inside its .mob-scroll container;
      scrollWidth 375 = clientWidth).
```

**Determination:** NBA P0 stays **OPEN** on **F13 desktop** (the Alpine/CSP `unsafe-eval` defect). The
containment/authority criteria (A2–A8, B9, C10, D11-season, E12) all pass authenticated; the board is in
fact *more* contained than the relabel spec because the gate is off. Separately, the **Data-Pulse zero**
is an open **P1** honesty/consistency defect.

---

## Read-only triage & attribution (no fixes applied)

### 1. CSP `unsafe-eval` EvalError (~40×) — BK-OWNED — real functional defect (F13 FAIL)
- **Emitted by Bankroll Kings, not injected.** The only external script on the page is
  `https://unpkg.com/alpinejs@3.14.9/dist/cdn.min.js` (verified via `document.scripts`), loaded by the
  authed shell at **`templates/bk_base.html:24`**. Alpine is BK's own dependency.
- **Cause:** BK's CSP at **`app.py:419`** is `script-src 'self' 'unsafe-inline' https://unpkg.com` — it
  allows unpkg as a *source* but has **no `'unsafe-eval'`**. Alpine evaluates `x-data`/binding
  expressions through `new Function()`, which CSP blocks → one `EvalError` per expression. The authed
  NBA page has **4 Alpine directive elements** → ~40 failed evaluations.
- **Scope:** site-wide (bk_base is the authed shell), surfaced here on the NBA board. Alpine reactivity
  is broken wherever `x-data` is used; server-rendered content still renders.
- **Proposed fix (NOT applied; must NOT add `'unsafe-eval'` or weaken CSP):** migrate to the **Alpine
  CSP build** (`@alpinejs/csp`), which avoids `eval`/`new Function` via a restricted component API — this
  requires rewriting inline `x-data` expressions into `Alpine.data(...)` components (a real change needing
  test). *Alternative:* with only 4 directive elements, evaluate whether Alpine is needed at all; if not,
  replace with plain JS and drop both the unpkg `<script>` and its CSP allowance. **Decision needed:**
  CSP-build migration vs. remove Alpine.

### 2. 2× 401 — `UNKNOWN_TRANSIENT` (plausible load-race, UNPROVEN) — exact request NOT isolable
- Steady state: `/api/live-ticker` returns **200** when authed; a steady-state `fetch` hook caught **no**
  401s; Resource Timing reports 0 failed; the network buffer shows only 200s.
- The one endpoint that 401s without a valid session is **`/api/live-ticker`** (`app.py:35455`), polled
  by the authed shell (`bk_base.html:446`, `credentials:'same-origin'`, fail-soft `.catch`). The service
  worker is **ruled out** (it handles only static shell GETs; all 200).
- **Most consistent explanation:** the ticker poll (`refresh()` on load, bk_base.html:457) races the
  fresh navigation; 2 requests 401 before the session applies, then recover to 200. **Impact: none**
  (fail-soft; the board renders fully).
- **Could NOT capture** exact URL/method/resource-type/initiator for the two failing requests — they do
  not surface in Resource Timing or the retained network buffer, and are not reproducible in steady
  state. **Proposed next step (NOT done):** confirm from prod access logs (401s on `/api/live-ticker`
  around a page load), or a one-shot server request-id log; if confirmed as the load-race, gate the first
  poll on a confirmed session. Low priority.

### 3. Raw-quotes fallback vs the gate — INTENT CONFIRMED
- **`render_nba_props_page` (app.py:41110–41115):** `if not _nba_source_gate.nba_stats_enabled():
  board = build_market_only_board(load_live_props_feed); return render_template('market_only_board.html',
  …)`. The in-code comment: *"Legal/IP NBA.com data-rights gate: while off, serve the stats-free,
  Odds-API-only market board."*
- So the raw per-book "MARKET QUOTES" board is the **deliberate, documented gated state** — not the
  analytical screener failing to render. The tip-off sort / de-vigged read / lean-gap all live in the
  stats-ENABLED branch below the early return. This also confirms `BK_NBA_STATS_ENABLED` is OFF on prod.
- → scores A6–A7 as `CONTAINED_FALLBACK — INTENT CONFIRMED` and A1 as `NOT APPLICABLE`.

### 4. Data-Pulse zero vs 728 quotes — P1 honesty/consistency defect (OPEN, separate from D11)
- **`build_nba_command_center_context` (app.py:30423–30424)** returns **`_nba_command_center_gated_stub`**
  (app.py:30394) when the gate is off — it zeroes ALL counts (`total_props:0, teams:[], today_games:0,
  board_depth:0, nba_gated:True`). Intended containment of **stats-derived** content.
- BUT the Props board's **728 quotes come from the ungated licensed Odds feed** (`build_market_only_board`).
  The stub also zeroes the Command Center's *market* card, so it shows "No plays loaded / NBA markets open
  closer to tip-off — the board fills when tonight's lines post," **contradicting the 728 live licensed
  quotes** one click away.
- **Proposed fix (NOT applied):** the gated stub (or the Command Center market card) should reflect the
  **ungated** licensed market board (show the live market-quote count / a "markets on the board" link)
  rather than implying no markets exist. The data-rights gate should zero *stats-derived* content only, not
  deny the licensed market board. P1 (honesty/consistency), not a legal/authority failure.

---

## Fixes landed on the branch (not yet deployed) — 2026-10-25

- **Decision 1 (`3080991`) — Attribution #1 fixed:** removed Alpine.js + `https://unpkg.com` from the
  CSP; the bet-slip's three tab buttons are now a CSP-safe vanilla tablist (click + keyboard + aria-
  selected). Local authed desktop + 375px: **zero Alpine/CSP console errors**, tabs behave. QC
  `qc_no_alpine_csp.py`.
- **Decision 2 (`82ec268`) — Attribution #4 fixed:** the gated Command Center now shows honest licensed
  market facts (Games / Teams / Prop markets / Market quotes, labeled "licensed sportsbook market quotes
  … not plays/projections/model"), recomputed live from the same feed so counts agree with the board;
  quote rows are distinguished from prop markets; unreliable counts show "Unavailable"; empty feed keeps
  the honest empty state; gate-ON untouched. QC `qc_nba_gated_market_facts.py`.

## Open items — NBA P0 remains OPEN
- **401s → `UNKNOWN_TRANSIENT` (Attribution #2):** the ticker load-race is plausible but **unproven**;
  the ticker is **not** modified. They remain an **F13 acceptance failure** until attributed from
  production access logs (exact paths/methods/user-agent around an authenticated reload) or eliminated.
- **Deploy + re-run:** both fixes are on `claude/jolly-ishizaka-c6519a`, **not deployed**. NBA P0 closes
  only after both fixes deploy, the 401s are attributed or eliminated, and the authenticated
  browser-health check is **re-run cleanly on prod**.
- The analytical-board acceptance (tip-off sort, de-vigged/lean-gap relabels, Legacy-model disclosure) is
  **not verifiable while the gate is OFF** — re-run if/when `BK_NBA_STATS_ENABLED` is turned on.

---

## FINAL PRODUCTION RECEIPT — deployed + re-run (2026-10-26)

**Deployed HEAD:** `master` = **`d09668c`** (fast-forward `ed0bf37..d09668c`; only the authorized NBA
commits cherry-picked onto master: `70a17c5` receipt · `3b93589` Alpine/CSP · `71ddfa5` Data Pulse ·
`5a2c66a` doc · `d09668c` counting-contract refinement). Deploy-diff verified = **6 authorized files
only**; `app.py` compiled + both QCs green on the master base before push; the NFL ATS shadow flag/code
was **not** included. Deploy confirmed live via prod CSP header (no `unpkg`) + behavioral checks below.

**Authenticated prod re-run** (signed-in All-Access; **fresh tab**, cache-busted, to avoid a stale
console buffer — the first-tab console retained pre-deploy messages, disproven by the live DOM):

| Check | Desktop | 375px |
|---|---|---|
| Alpine / `unpkg` script present | **none** (`window.Alpine` undefined, 0 external scripts) | none |
| Console errors (Alpine/CSP or any) | **zero** | **zero** |
| Failed resources (Resource Timing) | **none** | **none** |
| Page-level horizontal overflow | n/a | **none** (scrollWidth 375 = clientWidth) |
| Bet-slip tabs keyboard + functional | **yes** — Parlay active → click Singles → ArrowLeft → Round Robin; exactly one active, `aria-selected`/roving `tabindex` correct | — |

**Data Pulse (gate OFF, live 728-quote feed) — labels + counts:**
`Games 7` · `Teams 14` · `Player-stat markets 291` · `Market quotes 728`.
Caption (verbatim): *"Licensed sportsbook market quotes (Odds API) across 3 books — factual market quotes
(a quote may list only one side), not plays, projections, or model output."* Empty-state title: *"728
licensed market quotes on the board."* **No** false "no markets / board fills closer to tip-off" copy.
Counts are distinguished (728 quotes ≠ 291 player-stat markets) and agree with the market-only board;
label is exactly **Player-stat markets**; all counts derived (none Unavailable this load).

**401 attribution:** **NOT attributed** — production access-log / SSM inspection is required and was not
available to this session. On the fresh post-deploy tab the 2× 401 **did not reproduce** (clean console +
Resource Timing across desktop + 375px, multiple loads), consistent with a transient, but that is **not
attribution**. Classification stays **`UNKNOWN_TRANSIENT`**; the ticker was **not** modified.

**NBA P0 status: the deployed authenticated re-run is GREEN.** Closure is pending only the **401
attribution from production access logs** (exact path, method, timestamp, response status, referrer/UA,
expected-authenticated?) — once the 401s are attributed to an understood benign request (or repaired +
reverified), NBA P0 closes.

---

## 401 read-only log-attribution runbook (owner-run; no writes, no ticker/config change)

**Access:** run in an AWS **SSM Session Manager** session (`ssm-user`, passwordless sudo — the project's
standard; SSH is source-restricted to a stale /32), or SSH only if the owner's current IP is allowlisted.
Every command below is **read-only** (zgrep/grep/awk/journalctl). Do **not** modify the ticker or any
production configuration.

**Important limitation (stated up front):** the original browser receipt captured **no** exact request
URL, timestamp, request-id, or client IP for the two 401s. Access logs can therefore identify *plausible*
401s but can only **conclusively attribute** them if a record correlates **uniquely** to the browser
observations. If no unique correlation is possible, the correct outcome is
**`LEGACY_UNATTRIBUTED_EVIDENCE_GAP`** — *not* "benign", and *not* an active reproduced failure; the green
post-deploy acceptance is preserved separately.

```bash
# 1. Server timezone (to interpret every timestamp). nginx [time_local] also carries the per-line offset.
timedatectl | grep -iE 'time zone|local time'

# 2. Find the nginx access-log path(s) + whether a request-id is logged, then set ACCESS from the result.
sudo nginx -T 2>/dev/null | grep -nE 'access_log|log_format|request_id'
ACCESS=/var/log/nginx/access.log        # adjust to step-2 path if different

# 3. Enumerate EVERY HTTP 401 on 2026-10-25 and 2026-10-26 (current + rotated + .gz).
sudo zgrep -hE '\[(25|26)/Oct/2026' ${ACCESS}* 2>/dev/null | grep -E '" 401 ' > /tmp/nba401.txt
wc -l /tmp/nba401.txt

# 4. 401 distribution by METHOD + path (which endpoints 401'd, and how often).
grep -oE '"[A-Z]+ [^" ]+' /tmp/nba401.txt | sort | uniq -c | sort -rn | head -40

# 5. Isolate the endpoints of interest: ticker, NBA props, and authenticated API/assets.
grep -E '/api/live-ticker|/sports/nba/props|/api/' /tmp/nba401.txt

# 6. Per candidate, the combined line already carries: time_local(+tz) · "METHOD path?query HTTP" ·
#    status · client IP · referrer · user-agent. (request-id only if step 2 showed it in log_format.)
cat /tmp/nba401.txt

# 7. Correlation — did the SAME client IP get a 200 from that endpoint right after the 401?
IP="<candidate-client-ip>"
sudo zgrep -hE '\[(25|26)/Oct/2026' ${ACCESS}* 2>/dev/null \
  | grep -F "$IP" | grep -E '/api/live-ticker|/sports/nba/props' | sort -t'[' -k2

# 8. Application-side view (gunicorn/app 401s + request ids, same window).
sudo journalctl -u bankrollkings --since '2026-10-25 00:00:00' --until '2026-10-27 00:00:00' --no-pager \
  | grep -E '401|live-ticker|X-Request-Id' | tail -200
```

**Per candidate, record:** timestamp + log tz · method · path/query · status · client IP · referrer ·
user-agent · upstream/app request-id (if logged) · whether authentication was expected (`/api/live-ticker`
and `/sports/nba/props` **are** authenticated) · whether the same client subsequently got 200 from that
endpoint.

**Decision rule:** if a 401 correlates **uniquely** to a browser observation → classify the cause and
**close** (benign/understood) or **repair + reverify**. If unique correlation is impossible due to the
missing browser timestamp/path/request-id → **`LEGACY_UNATTRIBUTED_EVIDENCE_GAP`**, and NBA P0 **closes on
the clean repeated post-deploy acceptance**, with a **separate follow-up**: add per-request-id + client
network capture (so a future 401 is always attributable) — observability, not a release blocker.

---

## 401 attribution — RESULT (owner ran the runbook 2026-10-26 11:14 UTC)

Server timezone **UTC (`Etc/UTC`, +0000)** — nginx/gunicorn timestamps are already Eastern+4/5; every
time below is UTC. `nginx -T` showed **no `$request_id`** in `log_format` (combined only), so no
per-request id exists to pin a specific browser console line — this bounds what "unique correlation" can
mean. **227** total 401s on Oct 25–26; `/api/live-ticker` appears **zero** times at 401 (every ticker hit
is **200**).

**Population — fully attributed, all benign.** Every 401 is an **unauthenticated GET of a gated route**:
- **~221 crawler/bot hits** — PetalBot, MJ12bot, SemrushBot, Baiduspider, Bingbot, Reflectionbot, plus
  unauth datacenter clients — hitting `/sports/*`, `/player/*`, `/matchup/*`, `/tools/*`, `/parlay`,
  `/calibration-lab`, `/candidate-review` with no session. The auth gate returning 401 to these is
  **correct behavior**, not a defect.
- **The CTP built-in-browser client** `CTP_CLIENT_REDACTED` (a single public IP, redacted here — raw
  access-log IPs belong in restricted operational logs, not durable Git; UA `Claude/3.6556.2 … MSIX`; its
  fresh cache-busted tab shows UA `Chrome/155.0.0.0`). Its **entire** 401 footprint: `/sports/nba/props`
  at `25/Oct 23:34:06`, `23:37:22`, and `26/Oct 02:15:47` — all **pre-sign-in page loads during triage**.

**The two browser observations — correlated and closed.** The CTP client's only 401s are those
pre-sign-in `/sports/nba/props` loads, and the **same client** then returns **200** on `/api/live-ticker`
continuously from `26/Oct 02:17:07` onward (referer `/sports/nba/props`), including the post-deploy
acceptance run at `10:55–10:58` (referers `…?v=deploycheck1` / `?v=deploycheck2`). The
"same client later got 200 from the endpoint" test therefore **passes**: the 401 → 200 transition is the
sign-in boundary. **`/api/live-ticker` never returned 401** to this client (or anyone) across two days, so
there is **no live ticker-auth defect** — the earlier worry that the ticker was 401-ing authenticated is
disproven by server truth.

**Classification.** Cause of the browser-observed 401s = **unauthenticated access of a gated page before
sign-in** (benign; the gate working). The specific earlier *console* line cannot be pinned to an exact log
row by request-id (none is logged) — that precise pairing is a **`LEGACY_UNATTRIBUTED_EVIDENCE_GAP`** — but
it is **bounded to benign causes**: the only 401s this client ever produced are pre-auth page loads, and no
ticker 401 exists to attribute. This is explicitly **not** "benign by assertion" and **not** an active
reproduced failure; it is a benign population with one un-pinnable console artifact.

### NBA P0 — FINAL DETERMINATION: **CLOSED** (2026-10-26)
- **F13** (CSP `unsafe-eval` EvalErrors / Alpine removed) — fixed, deployed `d09668c`, re-run **green**.
- **Data Pulse P1** (false "no markets" on the gated board) — fixed, deployed, re-run **green**.
- **401s** — fully attributed to correct auth-gate behavior on unauthenticated requests (bots + CTP
  pre-sign-in); no `/api/live-ticker` 401 exists; CTP's 401s flip to 200 at sign-in. No defect; no ticker
  or config change made.

**Parked as a separate P2 observability item (not started; do NOT change nginx or deploy now):** add
`$request_id` to the nginx `log_format` and echo it as a response header (and optionally in the app log),
so any future 401 is attributable to an exact request without this evidence gap recurring. This is an
enhancement, not a fix for anything open — NBA P0 does not wait on it.

### Preserved distinctions (per reviewer direction, 2026-10-26)
- **Current production acceptance:** GREEN (desktop + 375px, post-deploy `d09668c`).
- **401 cause class:** expected pre-authentication gate behavior on unauthenticated requests.
- **Exact console-line-to-log-row pairing:** `LEGACY_UNATTRIBUTED_EVIDENCE_GAP` (no `$request_id` logged;
  bounded to benign causes — not an active defect).
- **`/api/live-ticker`:** no observed 401s in the two-day window.
- **Ticker + production config:** unchanged.
- **Raw access-log client IPs:** not copied into this durable document (redacted).
