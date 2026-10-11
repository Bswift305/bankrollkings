# NBA Season Readiness Review — 2026-10-11 (Days 1–2: read-only inventory)

**Goal:** make the *existing* NBA product honest, current, and testable for opening night
(~10 days out) — **not** build a new NBA model. **This is a read-only review. No fixes were
made.** Fixes come in Days 3–5 and only after they're authorized.

**Method:** live inspection of production (`bankrollkings.com`) in an authenticated All-Access
(trial) session, today 2026-10-11 (NBA is **preseason / no live slate yet**), plus targeted code
reads. Surfaces walked live: NBA Command Center, NBA Props Screener, Free NBA Preview. Surfaces
**not yet walked** (flagged for completion): NBA game/matchup pages, Daily Card, Review
Center tracking/grading with real NBA data, and the opening-night operational run.

**Headline:** the NBA product is **not** governed just because the NFL cleanup is done. The NBA
*authenticated* board carries confidence/tier/lock/"top plays"/injury-% authority the NFL
containment removed on its side. That — plus customer-facing operator leaks and a
default-postseason focus — is the launch-blocker set. The public/free NBA surface, by contrast,
already inherits the containment fixes and reads honestly.

---

## P0 — launch blockers (fix in Days 3–5, after authorization)

### P0-1 · Ungoverned authority all over the authenticated NBA board
None of these is classified or qualified; all are **Legacy** (predate governance) and must be
reframed/declassified before opening night — the NBA equivalent of the NFL containment.
- **Props Screener defaults to `Confidence` sort** (sort list: Confidence / Player / Team / …).
  "Confidence" is described on-page as *"Normalized play strength … a cleaner 50–99 score built
  from the adjusted hit-rate read."* This is the same class of composite the NFL side removed as
  the default ranking (de-vigged-price-derived ⇒ ranks the most -EV plays first). Default sort
  should not be a play-strength score.
- **`Tier`** — *"stricter than confidence … blends minutes, role stability, **edge**, and trend
  quality into a true **build-grade**."* A composite quality score claiming "edge" — unqualified
  authority + composite-score (against the do-not-build spirit).
- **`LOCKS`** is a board filter (BOARD: All Props / **Locks** / Floor Plays). A literal "lock" —
  explicitly on the do-not-build list.
- **`Top Plays — "the strongest live rows"`** (Command Center) — best-bets framing.
- **Injury role-shift "% BOOST"** (Command Center "Curated Lens / Expected Role Changes"):
  *"Jimmy Butler III (OUT) can create a **305.5% shift** in this role,"* "+213.8%", "+203.1%",
  shown as precise, authoritative predictions. Spurious precision from the unaudited NBA
  with/without impact engine. A "+305% boost" presented as fact will not survive scrutiny.

**Recommended classification (for the governance call):** Confidence, Tier, Top Plays, and the
injury-% boosts → **Legacy / Under Review**; must be relabeled and removed from any ranking or
"best/strength/edge/lock" authority before opening night. The de-vigged market-implied read may
remain as **Fact** (clearly labeled "the market's number"), not as our "confidence."

### P0-2 · Operator/dev language leaking onto customer screens
- Command Center empty state: **"Run `REFRESH_DATA` to reload player props and rebuild the
  dashboard board."**
- Props Screener live-feed warning: **"Live props feed is unavailable. **Verify the Odds API key
  or subscription** before trusting board lines."**

These are internal ops instructions shown to any signed-in tester. Before props load on a normal
preseason/overnight day they should read as a calm customer state ("NBA markets open closer to
tip-off — check back near game time"), never a maintenance command or an API-key warning.

### P0-3 · Default focus is `postseason=1` during a regular-season opener
`postseason_only_enabled()` defaults **true** (`app.py:20014`), and pages load with
`?postseason=1`. Opening night is the **regular season**, not the playoffs. **Verify** that NBA
regular-season schedule, boards, and labels render correctly under the default focus; if the
default filters to playoff teams/series/labels, that's a launch blocker. (Possible symptom: the
board advertises a **"20-team field"** rather than 30 — see P1-1.)

### P0-4 · Confirm the opening-night data chain actually runs on prod (verify)
Per the standing rule ("if a feed isn't wired into `run_daily.py` it never runs on prod"),
confirm NBA props / game lines / injuries are in the prod refresh and timers so the board
**populates on opening night**. NBA uses the unprefixed loaders (`load_props`, `load_schedule`,
`load_gamelogs`) and grades via `load_nba_review_gamelogs`. Today everything reads 0 rows / 0
books / "Props refreshed **Unknown**" — expected in preseason, but the chain must be proven
against real opening-week data (Day 6–7 load test + a Day 10 smoke test).

---

## P1 — fix if time allows; not launch blockers

- **P1-1 · "20-team field."** The props screener is labeled **"20-TEAM FIELD"** and the Command
  Center shows **"20 Teams."** NBA has 30. Looks like a stale/partial team set — confirm and
  correct, or explain the label.
- **P1-2 · Missing source timestamps.** "Props refreshed **Unknown**", "LINES REFRESHED
  **Unknown**", "MARKET SOURCE: 0 books / **Manual or generated board**." The review wants real
  refresh/source timestamps and clear provenance; "manual or generated board" is worrying
  provenance language to confirm.
- **P1-3 · Contradictory empty-state copy.** The screener says *"The full board still has props
  ready; open it below"* while showing **0 props** — misleading when nothing is loaded.
- **P1-4 · "Tracking is live" vs no feed.** The screener claims NextGen tracking "now feeds the
  board" while simultaneously showing 0 books / feed unavailable — reconcile.

---

## What's already good (carry over, don't re-touch)

- **Season string is correct:** `get_current_nba_season()` returns **"2026-27"** (flips in
  October). ✅
- **Free / anonymous NBA journey is honest:** `/free/nba` uses the patched `free_tier.html` —
  de-vigged "market's read, not our picks" caption, no "Missed Opps/proof" card, clean ticker.
  Rosters look current (Jimmy Butler III on GSW, Shaedon Sharpe on POR). ✅
- **Site-wide containment covers NBA too:** the header-ticker authority is gone, the
  Missed-Winners/Calibration nav gating applies, trial access + feedback work. ✅

---

## 6-area inventory status

| Area | Status |
|---|---|
| 1 Season-state accuracy | Season string ✅; **postseason-default** (P0-3) and **"20 teams"** (P1-1) to resolve; no stale "preseason" banner (unlike NFL). |
| 2 Data readiness | Preseason: 0 games/props/books. Timestamps "Unknown" (P1-2); graceful state leaks ops language (P0-2). Injuries flowing (role engine active). |
| 3 Product surfaces | Command Center + Props Screener + Free Preview walked. **Game pages, matchup tools, Daily Card, tracking/grading NOT yet walked** — complete with opening-week data. |
| 4 Authority & governance | **Primary blocker (P0-1).** Confidence default sort, Tier "build-grade/edge", Locks filter, "Top Plays/strongest", injury "% BOOST" — all ungoverned Legacy. |
| 5 Customer journeys | Anonymous/free NBA honest ✅. Authenticated (free/trial) sees the ungoverned board (P0-1). Mobile/save-reopen/feedback work generically; NBA-specific save+grade to verify with real props. |
| 6 Operational readiness | Refresh chain (P0-4) + clean late-feed behavior (P0-2) to confirm; freshness timestamps (P1-2); opening-night smoke test required (Day 10). |

---

## Proposed Days 3–10 sequence (per the gate)
- **Days 3–5:** spec + fix **P0 only** — declassify/reframe NBA authority (P0-1), replace ops
  leaks with customer states (P0-2), resolve the postseason-default for regular season (P0-3),
  confirm/repair the refresh chain (P0-4). Finish walking the un-inspected surfaces (area 3).
- **Days 6–7:** load opening-week schedule + available markets; test refresh timing.
- **Days 8–9:** free/trial mobile journeys + authenticated prod verification (incl. save/reopen a
  tracked NBA decision and grading).
- **Day 10:** freeze, opening-night checklist, operate.

*No new NBA research mechanism is proposed. No code changed in this review. Awaiting authorization
to open the Days 3–5 P0 fix gate.*
