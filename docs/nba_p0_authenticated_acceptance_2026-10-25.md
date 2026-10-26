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
