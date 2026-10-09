# CFB Research Audit — can college football produce trustworthy evidence?

**Status:** Research Audit (authorized). This is not feature development. No CFB models,
boards, recommendations, or NFL-feature ports are authorized until this audit answers the
question it exists to answer. Audited 2026-10-09 against the live repo.

The NFL journey's biggest lesson wasn't a lens — it was *operational truth precedes
research truth: you cannot judge a lens until you trust the machine that observed it.*
This applies one level earlier to CFB. Before "does Role Stability work in college?" comes
**"can college football even produce trustworthy point-in-time evidence?"** If it can't,
every downstream result is contaminated.

---

## The verdict (the governing answer)

**Split, by product surface:**

- **Sides / Totals (game lines, ATS): TRUSTWORTHY.** The game-line evidence base is
  historically deep (`NCAAF_GameLines_History.csv`, 7,274 games back to 2021, open **and**
  close), point-in-time aware (`NCAAF_LineMovementHistory.csv` carries a real `SnapshotAt`
  timestamp series from 2026-06 on), and already graded (`NCAAF_GameLineResults_Scored.csv`,
  28,964 rows). CFB **can** produce trustworthy point-in-time evidence here.
- **Player props: CONTAMINATED / UNPROVEN.** The board is live (`NCAAF_Props.csv`, 1,891
  rows) but has **no point-in-time basis**: no per-game player stats
  (`NCAAF_GameLogs.csv` is **missing**), only season-final aggregates
  (`NCAAF_PlayerStats_History.csv`, one row per player-season), **no** accumulating prop
  history, and a grading path that writes nothing (`NCAAF_FeaturedResults.csv` is
  header-only; the shared candidate archive holds **0** NCAAF rows). There is currently
  **no graded, timestamped CFB prop evidence at all.**

So the direction is set by the data, not by preference: **CFB research is a sides/totals
research program.** The NFL lens machinery is player-prop-shaped and does not port until
CFB grows the player-level evidence base it lacks. That is a *finding to act on later*, not
a build order now.

---

## Q1 — Primary CFB product

**Sides / Totals, confirmed by both docs and data.** `docs/ncaaf_game_line_formula.md`:
*"NCAAF is a sides/totals product first. Player props are optional support, not the primary
formula surface."* The data agrees — the game-line side is mature and gradeable; the prop
side is a live snapshot with nothing behind it. Player **production** still matters, but as
an *input to sides/totals* (returning QB, lead back, continuity), not as a prop surface.

---

## Q2 — Evidence-base audit

| Asset | Present? | Point-in-time? | Trustworthy for research? |
|---|---|---|---|
| `NCAAF_GameLines_History.csv` (7,274 games, 2021+) | ✅ | Open+Close per game | ✅ for ATS/total backtests (close = kickoff reference) |
| `NCAAF_LineMovementHistory.csv` (1,970 rows, `SnapshotAt`) | ✅ | ✅ real timestamp series | ✅ but only **2026-06 onward** (no pre-2026 intra-week movement) |
| `NCAAF_GameLineResults_Scored.csv` (28,964, `BK_CFB_EdgeScore`) | ✅ | graded vs close | ⚠️ grading OK; **EdgeScore inputs contaminated** (see ledger #6) |
| `cfb_2026_results.json` (1,355 games, wks 1–5) | ✅ | ❌ overwritten season-to-date | ⚠️ live form only; **no per-week archive → lookahead** (#2) |
| `cfb_power.json` (138 teams, SP+/FPI) | ✅ | ❌ latest only | ⚠️ not reconstructable as-of-week |
| `NCAAF_PlayerStats_History.csv` (13,189 rows) | ✅ | ❌ season aggregates | ❌ one row per player-season → within-season lookahead |
| `NCAAF_GameLogs.csv` (per-game player stats) | ❌ **MISSING** | — | ❌ the missing keystone for any player research |
| `NCAAF_Props.csv` (1,891 live rows) | ✅ | single live snapshot | ❌ no history, no grading behind it |
| `NCAAF_PropLines_Archive.csv` (NFL analog) | ❌ **MISSING** | — | ❌ no prop-line capture exists |
| `NCAAF_CurrentRoster.csv` / `NCAAF_PlayerMaster.csv` (30,072) | ✅ | current state | ⚠️ 2026 state; transfer flagging fragile (#5) |
| `NCAAF_TransferPortal.csv` (4,429) / `NCAAF_ReturningProduction.csv` (134) | ✅ | prior-school modeled | ⚠️ usable for continuity; see #5/#6 |
| CFB play-by-play / drive / possession | ❌ **NONE** | — | ❌ richest granularity is per-quarter line scores |

**Identity:** CFBD `PlayerID` is primary, with a normalized-name fallback used *only* when
PlayerID is empty (`app.py` `_normalize_player_join_key`). Better than NFL's name-first
board was — but transfer-portal rows frequently lack a PlayerID and fall back to name
joins, which is the live collision surface. Teams are name-based (heuristic
longest-prefix resolver in `cfb_current_form.py`).

---

## Q3 — Contamination ledger

| # | Contamination | Class | Severity | Status |
|---|---|---|---|---|
| 1 | Player props have no point-in-time production basis — `NCAAF_GameLogs.csv` missing; only season-final aggregates exist | Future-data leakage (within-season lookahead) | **Critical** for prop work | Open — keystone data absent |
| 2 | `cfb_2026_results.json` overwritten as season-to-date; `cfb_current_form.py` builds SRS/power ratings live from it; no per-week archive | Lookahead (retrospective reads see full season) | **High** | Open |
| 3 | CFB prop results pipeline non-functional — `refresh_ncaaf_featured_results.py` grades against a non-existent gamelog loader; `FeaturedResults` empty; 0 NCAAF rows archived | Missing-evidence (no graded prop record) | **High** | Open |
| 4 | No CFB prop-line snapshot capture (no NCAAF analog to `capture_nfl_prop_lines.py`) | Missing timestamps (price) | **High** for props | Open |
| 5 | Transfer flagging fragile — nan-stringification recently suppressed ~all portal flags (`services/football_intelligence.py:282-297`); portal rows often lack PlayerID → name joins | Roster / transfer contamination + identity | **Medium** | Partially mitigated (fix landed; still name-join fallback) |
| 6 | `calculate_ncaaf_edge_score.py` backtest scored 2025 games with 2026 inputs: full-season stats on Week 1, 2026 portal on 2025 games, 2026 roster; one season only, no recorded price | Future-data + roster + transfer + price | **Critical** (as *validation*) | **Contained** — documented 2026-07-22, not wired to live board |
| 7 | Intra-week line-movement history only exists from 2026-06; pre-2026 is open+close only | Price granularity gap | **Low** | Known limit, not a defect |

**Price contamination note:** game-line backtests grade against the **closing** line (a
legitimate kickoff-time reference), but ROI claims need a *recorded price*, and the deep
history stores lines without a consistent juice/price field. Any CFB ROI number must state
which line and price it assumes — same discipline as NFL.

---

## Q4 — Minimum trustworthy CFB dataset

What we can trust **today**, for point-in-time, out-of-sample sides/totals research:

- `NCAAF_GameLines_History.csv` — open+close spreads/totals, 2021→, 7,274 games.
- Final scores (CFBD `/games`) — for ATS/total resolution.
- `NCAAF_LineMovementHistory.csv` — timestamped snapshots, **2026-06 onward only** (so
  intra-week line-movement research is a 2026+ program, not a historical one).

**Explicitly outside the trustworthy set** until the gaps close: any player-prop research
(no gamelogs, no prop history, no grading), and any *retrospective* team-form/power read
(ratings are overwritten, not archived per week). Returning-production and portal context
are usable as **continuity inputs to sides/totals**, with the transfer-flag fragility noted.

**The three builds that would make the prop side trustworthy** (defining them, not
authorizing them): (a) ingest CFBD per-game player stats → a real `NCAAF_GameLogs.csv`;
(b) a CFB prop-line snapshot capture (the NCAAF analog of `capture_nfl_prop_lines.py`);
(c) repair the prop grading path so `FeaturedResults`/candidate-archive actually populate.
Until all three exist, the lesson from NFL holds: don't judge a CFB prop lens, because the
machine can't yet prove it observed reality.

---

## Q5 — NFL → CFB transfer matrix

Which NFL concepts could get a CFB version, and what each is gated on:

| NFL concept | Ports to CFB? | Gated on |
|---|---|---|
| Game-line / ATS / totals research | ✅ **Now** | Nothing — the evidence base is deep, timestamped, gradeable. This is where CFB evidence lives. |
| Lens Attribution discipline (capture → grade → attribute, pre-registered tests) | ✅ in principle, at the **game-line** level | Applying the *method* to ATS/total signals; not to props |
| Coaching (team-level) | 🟡 Partial | `build_cfb_coaches.py` + favorites/ATS research exist; needs point-in-time framing. Promising at team/ATS level |
| Game Identity / Script (pre-game) | 🟡 Partial | Win-prob derivable from the spread; but **no PBP** → no in-game script. Pre-game only |
| Opportunity (usage/volume) | ❌ Blocked | Needs per-game player gamelogs (missing) |
| Role Stability (variance of role) | ❌ Blocked | Needs per-game usage series (missing) |
| Channel Dependency | ❌ Blocked | Needs per-game yardage splits (missing) |
| Matchup (Defense vs Channel) | ❌ Blocked | Needs player gamelogs + defensive channel splits (missing) |
| Green Light convergence engine (player props) | ❌ Blocked | Needs all of the above + working prop grading |

**Headline:** the portable surface is **sides/totals**. Every player-prop lens is blocked
on the same missing keystone — per-game player data — so there is no point in porting any
of them until that exists. The highest-value CFB-native direction, when build work is
eventually authorized, is a game-line/ATS program that applies the NFL *governance method*
(point-in-time capture, pre-registered tests, honest grading) to the one CFB surface whose
evidence is already trustworthy.

---

## What this audit does NOT authorize

Per the standing orders: no Coach Identity / Role Stability / Script Confidence / Channel
Dependency implementation, no new CFB boards or customer-facing tools, no new CFB
recommendations or scoring systems, no porting of NFL features. The audit's output is this
document. Build work on the three prop-evidence gaps (Q4 a/b/c) or on a CFB game-line
attribution program is a **separate authorization**, to be decided after this audit is
reviewed.

See also: `docs/ncaaf_game_line_formula.md` (formula + the 2026-07-22 contamination note),
`docs/cfb_player_data_model.md` (the transfer/continuity model), `docs/lens_governance_constitution.md`
(the method this would inherit), and `BANKROLL_KINGS_DOCTRINE.md` §10.
