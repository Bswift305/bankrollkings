# Player/Team Lookup Data-Integrity Gate — Diagnosis (Nico Collins)

**Status: DIAGNOSIS COMPLETE — returned before implementation, per directive.**
Read-only. No product/app behavior changed by this investigation. Tool: `diag_nfl_streak_audit.py`
(read-only, run on prod via SSM; also a fail-closed health report). P1 Green Light archaeology is
paused at its read-only boundary; the SGP handoff stays isolated on `sgp-handoff-hold` (`a94cbf9`).

---

## 1. Nico Collins complete trace — the 5-straight claim is **TRUE**

Corrected premise: "5 straight" = **5 straight vs the Jacksonville Jaguars** (an opponent-matchup,
cross-season **milestone** streak), not a current-season streak.

Canonical identity: **Nico Collins**, WR, **HOU** (NFL rookie year 2021). Authoritative source:
nflverse weekly player logs. Every Nico-vs-JAX game on record, chronological:

| Season | Week | Opp | Rec | **Rec Yds** | 100+? |
|---|---|---|---|---|---|
| 2021 | 1  | JAX | 1  | 7   | — |
| 2021 | 15 | JAX | 2  | 14  | — |
| 2022 | 5  | JAX | 4  | 65  | — |
| 2023 | 3  | JAX | 2  | 34  | — |
| 2023 | 12 | JAX | 7  | **104** | ✅ |
| 2024 | 4  | JAX | 12 | **151** | ✅ |
| 2024 | 13 | JAX | 8  | **119** | ✅ |
| 2025 | 3  | JAX | 8  | **104** | ✅ |
| 2025 | 10 | JAX | 7  | **136** | ✅ |

**Trailing 100+ receiving-yard streak vs JAX = 5** (and 5 at 75+ and 50+ too). **Confirmed.**

### Why it was absent — and how it was almost mis-diagnosed
- **No product computes an opponent-matchup milestone streak.** The two existing NFL streak
  surfaces are **market-line** products, not milestone products (see §2), so a "100+ yards in 5
  straight vs JAX" fact has nowhere to surface.
- **Identity-resolution failure (critical, latent).** The **2025** nflverse build stores Nico as
  **`N.Collins`** (short form), not `Nico Collins`. A literal full-name match returns **zero** 2025
  rows for him (the local 2025 file genuinely has no "Nico Collins" string), which **drops his two
  2025 JAX games (104, 136)** and under-counts the streak to 3. First-initial+last-name key
  resolution (`n.collins`) restores all 9 games and the true streak of 5. Any milestone/streak
  logic that does not key-resolve short↔full names will silently suppress qualifiers.

---

## 2. The two streak PRODUCTS must be separated (they are not, today)

| | **Milestone streak** | **Market-line streak** |
|---|---|---|
| Definition | Reached a fixed factual threshold (100+ rec yds) | Went Over/Under the posted sportsbook line |
| Needs | Authoritative game stats only | Captured market line + grading |
| Opponent-specific? | Yes — "vs JAX" is a milestone view | Possible, but needs captured lines per matchup |
| Built today? | **NO product exists** | `build_nfl_prop_streaks` + `build_nfl_prop_hot_start` (Wave), `build_nfl_hot_hand` (Heat Map) |
| UI label rule | Label as milestone (threshold shown) | Label as market-line; **never** call it "ATS"/"cover" for a milestone |

Nico's streak is a **milestone** (and a matchup milestone). It must be able to qualify even when the
prop-line record is unavailable. The UI must label milestone vs market-line distinctly and never
present a 100-yard milestone as a "cover" streak.

---

## 3. Data-health report

| Source | Scope | State |
|---|---|---|
| nflverse weekly logs (game stats) — **prod** | 2026 | **current through Week 6**, updated today (Heat Map confirms) |
| nflverse weekly logs — **local** | 2026 | **STALE** (parquet through Wk 4, updated 2026-10-08, 231h old) → diagnostic exits fail-closed (2) |
| local 2025 CSV | 2025 | **partial + short-form names** (5,636 rows; `N.Collins` not `Nico Collins`) |
| `NFL_AllPropResults.csv` (market-line grades) — **prod** | stuck at **2025 Wk 18** | prop-grading lane not advancing in-season (see §5.4) |
| `NFL_AllPropResults.csv` — local | max Season 2025 | n/a for 2026 |

The **current-season Wave now correctly fails closed** ("2026 not yet graded") — that is honest, not
operational. **Milestone** streaks, by contrast, are computable from the game-stat logs prod already
has (through Week 6) — they are simply not built.

---

## 4. Threshold audit matrix (independent calc from the complete player universe)

Run via `diag_nfl_streak_audit.py` (local shown here = 2026 **through Wk 4**, stale; **re-run on prod
via SSM for the live Week-6 matrix**). "Service" and "Rendered" are **∅ for every milestone
threshold** because no milestone service/surface exists — that is the gap, not a count mismatch.

| Stat / threshold | Expected (independent) active ≥3 | Service output | Rendered |
|---|---|---|---|
| Rec yds 100+ | CeeDee Lamb (3) | ∅ (no milestone service) | ∅ |
| Rec yds 75+ | Olave(4), JSN(4), Lamb(3), Higgins(3), Flowers(3) | ∅ | ∅ |
| Rec yds 50+ | 10 active (Olave, JSN, J.Johnson, Higgins, Lamb, …) | ∅ | ∅ |
| Receptions 7+ | Olave(4), McBride(4), Lamb(3) | ∅ | ∅ |
| Rush yds 75+ | Cook(3), Kyren Williams(3) | ∅ | ∅ |
| Pass yds 300+ | Stafford(3) | ∅ | ∅ |
| Pass yds 250+ | B.Young(4), Shough(4), Prescott(3), Goff(3), Stafford(3) | ∅ | ∅ |

(Full matrix for all thresholds printed by the tool.) **The audit reconciles as: expected milestone
streaks exist; zero are served or rendered because the milestone product is unbuilt.**

---

## 5. Root-cause classification — **MULTIPLE**

1. **Incorrect/missing streak definition (PRIMARY).** No milestone product (season-wide or
   opponent-matchup) exists; only market-line + board-gated line-relative surfaces. Nico's matchup
   milestone has nowhere to appear.
2. **Identity failure (CRITICAL, latent).** Short-form `N.Collins` (2025 build) is dropped by
   literal-name matching → whole-season suppression + streak under-count. Needs one shared robust
   key-resolver used by all streak/milestone logic.
3. **Stale source (SECONDARY).** Market-line prop record stuck at 2025 Wk 18 on prod (§5.4);
   game-stat parquet is current on prod but stale locally. The market-line Wave fails closed
   correctly; this does **not** block milestone streaks.
4. **NOT** model suppression / confidence / ordering-truncation / render defect **for this case** —
   the item is simply never computed. (Those remain risks a membership firewall must still prevent.)

### 5.4 Why `NFL_AllPropResults.csv` is stuck at 2025 Wk 18 (needs a prod SSM pull to finish)
Determinable now: the record's max Season is 2025; the game-lines/ATS lane is current (2026 Wk 6), so
only the **prop-grading** lane is stuck. Likely: the 2026 posted-prop-line capture/grading isn't
producing graded 2026 rows (cf. CLAUDE.md §13 "`NFL_Props_History` never advanced in-season"). To
confirm, run on prod via SSM and report: `systemctl status`/last run of the prop-refresh unit;
`refresh_all_prop_results.py` logs; input freshness (captured lines); season selection; grading
errors; file permissions; runtime-dir vs committed-seed path; whether a deploy can overwrite it;
whether failures alert. **Do not manufacture 2026 prop grades from game logs** — game stats restore
*milestone* streaks; market-line streaks stay unavailable until authentic captured lines are graded.
`diag_nfl_streak_audit.py` already exits non-zero (fail-closed) when the current-season record is
absent/stale.

---

## 6. Corrective plan + reversible commit boundaries

Each is an independent, reversible commit. **A, B, D are corrections (proceed-able). C is a
product-definition addition → needs your explicit go per your own rule.**

- **A — Identity resolver hardening (CORRECTION, low risk).** One shared `nfl_player_identity`
  resolver (key-resolve short↔full, ambiguity-safe) consumed by every streak/milestone/heat-map
  path; QC proving `N.Collins` ↔ `Nico Collins` and that a qualifier cannot be dropped by a name
  form. No product change.
- **B — Prop-pipeline fail-closed health (CORRECTION).** Wire `diag_nfl_streak_audit.py`'s health
  check into the daily alert (non-zero exit visible to ops) + finish the §5.4 prod diagnosis via SSM.
- **C — Milestone / matchup streak surface (NEW PRODUCT — DECISION GATE).** Season-wide and
  opponent-matchup milestone streaks from game stats, with: milestone-vs-market-line labeling (§2);
  the **explainability contract** (type, threshold/line, length, season, graded-through, source
  health, events evaluated, missing-event count, injury/return designation, membership rule, model
  overlay separated) + a click-through **Streak Explainer** per counted game; and a **membership
  firewall** (every factual qualifier survives model/confidence/injury/row-limit/sort/mapping/alias/
  template-filter; show-all or paginate with total count). Tests must prove Nico cannot disappear.
- **D — Entity-link P0 reopened (CORRECTION, partial decision).** The universal-link requirement is
  **not** closed after one template. Deliver the full mechanical inventory as a **tracked migration
  table** (every occurrence · destination status · blocking reason) and migrate every *actionable*
  occurrence; fetch every destination in tests. **Team destinations:** "no team page exists" is not a
  final answer — specify canonical NFL/MLB team destinations (NFL: extend `/tools/nfl-team` to accept
  `?team=<abbr>` so it targets a specific team instead of the generic profile tab; MLB: a per-team
  page does not exist and must be defined). Do not create guessed links, but do not leave team names
  permanently unlinked. **The NFL/MLB team-destination definition is a small product decision.**

---

## 7. P0 closes only when (directive)
Nico objectively explained ✅ (this doc) · all audited thresholds reconcile ✅ (as a gap, §4) ·
milestone vs market-line separated (C) · current-season freshness visible (B + existing fail-closed) ·
every qualifying player survives membership→render (C firewall) · player/team-link coverage honestly
accounted (D) · authed desktop + 375px prod checks pass (C/D). Then resume Green Light → King's Tickets.
