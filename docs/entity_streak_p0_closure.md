# Universal Entity Links + Streak Explainability — P0 closure report

Status at `e4e5bf5` (pushed to `master`; `bk-deploy.timer` auto-pull + restart). Categories per the
governing directive: **(1)** implemented + locally verified, deployed, awaiting your prod receipt;
**(2)** implemented, awaiting your owner-session **visual** check; **(3)** genuinely unresolved;
**(4)** intentionally unavailable behind a data/legal gate.

Standing constraints held throughout: all feature/data gates OFF, `?view=classic` retained,
`BK_NBA_STATS_ENABLED=0`, Decision Journal + King's Tickets draft store disabled, no NBA.com/WNBA
ingestion, no gate lifted. I cannot run SSM/`curl` against the authed prod gate or drive the prod
browser — so "verified" below means **compile + the owner test-client (server-side gate bypass) +
the QC suite**, with the prod receipt and the visual pass being yours to run.

---

## 1. Implemented + locally verified + deployed (awaiting your prod receipt)

### Destination pages (close the "no destination exists" gap — items 3)
- **MLB team page** — `/tools/mlb-team?team=<team>` (`6ac3746`). Identity + licensed Odds-API
  schedule/lines only; a visible "statistics are not available here" banner; opponents entity-linked;
  unknown/stale team → honest "not a current team" (plain text, never a guess). PRO-gated.
- **WNBA team page** — `/tools/wnba-team?team=<team>` (`6868dd1`). Same shape, **obeys the stats gate**:
  the licensed Odds schedule resolves and renders *while `BK_NBA_STATS_ENABLED=0`* (identity source is
  `_wnba_current_team_set()` off the Odds schedule, **not** stats.nba.com), and statistics abstain
  visibly. This decouples the WNBA team *link contract* from the *stats gate*.
- Resolver: `services/entity_links.py` `TEAM_SPORTS += {mlb, wnba}`, `team_path` branches. App:
  `_entity_team_known` mlb/wnba branches, `build_{mlb,wnba}_team_page`, routes, PRO_ENDPOINTS.
- Fetch tests in `qc_entity_links.py` assert each destination renders the **right sport + entity +
  cleared-only banner** and that an unknown team yields plain text. `qc_entity_link_crawl.py` crawls 7
  authed routes, follows **115** distinct entity URLs, and asserts 200 / correct sport / no nested
  anchors / no gated-stat leakage.

### Shared streak explainer (normalized view-model — item 8)
- `services/streak_explainer.py` `normalize(family, row, meta)` → ONE model
  (threshold · direction · current_streak · current_season · counted_events · excluded_events ·
  source · data_through · freshness · availability · membership_reason · model_status). A field the
  source cannot provide is labeled `unavailable` and **never synthesized**; governed-model status is
  carried **separately** from factual membership. All six families map
  (`milestone/prop/market_line/wave/ats/hot_hand`).
- Partial `templates/_streak_explainer.html` renders the model identically everywhere; opponent names
  inside it go through the centralized entity resolver.
- **Wired as an inline disclosure** on the two player-prop streak surfaces:
  - Milestone Streaks (`/tools/nfl-milestones`) — matchup + season expands (prior commit `52d6827`).
  - Riding the Wave (`/tools/riding-the-wave`) — each Player Prop Streak row is now a native
    `<details>` disclosure (keyboard/mobile-accessible, no JS) rendering the shared model; the player
    name is entity-linked (`e4e5bf5`). Proven end-to-end through the owner test client: explainer
    renders, membership reason + threshold come from the row, per-game values correctly marked
    unavailable, model status separate, **no nested anchors**.

### Streak integrity audits (every live family — item 7)
All green locally; each proves current-season resolution, canonical identity, duplicate/conflict
handling, freshness/fail-closed, membership/ordering, and the frozen ATS rules (active consecutive
covers; earlier losses allowed; pushes interrupt; byes/ungraded ignored; FBS side of FBS–FCS retained;
`(GameID, TeamSide)` authoritative for CFB):
`qc_streak_integrity.py` (prop/market-line + Nico/Caleb traces + source→render hash),
`qc_streak_integrity_milestone.py`, `qc_streak_integrity_ats.py` (NFL + CFB),
`qc_streak_integrity_hothand.py`, `qc_streak_explainer.py`.

**Your prod receipt** (venv python, as before), expected ALL-PASS:
```
cd /opt/bankrollkings && for q in qc_entity_links qc_entity_link_crawl qc_streak_integrity \
  qc_streak_integrity_milestone qc_streak_integrity_ats qc_streak_integrity_hothand \
  qc_streak_explainer; do echo "== $q =="; venv/bin/python3 $q.py 2>&1 | tail -3; done
```

---

## 2. Implemented — awaiting your owner-session VISUAL check

The built-in browser hits the "All Access Required" gate on bankrollkings.com, so I can verify
server-side but not *look* at the signed-in pages. Please eyeball, desktop + 375px:
- `/tools/mlb-team?team=<a current MLB team>` and `/tools/wnba-team?team=<a current WNBA team>` —
  identity, schedule table, the cleared/gated banner, opponent links.
- `/tools/riding-the-wave` — expand a Player Prop Streak row; confirm the explainer reads cleanly and
  the player link works. (Live prop rows only appear once prod's `NFL_AllPropResults.csv` is current —
  see §4.)

---

## 3. Genuinely unresolved (need a decision or a separate build)

- **NBA/WNBA market-only PLAYER + TEAM pages (item 4) — needs your design decision.** The intent is
  clear (resolve identity from the cleared Odds feed so the link persists while the stats gate is off,
  render market-only facts, abstain on NBA.com stats). The blocker is *where*: the existing NBA
  destinations are `/player/<name>?sport=nba` and `/team/<team>?sport=nba` — the **rich stats pages**,
  and the NBA board/`/team` surface is the one you've explicitly **frozen** (NBA containment Days 3–5
  not authorized). Two safe implementations exist and I won't guess between them:
  **(A)** new minimal market-only routes (`/tools/nba-team`, `/tools/nba-player`, WNBA likewise)
  mirroring the MLB/WNBA team pages, with the resolver pointing there while gated — additive, never
  touches the frozen `/team` `/player` routes; or **(B)** make the existing `/team` `/player` routes
  gate-aware (market-only when gated) — fewer URLs, but edits the frozen NBA surface.
  Today these names are **already plain text** while gated, so nothing regresses by leaving this for
  your call. One word — **A** or **B** — and I'll build it.
- **Client-rendered entity links via one server resolver payload (items 2/11) — separate build.**
  Server-rendered surfaces are converted and crawl-clean. The JS-rendered surfaces (King's Tickets,
  SGP Workbench, Daily Cards, Matchup Center, and the live Wave/Heat-Map tables) still render names as
  plain text in the browser. Doing this *correctly* means emitting ONE server-generated resolver
  payload (no alias/URL logic reimplemented in JS) and threading it through each of those prod-verified
  surfaces — a multi-surface workstream of its own, not a drive-by. Scoped, not started.

---

## 4. Intentionally unavailable (data / legal / UI-contract)

- **CFB player page** — no cleared per-player identity dataset exists (CFB is a sides/totals program;
  player props are contaminated/unproven, per `docs/cfb_research_audit`). CFB player names stay plain
  text by design; counted as a documented gap, not a silent drop.
- **WNBA/NBA player & team STATISTICS** — stats.nba.com-gated behind `BK_NBA_STATS_ENABLED=0` pending a
  licensing decision. The WNBA team page shows cleared schedule only and abstains on stats visibly.
- **Hot Hand Heat Map explainer disclosure** — each Heat Map row is itself a single navigational
  `<a>` (row-click → `/tools/nfl-floor`). An inline `<details>` explainer there would nest anchors and
  break the row-click contract the directive says to preserve, so the row stays a link and its player
  name is intentionally plain. The `hot_hand` family is still in the shared view-model and is audited
  (`qc_streak_integrity_hothand.py`); it is simply not inlined into a row-as-link grid.
- **ATS team boards (NFL/CFB, Riding the Wave)** — team-level compact rows carrying no per-game result
  array; the `ats` view-model is audited (`qc_streak_integrity_ats.py`) but an inline disclosure adds
  only "N straight covers" over the existing freshness line, so it was not inlined to avoid clutter on
  a prod-verified surface. Available to wire on request.
- **Live Wave prop rows on prod** — currently render as "unavailable" because prod's
  `NFL_AllPropResults.csv` is stale at 2025 Wk18 (the prop-grading refresh isn't advancing on prod — a
  known data-pipeline item, diagnosed separately via `diag_nfl_streak_audit.py`; `qc_...integration`
  confirms the surface is correct and fails closed). Not an entity/streak code gap.

---

## Closure artifacts delivered
Occurrence-level coverage report (`docs/entity_link_migration.md`) + destination matrix
(`docs/entity_destination_matrix.md`, MLB/WNBA team rows now COMPLETE); fetch-based destination tests;
authenticated crawl (source→render, nested-anchor scan, cross-sport isolation, gated-leak scan); all
five streak families audited with game-level traces; shared explainer view-model audited across all
families. Zero wrong-sport destinations, zero nested anchors, zero unclassified occurrences in the
coverage report.
