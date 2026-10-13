# NBA Commit C — Characterization & Membership/Ordering Record

**Status: read-only characterization (steps 2–3). No code changed.** Pairs with the frozen
`docs/nba_p0_remediation_spec.md` (the authoritative list of *what* to remove) — this document
records *how the shared board is wired today*, so the removal can be proven **NBA-only** and the
other sports proven **unchanged** (steps 4–5).

Date: 2026-10-13.

---

## 1. Scope

Commit C removes the frozen ungoverned authority from the **authenticated NBA props board**
(`props.html`): the Confidence "play strength / 50-99 score" tile + letter grade, the default
Confidence sort + `min_confidence` control, **Tier** (presentation/order/filter/membership), the
**Locks** filter/tab/badge, and the **Top Plays** section. The frozen copy-vs-behavioral
classification is in `nba_p0_remediation_spec.md §1a–1d`; this record does not restate it.

**Hard constraint (director):** NBA-only. NFL, MLB, WNBA, and CFB (NCAAF) behavior must be
**byte-for-byte unchanged**. No ranking/threshold/selection change beyond the frozen removals.

---

## 2. Membership — what renders `templates/props.html`

`props.html` is a **shared** template reached by two distinct render paths:

| Sport | Route | Render function | Path to template |
|---|---|---|---|
| **NBA** | `/sports/nba/props`, `/props` → `nba_props_page` | **`render_nba_props_page`** (app.py:39282) | `render_template('props.html', …)` (app.py:39435) |
| NFL | `/sports/nfl/props` → `nfl_props_page` (app.py:32820) | `render_props_screener_page` (app.py:39140) | app.py:39247 |
| NCAAF | `/sports/ncaaf/props` → `ncaaf_props_page` (app.py:32879) | `render_props_screener_page` | app.py:39247 |
| WNBA | `/sports/wnba/props` → `wnba_props_page` (app.py:33044) | `render_props_screener_page` | app.py:39247 |
| MLB | `/sports/mlb/props` → `mlb_props_page` (app.py:33408) | `render_props_screener_page` | app.py:39247 |
| (cross-sport tools hub) | `/tools/props` (app.py:36520) | `render_props_screener_page` | app.py:39247 |

**Key fact:** NBA has its **own** render function (`render_nba_props_page`); the other sports share
`render_props_screener_page`. Both render the same `props.html`. The template distinguishes sport
only through context vars — chiefly **`props_sport_key`** (default `'nba'`, `props.html:2`) and
`props_show_sample_controls` (`props.html:8`, defaults true only for NBA).

---

## 3. Ordering — default sort per sport

| Sport | Default sort source | Default `sort_by` |
|---|---|---|
| **NBA** | `build_live_prop_request_context` → `get_sort_params()` (app.py:27469, 19977) | **`confidence`** desc |
| NFL | explicit `request.args.get('sort_by', 'player')` (app.py:32827) | `player` |
| NCAAF | explicit `… 'confidence'` (app.py:32884) | `confidence` |
| WNBA | explicit `… 'confidence'` (app.py:33049) | `confidence` |
| MLB | explicit `… 'confidence'` (app.py:33413) | `confidence` |

- `get_sort_params(default_by='confidence')` (app.py:19977) is the **shared** default; NBA inherits
  it via `build_live_prop_request_context`. `build_live_prop_request_context` has **four callers,
  all NBA surfaces** (props 39284, market-edge 39483, two ticket contexts 40237/40359), so changing
  the NBA default there would be NBA-scoped — but the **surgical** change is to give
  `render_nba_props_page` an explicit neutral default, mirroring how `nfl_props_page` already does.
- The frozen target order (spec §1a) is **scheduled tip-off ascending, then player A–Z** — a
  deterministic, authority-free order (not `player`-only), defined so removing confidence-sort never
  leaves order undefined. Implemented via the existing `sort_prop_rows` (app.py:19990) with a new
  neutral key, NBA path only.
- **Do not touch** `get_sort_params`'s shared default or the NCAAF/WNBA/MLB explicit `'confidence'`
  defaults — those keep MLB/WNBA/CFB unchanged.

---

## 4. Authority inventory in `props.html` — the critical finding

Every authority element is gated by **view (`filter_type`)**, **not by sport**, so it currently
renders for **every** sport that uses the template:

| Element | Location (`props.html`) | Current guard | Renders for |
|---|---|---|---|
| "Confidence / Normalized play strength / 50-99 score" tile | 254–256 (floor view) **and** 283–285 (default view) | `{% if filter_type == 'floor' %} … {% else %} …` (line 241) | **all sports** |
| "Tier / Parlay build quality / build-grade" tile | 258–261 (floor) **and** 287–290 (default) | same `filter_type` split | **all sports** |
| **Locks** board-filter tab | 367 (`href=props_locks_path`) | `props_locks_path` defaulted for all (line 7) | **all sports** |
| **Locks** header "🔒 Locks (80%+ Confidence)" | 399 | `{% if filter_type == 'locks' %}` | **all sports** |
| **Top Plays** section | (default-view header block) | view, not sport | **all sports** |

**Consequence:** an *unconditional* deletion of these blocks would change NFL/MLB/WNBA/CFB too,
violating the NBA-only constraint. The removal must be **sport-guarded** — wrap each NBA authority
block so it is suppressed only when `props_sport_key == 'nba'` and renders exactly as today for
every other sport. The data-level fields that feed these (``is_lock``, ``grade``, ``snapshot_tier``
in `services/nba_props_engine.py` — spec §1a–1c) are NBA-engine-only and may persist internally;
they must simply stop surfacing on the NBA board.

---

## 5. Cross-sport baseline & regression-proof plan (step 5)

Because §4 shows the authority is shared/view-gated, the regression proof is essential and concrete:

1. **Before** any edit, capture the rendered authenticated board (default view + floor view + the
   `?filter=locks` / `/locks` tab) for **NFL, MLB, WNBA, NCAAF** — the presence/absence and exact
   text of the Confidence tile, Tier tile, Locks tab, Top Plays section, and the default row order.
2. Apply the frozen removals **guarded on `props_sport_key == 'nba'`** + the NBA-only sort default.
3. **After**, re-capture the same four sports' boards and diff: they must be **identical** (tiles,
   tabs, Top Plays, order all unchanged). Capture the **NBA** board to confirm the five removals.
4. Add a QC that asserts, for a non-NBA `props_sport_key`, the rendered board still contains the
   Tier/Confidence/Locks/Top-Plays markers (guard-direction regression), and for NBA it does not.

Auth note: these boards are behind sign-in; the capture is done against the local dev server with a
test session (or the render functions exercised directly), never against a real user account.

---

## 6. Implementation plan (step 4) — frozen removals only

1. **Ordering (NBA only):** `render_nba_props_page` passes an explicit neutral default
   (tip-off asc, then player A–Z) instead of inheriting `confidence`; `sort_prop_rows` gains the
   neutral key. No change to the shared helper or other routes.
2. **Confidence tile + grade (NBA only):** guard the 254–256 / 283–285 tiles on
   `props_sport_key != 'nba'`; keep the market-implied % (Fact). Stop rendering the grade badge on
   the NBA row. (Copy vs behavioral per spec §1a.)
3. **Tier (NBA only):** guard the 258–261 / 287–290 tiles off for NBA; remove Tier from NBA
   ordering/filtering/membership. Other sports keep the tile.
4. **Locks (NBA only):** suppress the Locks tab (367) + header (399) + lock badge for NBA; NBA board
   filter becomes All Props / Floor Plays. `props_locks_path`/`/locks` stays for other sports.
5. **Top Plays (NBA only):** guard the section off for NBA.
6. **`min_confidence` control (NBA only):** remove the customer-facing control on the NBA board.

Each step is behind an NBA guard or on the NBA render path, so steps 4–5's diff proves the other
four sports are untouched. Nothing is implemented in this record.
