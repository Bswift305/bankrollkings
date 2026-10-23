# Universal Entity Links + Streak Explainability — P0 status report

**Supersedes** the premature `b080a3b` closure (which pre-declared closure while Option A was still an
open A/B decision and the explainers on Heat Map / NFL ATS / CFB ATS were declined). This report states
the **true** status per the current directive, which (1) resolves the open decision as **Option A** and
(2) overrides the earlier declines (explainers are now authorized). It is accurate as of the HEAD below.

Standing constraints held throughout: all feature/data gates OFF, `?view=classic` retained,
`BK_NBA_STATS_ENABLED=0`, Decision Journal + King's Tickets draft store disabled, no NBA.com/WNBA
stats ingestion, no gate lifted. "Verified" means compile + the owner test-client (server-side gate
bypass) + the QC suite; the authenticated prod receipt + the owner-session visual pass remain yours
to run (this session has no SSH/SSM/AWS-CLI and the authed prod gate returns 401 to an anonymous client).

Latest relevant commits on `master`:
- `6fbc4dc` — Option A: additive NBA/WNBA market-only entity destinations (**this session**).
- `90dbae0` — CFB matchup total-render regression guard + prod receipt (this session; see
  `docs/cfb_matchup_total_fix_receipt.md`).
- `da2c3c2` — CFB matchup O/U dict-leak fix.

---

## DONE this session — implemented, verified, deployed

### Item 1 — NBA/WNBA market-only entity destinations (Option A) ✅ `6fbc4dc`
The open "A or B" decision is resolved as **A** and built. Additive, cleared, market-only pages whose
identity resolves from the **licensed Odds feed** (never stats.nba.com), so NBA/WNBA entity links work
while the stats gate is off and revert to the rich pages when it is on. The frozen `/team` `/player`
routes are **untouched**.
- Routes/builders: `/tools/nba-team` (`build_nba_team_page`), `/tools/nba-player` + `/tools/wnba-player`
  (`build_market_player_page`); templates `nba_team.html`, `market_player.html`. All PRO-gated.
- Identity: `_entity_market_player_keyset` (licensed props, mtime-cached), `_nba_current_team_set`
  (licensed Odds schedule). Gate-aware `_entity_player_known` / `_entity_team_known` / `player_url` /
  `team_url`: market-only page while gated, rich page when `BK_NBA_STATS_ENABLED=1`; unknown/ambiguous
  → plain text.
- Resolver: `services/entity_links.py` `market_player_path`, `nba_market_team_path`.
- QC: **`qc_entity_nba_wnba_market.py`** (registered in `run_all_scorecards.py`) — gate-off → market
  pages, unknown/ambiguous → plain text, abstain banner present, **no nested anchors**, gate-on reverts
  to rich pages. Green. Existing `qc_entity_links.py` + `qc_entity_link_crawl.py` still green (they
  already treat no-local-data as plain text, consistent with the gated path).
- Docs: `docs/entity_destination_matrix.md` NBA/WNBA rows now **COMPLETE**.

> Local data (`data/props/*.csv`, `data/odds/NBA_Odds.csv`) is absent off-season (gitignored), so the
> QC is fixture-driven and the **live-data** render is a prod/owner-visual check (below). The fail-closed
> path (no data → plain text / "not a current player/team") is covered by the QC.

### Phase-1 corrective — CFB matchup total-render guard ✅ `90dbae0`
Permanent regression QC (`qc_cfb_matchup_total.py`, registered) for the `da2c3c2` O/U dict-leak fix,
with positive + negative controls, plus `docs/cfb_matchup_total_fix_receipt.md` (deploy source-of-truth,
`/healthz` probe, authed test-client render) and a prominent branch/deploy guard added to
`docs/PROJECT_MAP.md`.

---

## REMAINING — authorized, not yet implemented (precise status + next step)

### Item 2 — one server-generated resolver payload across the client-rendered surfaces — NOT STARTED
Server-rendered surfaces are converted and crawl-clean. The JS-rendered surfaces (King's Tickets, SGP
Workbench, Daily Cards, Matchup Center, and the live Wave / Heat-Map tables) still print names as plain
text in the browser. Correct approach (unchanged): emit **one** server-generated resolver payload
(`{kind, sport, identity} → href | null`, computed by the existing `player_url`/`team_url` so no alias/URL
logic is reimplemented in JS) and thread it through each surface's client renderer; never build hrefs in
JS. This is a multi-surface workstream touching 5 prod-verified surfaces — it must be done per-surface
with a crawl/nested-anchor check each, not as a drive-by. **Next:** add the payload emitter + a single
reference surface (SGP Workbench is the most self-contained) with a QC, then replicate.

### Items 3 + 4 — explainers on Heat Map, NFL ATS, CFB ATS + canonical game details — NOT STARTED (design nailed down this session)
The shared view-model (`services/streak_explainer.py`) and partial (`_streak_explainer.html`) exist and
the `ats` + `hot_hand` families are already audited. Findings that shape the build (so it is correct, not
rushed into audited code):
- **CFB ATS** (`/tools/cfb-ats-streaks`): rows carry `r.streak` + `r.last` (a space-separated W/L/push
  sequence, newest last) + `kind` ∈ {cover, total}. The `ats` view-model currently hardcodes
  direction/"straight covers" — it must be generalized to respect `kind` (cover vs over/under) before
  wiring, or it will mislabel total streaks. Per-game **opponents/weeks/dates are not on the row**, so
  canonical game detail is carried where available (the result markers) and the rest is labeled
  `unavailable` (honest), unless `build_cfb_ats_streaks.py` is extended to emit them.
- **NFL ATS**: `/tools/nfl-ats` is a cover-**rate** table (no streak/results array) — the streak
  explainer belongs on the **NFL ATS Wave** streak board (`build_nfl_ats_wave`), not the rate table.
  Confirm which surface is intended before wiring; the rate table would need a *rate*-explainer, not the
  `ats` streak family.
- **Heat Map** (Hot Hand): each row is a single navigational `<a>` (row-click → `/tools/nfl-floor`). An
  inline `<details>` would nest anchors. The directive wants the explainer visible, so the row must be
  **restructured** so the disclosure is a sibling of the row-link (not nested) — e.g. a separate
  expander control outside the `<a>` — preserving the row-click contract while exposing the explainer.
**Next:** generalize the `ats` branch for `kind` (with a `qc_streak_explainer.py` case), wire CFB ATS +
NFL ATS Wave via the proven `<details>` pattern (as on Riding-the-Wave), and restructure the Heat-Map row
to carry a non-nested disclosure; extend the CFB/NFL ATS builders to emit per-game canonical detail where
the source has it.

### Item 5 — repair + synchronize the stale NFL Wave results pipeline — NOT STARTED (diagnosis stands)
Prod `NFL_AllPropResults.csv` is stale at 2025 Wk18 (the prop-grading refresh is not advancing on prod),
so the live Player-Prop Wave rows correctly render "unavailable" (the surface fails closed — not an
entity/streak code gap). `diag_nfl_streak_audit.py` is the fail-closed health probe. This needs a prod
investigation of why the grading refresh job isn't advancing (SSM; the daily refresh log / the
prop-grading step), then a code fix if the step errors vs an ops fix if the job isn't running. **Next:**
run `diag_nfl_streak_audit.py` on prod via SSM, read the prop-grading step in the daily refresh log,
classify code-vs-ops, and fix accordingly.

### Item 6 — rerun crawl / nested-anchor scan / universe hashes / production receipts — PARTIAL
Re-run locally after Option A: `qc_entity_links.py`, `qc_entity_link_crawl.py` (7 pages, nested-anchor
scan clean), and the new `qc_entity_nba_wnba_market.py` — all green. The **authenticated prod** crawl +
receipts still need owner/prod execution (local data is absent, so the crawl follows 0 live entity URLs
here). **Next:** run the receipt block below on prod after Items 2–4 land, and capture the universe hashes
from the streak-integrity audits on the real on-disk sources.

### Item 7 — accurate final report — THIS DOCUMENT ✅ (supersedes `b080a3b`)

---

## Your prod receipt (venv python), expected ALL-PASS
```
cd /opt/bankrollkings && for q in qc_entity_links qc_entity_link_crawl qc_entity_nba_wnba_market \
  qc_streak_integrity qc_streak_integrity_milestone qc_streak_integrity_ats \
  qc_streak_integrity_hothand qc_streak_explainer qc_cfb_matchup_total; do \
  echo "== $q =="; venv/bin/python3 $q.py 2>&1 | tail -3; done
sudo -u ubuntu git -C /opt/bankrollkings log --oneline -1   # expect 6fbc4dc at/after HEAD
systemctl is-active bankrollkings                           # expect: active
```

## Owner-session visual pass (desktop + 375px)
- `/tools/nba-player?q=<a current NBA player>`, `/tools/wnba-player?q=<a current WNBA player>`,
  `/tools/nba-team?team=<a current NBA team>` — identity, the market/schedule table, the
  cleared/abstain banner, opponent links; an unknown name shows the honest "not a current …" state.
- `/tools/mlb-team`, `/tools/wnba-team`, `/tools/riding-the-wave` (expand a Player-Prop Streak row) —
  as before. Live Wave prop rows appear once prod's `NFL_AllPropResults.csv` is current (Item 5).
