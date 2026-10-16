# Player-Prop Capture — Gate 2a Measurement Report (read-only)

Output of the **Gate 2a-measurement** sub-gate (`docs/player_prop_capture_spec.md` §9). Read-only: no
capture built, no surface built. It measures reality to resolve identifiers, pairing, coverage,
timestamps, quota/cost, cadence, and grading/participation coverage, and proposes numeric Gate 2a
thresholds for review. **Nothing is frozen by this report**; cadence + thresholds are frozen only after
review (and after the prod-pending items below are measured on the live feed).

Date: 2026-10-16. Measured on the Windows dev box (NFL in season; NBA off-season). Items needing the
live prod feed are marked **PROD-PENDING**.

---

## 1. Raw provider identifiers actually available
Source = The Odds API event-odds endpoint (`fetch_player_props.py`).
- **Event id: AVAILABLE at the source** (`event['id']` is used to build the request URL) but **dropped
  before storage** — `parse_market_rows` computes `commence_time` and the event, yet the persisted row
  keeps only a `Game` team-label; **no `event_id` or `commence_time` column reaches
  `NFL_Props.csv`** (verified: both ABSENT).
- **Player id: NOT AVAILABLE from the source.** A player prop's identity is `outcome.description` — a
  **name string**; the Odds API supplies no stable player id. → `player_id` must be resolved by us
  (name → roster id); per spec Rev 3, unresolved observations are captured with `raw_player` +
  `player_resolution_status` and grade `UNGRADED`.
- **Source update timestamp: AVAILABLE** — `bookmaker.last_update` is captured as `LastUpdated`
  (100% non-null on the board).

**Implication:** event_id + commence_time are a persistence fix (they exist at source); player_id is a
resolution problem (name matching with a status), not a feed field.

## 2. Per-book pairing reliability
**High at the source.** `parse_market_rows` builds `over_under_map[(player, line)]` **per bookmaker**,
pairing that book's Over and Under at the same line — a genuine two-sided per-book quote. The loss is
downstream: `capture_nfl_prop_lines.py` collapses to a **modal line + independently-median Over/Under
across books** (the cross-book-mixing defect in the spec §2). So canonical per-book pairing is readily
recoverable by persisting the fetch's per-book rows instead of the collapse.

## 3. Both-price and stable-ID coverage (measured)
| Surface | Rows | Over price | Under price | event_id | player_id |
|---|---|---|---|---|---|
| `NFL_Props.csv` (collapsed board) | 2,062 | 100% | **49.4%** | 0% (absent) | 0% (absent) |
| `NFL_PropLines_Archive.csv` (daily capture) | 467 | 100% | 98.3% | 0% | 0% |

- Books present: **3** (BetMGM, DraftKings, FanDuel).
- The board's **49.4% under-price** coverage is an artifact of the modal/median collapse (and one-sided
  markets), **not** the source — per-book both-price coverage must be re-measured on the canonical
  per-book capture (**PROD-PENDING**, needs a valid key).
- Stable-ID coverage is **0%** today (event_id droppable-back-in; player_id needs resolution).

## 4. Source update timestamps
`LastUpdated` (= `bookmaker.last_update`) is **100%** present on the board — a per-book freshness
signal already available for the `line_type` / `minutes_to_commence` labeling in the spec.

## 5. API quota and per-call cost — **PROD-PENDING**
The local Odds API key returns **HTTP 401** (expired/rotated; prod holds the valid key). Measure on prod
with the zero-cost probe:
```
GET https://api.the-odds-api.com/v4/sports/?apiKey=<prod key>   # read headers, costs 0 credits
#   x-requests-remaining / x-requests-used  -> the live quota
```
Per-call cost (documented Odds API behavior): an event-odds call costs **(#markets) × (#regions)**
credits. NFL modeled markets ≈ 10 (the `KEEP_STATS` set), region = 1 ⇒ ~**10 credits per game per
capture pass**; ~14–16 games/week ⇒ ~**140–160 credits per full NFL pass**. NBA in season is ~5–12
games/night across its markets. The exact monthly budget (and therefore how many pregame passes are
affordable) is set by the prod quota — measure first.

## 6. Feasible pregame checkpoint cadence — **PROD-PENDING (depends on §5)**
Shape (to be sized by the measured quota): a daily baseline capture plus **denser captures approaching
kickoff** so a `last_prestart_captured` row is genuinely close (the `bk-linemove.timer` lesson). Concrete
checkpoint counts/intervals are frozen only after §5.

## 7. Grading and participation-source coverage
- **Grading resolution (measured):** `NFL_PropLines_Graded.csv` = 467 rows → OVER 198, UNDER 247,
  PUSH 1, PENDING 21 ⇒ **~95.5% resolved**. **Caveat:** this grader zero-fills missing components and
  has no DNP/VOID/UNGRADED (spec §2), so 95.5% is an **upper bound** — some resolutions may be
  manufactured and must be re-derived under the Rev-3 taxonomy.
- **Participation source: NOT YET IDENTIFIED.** There is injury data in the platform, but a definitive
  **inactives/DNP confirmation source** (who was active each game) is not wired to the grader. Required
  before DNP can be distinguished from UNGRADED (spec §6). **Action:** identify an inactive/participation
  feed per sport (NFL gameday inactives; NBA injury report/box-score DNP) as a Gate-2a input.

## 8. Proposed numeric Gate 2a thresholds (for review — ratify after §5/§6 and the prod re-measure)
Per sport, measured on **real on-disk** canonical-capture observations (not synthetic):
- **event_id coverage ≥ 99%** (source field; persist it).
- **player resolution ≥ 95%** of captured observations in modeled markets (`player_resolution_status =
  resolved`); the remainder captured as `UNGRADED`, not dropped.
- **per-book two-sided coverage ≥ 90%** of (player, market, book) where that book offers the market —
  measured per book, not on a collapsed line.
- **participation-source coverage ≥ 98%** of games (so DNP vs UNGRADED is decidable).
- **grading resolution ≥ 95%** of *gradable* (player-resolved + participation-known) observations within
  **N days** post-game, under the OVER/UNDER/PUSH/VOID/DNP/UNGRADED taxonomy — with **zero**
  manufactured (zero-filled) results.
- **freshness:** a `last_prestart_captured` row within **≤ X minutes** of kickoff (X set by §6).
- **stability:** the capture + grade run **green in `run_daily` for ≥ 14 consecutive in-season days**.

These bars are **proposals**; freeze them after the prod quota/cadence measurement and the
participation-source decision.

---

## Summary
- **NFL** is well-positioned: the source already yields per-book two-sided quotes with freshness; the
  gaps are persistence (event_id + commence), player-name resolution, a participation source, and the
  grader taxonomy/zero-fill fix — an **upgrade/migration**, not a rebuild.
- **NBA** needs the whole capture+grade pipeline (none exists) and must be live before tip-off.
- **PROD-PENDING:** quota/cost (§5), cadence sizing (§6), and the canonical per-book both-price
  re-measure (§3) — all need the valid prod key. Run the §5 probe on the box and append the numbers
  here, then this report can freeze cadence + thresholds for review.

No capture and no surface were built. Gate 2a (build) and Gate 2b (surface) remain closed.
