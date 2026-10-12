# NBA Days 3–5 P0 Remediation Specification — focused (rev 2 · 2026-10-12)

**Status: SPECIFICATION ONLY. No code changed. Do not implement until approved.**
Companion to `docs/nba_season_readiness_review_2026-10-11.md` (accepted report `e6c9513`). This
rev is the **focused Days 3–5 P0 spec** for the four accepted blockers. **Rev 2 freezes the five
decisions from review** (no open branches remain): (1) remove the customer-facing `min_confidence`
control; (2) remove Tier from customer presentation, ordering, filtering, and membership; (3) the
single heading **"Live NBA markets"**; (4) order injury-context cards **by team, then player A–Z**;
(5) an **NBA-specific, season-aware** postseason default where an explicit `?postseason=` param
overrides and other sports are unchanged. Each change below carries the **exact current wording**,
its **classification (COPY-ONLY vs BEHAVIORAL)**, the **replacement**, the **behavioral
consequence**, the **non-changes**, the **tests**, and the **rollback** — no
ranking/filtering/membership behavior changes before its replacement is defined (the PropScore
lesson).

**No new model, scoring system, research claim, or architecture.** The composite computations
may remain internally; only their customer presentation / ranking / filtering / membership
change. The free NBA surface, the season string, trial infra, and site-wide containment are
untouched.

---

## 0. Today's data verification (2026-10-12, Monday — preseason)

Verified from the working data + code (prod authenticated re-walk available on request; the
authenticated-board *wording* below is from code/templates, not session state):

| Signal | State today | Source |
|---|---|---|
| Season state | **Preseason**; regular season 2026-27 opens ~late Oct. Season string `get_current_nba_season()` = **"2026-27"** ✅ | code |
| NBA props | **Empty** — `data/props/NBA_Props.csv` header-only, mtime 2026-07-28 (no markets posted) | file |
| NBA game lines | **Empty** — `data/odds/NBA_Odds.csv` header-only, mtime 2026-07-28 | file |
| NBA injuries | **Flowing** — `data/injuries/NBA_Injuries.csv`, 125 players, mtime 2026-10-11 18:30 | file |
| Results / sim pipeline | Ran **today** — `NBA_AllPropResults.csv` / `NBA_Simulation_Results.csv` mtime 2026-10-12 08:3x | file |
| Game coverage | 0 live games / 0 books (no posted slate markets) — expected in preseason | file |

**Consequence for this spec:** all four blockers are reproducible *now* without a live slate,
because they are authority/copy/default-state defects, not data defects. P0-4 (refresh chain) is
the one that needs real opening-week data to fully pass — its acceptance test is defined here and
run Days 6–7 / Day 10.

---

## Blocker 1 — Ungoverned authority on the authenticated NBA board (P0-1)

The composites below are **Legacy — no governed authority** (they predate governance; that alone
strips their authority). They are **not** labeled "Under Review" (that requires opening a formal
evaluation) and are **not** claimed negative-EV (not demonstrated for NBA). The de-vigged
market-implied number may remain as a labeled **Fact** ("the market's number"), never as "our
confidence."

### 1a · Confidence — default sort + "play strength" number + letter grade
**Exact current wording** (`templates/props.html:254-256`, repeated `283-285`):
> kicker **"Confidence"** · value **"Normalized play strength"** · note **"A cleaner 50-99 score
> built from the adjusted hit-rate read so the board stays professional and comparable."**

**Exact current behavior:** `sort_prop_rows(rows, sort_by='confidence', sort_dir='desc')`
(`app.py:19990`) — and every board caller passes `sort_by='confidence'` by default
(`app.py:29308, 36332, 36382, 37299, 38055, 38179, 38903`). `min_confidence` drops rows;
confidence ≥ 80 feeds `is_lock` and a letter `grade` (`services/nba_props_engine.py:186,202,205,233`).

| Change | Class | Replacement |
|---|---|---|
| Default sort | **BEHAVIORAL** | Deterministic authority-free order: **scheduled tip-off ascending, then player A–Z**. (Defined so removing confidence-sort never leaves order undefined.) |
| The "play strength / 50-99 score" tile + letter grade | **COPY-ONLY** (tile text) + **BEHAVIORAL** (stop rendering the grade badge) | Keep only the de-vigged **market-implied %** labeled as the market's number (Fact). Remove "normalized play strength / 50-99 score" text and the letter grade. |
| Customer-facing `min_confidence` control | **BEHAVIORAL** | **FROZEN: remove the customer-facing `min_confidence` control.** (Not relabeled, not kept as a renamed threshold.) |

**Behavioral consequence:** the board's default row order changes (tip-off/name, not strength).
Row counts are unchanged unless `min_confidence` was set. Nothing is dropped by the relabel.

### 1b · Tier — "build-grade / edge"
**Exact current wording** (`templates/props.html:258-261`, repeated `287-290`):
> kicker **"Tier"** · value **"Parlay build quality"** · note **"Tier is stricter than confidence.
> It blends minutes, role stability, edge, and trend quality into a true build-grade."**

| Change | Class | Replacement |
|---|---|---|
| Tier — customer presentation, ordering, filtering, membership | **COPY-ONLY** (tile text) + **BEHAVIORAL** (ordering/filtering/membership) | **FROZEN: remove Tier from customer presentation, ordering, filtering, and membership.** No Tier tile, no Tier-based order or gate, no Tier bucket. (Not kept as "descriptive context.") |

**Behavioral consequence:** Tier disappears from the customer board entirely — no tile, no
ordering, no filtering, no membership role. `snapshot_tier` (`nba_props_engine.py:270`) may persist
**internally** but must not surface or influence anything shown.

### 1c · Locks — board filter + lock badge
**Exact current wording** (`templates/props.html`): board-filter buttons **"All Props"** (365) /
**"Locks"** (367) / **"Floor Plays"** (370); header **"🔒 Locks (80%+ Confidence)"** (399).

| Change | Class | Replacement |
|---|---|---|
| LOCKS board filter, the `props_locks_path` route tab, the lock badge + `lock_reason` | **BEHAVIORAL** (removes a filter/route tab + badges) | Board filter becomes **All Props / Floor Plays** only. `is_lock` (`nba_props_engine.py:235,316`) may persist internally but must not surface. |

**Behavioral consequence:** one customer filter tab (Locks) and the lock badge disappear; Floor
Plays already covers the high-reliability case honestly. No row data changes.

### 1d · Top Plays — "the strongest live rows"
**Exact current wording** (`templates/dashboard.html:1696-1697`):
> title **"Top Plays"** · subtitle **"The strongest live rows with market status and signal notes
> in one place."**

| Change | Class | Replacement |
|---|---|---|
| "Top Plays / strongest / signal" heading | **COPY-ONLY** | **FROZEN: the heading becomes exactly "Live NBA markets."** Ordered by the 1a default. No "top/strongest/signal strength" language. |

**Behavioral consequence:** none beyond the heading text + inheriting the 1a default order; it is a
neutral list, not a best-bets set.

### 1e · Injury "% BOOST"
**Exact current wording** (`templates/dashboard.html:1652,1665`): section **"Expected Role
Changes"**; each row renders **`+{{ role.boost_pct }}% {{ role.expected_shift }}`** (e.g.
"+305.5% shift") plus **"Projected starter"**. `boost_pct` = `Boost_Pct` from the with/without
engine (`app.py:18292, 19736`).

| Change | Class | Replacement |
|---|---|---|
| The fabricated `+N% shift` magnitude in the customer card | **COPY/PRESENTATION** (computation unchanged) | A qualitative, factual note: who is out + the expected role (e.g., "Gui Santos — projected larger role with Jimmy Butler III out"). Any magnitude shown must be a defensible, labeled observation (the player's own recent minutes/usage), never a relative % that balloons off a bench baseline. `build_role_change_candidates` (`app.py:19705/19744`) stays; only the `% shift` presentation changes. |
| Card ordering | **BEHAVIORAL** | **FROZEN: order the role-context cards neutrally by team, then player A–Z** — never by any magnitude. |

**Behavioral consequence:** the displayed `+N% shift` magnitude is replaced by the qualitative
note, and the cards are ordered **team → player A–Z** (not by magnitude). The
`build_role_change_candidates` computation is unchanged; only its presentation and order change.

### 1f · Governance labels (presentation)
Confidence/market number, Tier, Top Plays, injury role-changes → shown as **Legacy** context ("the
market's number," not a BK edge). The de-vigged market-implied probability → **Fact**. Nothing is
marked Qualified/Baseline; nothing auto-marked Under Review.

---

## Blocker 2 — Operator/dev language on customer screens (P0-2)

All **COPY-ONLY** (string edits; no logic change).

| # | Exact current wording | Location | Replacement (frozen) |
|---|---|---|---|
| 2a | **"Run `REFRESH_DATA` to reload player props and rebuild the dashboard board."** | `templates/dashboard.html:1744` | **"NBA markets open closer to tip-off — the board fills when tonight's lines post."** |
| 2b | **"Live props feed is unavailable. Verify the Odds API key or subscription before trusting board lines."** | `app.py:3461` | **"Live NBA lines aren't posted yet — check back near game time."** |

All engine/key/refresh health language stays on **owner-gated** surfaces only. (These replacements
are sport-neutral enough to reuse; if other sports share string 2b, scope the change so only the
customer-facing empty state is reworded, not any owner diagnostic.)

**Behavioral consequence:** none — empty/late-feed states read as calm customer states instead of
maintenance commands.

---

## Blocker 3 — `postseason=1` default during a regular-season opener (P0-3)

**Exact current behavior** (`app.py:20015-20017`):
```python
def postseason_only_enabled():
    value = request.args.get('postseason', '1')
    return str(value).lower() not in {'0', 'false', 'no', 'all'}
```
The param **defaults to `'1'`**, so with no query param the whole app is in **postseason-only**
focus. Pages load `?postseason=1`; the props header renders
**`{{ (focus_mode_label + ' Props') if postseason_only else 'All Props' }}`** with
`focus_mode_label = '20-Team Field'` (`app.py:20075,20084,20099`). The NBA **Matchup Lens** is
framed as "playoff context, series state."

| Change | Class | Replacement |
|---|---|---|
| The NBA `postseason` default | **BEHAVIORAL (NBA-scoped)** | **FROZEN: an NBA-specific, season-aware default.** For NBA, the default view is **regular-season** unless the NBA is actually in its postseason (resolved from the real league phase, not the hardcoded `'1'`). An explicit `?postseason=` query parameter **always overrides** the resolved default. **Other sports are unchanged** — the global default for MLB / WNBA / NFL is not touched. |
| NBA Matchup Lens "playoff context, series state" framing | **COPY-ONLY** | Reframe for regular-season games (series/playoff language removed for NBA regular season). |

**Behavioral consequence:** during the NBA regular season the NBA board defaults to the
**regular-season** field (and defaults to postseason only when the NBA is actually in its
postseason); an explicit `?postseason=` param still overrides. The change is **scoped to NBA**, so
MLB / WNBA / NFL defaults are untouched. Verification (below) must confirm NBA regular-season
schedule/boards/labels render correctly under the new default before it ships.

**"20-team field" (P1, not a standalone edit):** navigating `?postseason=0` did **not** change
"20-Team Field," so it is **not** driven by the postseason default — it is a **data-completeness**
symptom (20 of 30 teams carrying preseason data). **Do not** "fix" the label until a full slate
loads and the real count is known (reconfirm in the §Verification load test).

---

## Blocker 4 — Production refresh chain for lines, props, injuries (P0-4)

**Current state (today):** injuries flow; props/lines are empty (preseason, no markets). Per the
standing rule ("if a feed isn't wired into `run_daily.py` it never runs on prod"), the chain must
be **proven** before opening night. NBA uses the **unprefixed** loaders (`load_props`,
`load_schedule`, `load_gamelogs`, `load_game_market_odds`) and grades via
`load_nba_review_gamelogs`.

**Spec action (Days 3–5, verify-and-document — mostly non-code):**
1. Confirm NBA **props**, **game lines**, and **injuries** fetch/refresh steps are present in
   `run_daily.py` and in the prod systemd timers (not just the Windows batch files). Record the
   exact unit/timer names and cadence.
2. If any NBA feed is **absent** from `run_daily.py`, that wiring is the one code change this
   blocker authorizes (add the NBA feed to the daily operator) — specified and reviewed before
   edit, scoped to wiring only (no model/logic).
3. Document the chain in `docs/PROJECT_MAP.md` so it is re-derivable.

**Acceptance test** (run Days 6–7 + Day 10 on real opening-week data; launch stays blocked until
all pass):
1. **Schedule loads** — regular-season NBA games with correct Eastern dates; no stale/missing days.
2. **Game lines load** — spreads + totals, ≥1 book.
3. **Props load when markets exist** — non-zero rows, `books > 0`, a real market source (not
   "manual or generated board").
4. **Injuries load** — statuses + role-change inputs populate.
5. **Timestamps + sources display** — real "props/lines refreshed <time>" + book list; no "Unknown."
6. **Late/missing feed → safe empty state** — shows the Blocker-2 customer copy, never the operator
   strings.
7. **Tracking + grading persist** — a saved NBA decision survives reopen; after results it grades;
   **NBA appears in the Review Center sport filter** (today it is absent: MLB/NCAAF/NFL/WNBA only).

**Behavioral consequence:** none to UI; this is operational wiring + verification. The only code
touched is `run_daily.py` wiring *if* a feed is found missing (step 2).

---

## Copy-only vs behavioral — at a glance (for staged commits)

- **COPY-ONLY commits** (safe, no logic): 1a tile text, 1b tile text (full removal is behavioral —
  the *text* removal is copy), 1d heading → "Live NBA markets", 1e magnitude text, 2a, 2b, 3
  Matchup-Lens reframe. These can land first and are trivially rollback-able.
- **BEHAVIORAL commits** (reviewed, tested against current output first): 1a default sort +
  **remove** `min_confidence` control + grade badge, 1b **remove** Tier from ordering/filtering/
  membership, 1c Locks filter/route/badge removal, 1e card order (team → player A–Z), 3 **NBA
  season-aware** postseason default (NBA-scoped), 4 `run_daily.py` wiring if missing.
- Mirror the Player Check discipline: for any change that could alter which rows show or their
  order, **characterize current output first**, then prove the change does exactly (and only) what
  the spec says.

---

## Explicit non-changes / boundaries

- No new NBA model, scoring system, research claim, or architecture.
- No change to the free/anonymous NBA surface, the season string, trial infra, or site-wide
  containment.
- `is_lock` / `confidence` / `snapshot_tier` / `boost_pct` **computations** may remain internally;
  only their customer presentation, ranking, filtering, and membership roles change.
- Rankings are not re-weighted; nothing is re-scored. Removing an authority ≠ inventing a new one —
  the replacement order (tip-off/name) is neutral by construction.
- No implementation until this spec is approved. The postseason default **mechanism is now frozen**
  (NBA-specific, season-aware, param-overridable, other sports unchanged) — no remaining decision.

---

## Rollback (per change)

Every change is a discrete, revertible edit; none migrates or deletes data, so rollback is a code
revert with no data step.

| Change | Rollback |
|---|---|
| 1a default sort | Revert the caller defaults to `sort_by='confidence'`; order returns to confidence-desc. Pure presentation — no data effect. |
| 1a grade/number + remove `min_confidence` control | Re-render the tile/grade and restore the `min_confidence` control. The computations were never removed (internal), so the surface returns intact. |
| 1b Tier (full removal) | Restore the Tier tile + any ordering/filtering/membership hook. `snapshot_tier` untouched internally. |
| 1c Locks | Restore the Locks filter button + `props_locks_path` tab + lock badge/`lock_reason` render. `is_lock` untouched internally. |
| 1d Top Plays → "Live NBA markets" | Restore the "Top Plays / strongest live rows" strings. |
| 1e Injury % + card order | Restore the `+{{ role.boost_pct }}% …` render and the prior card order. `build_role_change_candidates` untouched. |
| 2a / 2b | Restore the original strings. |
| 3 NBA postseason default | Revert the NBA season-aware wrapper; the NBA default returns to prior behavior. **Scoped to NBA**, so MLB/WNBA/NFL are never touched by this change or its revert. Ships as its own commit. |
| 3 Matchup-Lens copy | Restore the playoff/series wording. |
| 4 run_daily wiring | Revert the added NBA feed step; the daily operator returns to its prior set. No data effect (a refresh step only writes fresh files). |

Each behavioral change ships as its own commit (not bundled), so any one can be reverted
independently without touching the others — especially the global postseason default.

---

## Surface inventory (prod, All-Access, NBA preseason — from the accepted report + 10-12 recheck)

| Surface | State | Finding |
|---|---|---|
| Command Center `/sports/nba` | renders | Top Plays "strongest live rows"; injury "+N% shift" cards; "Run `REFRESH_DATA`" leak; "20 Teams"; "Props refreshed Unknown". |
| Props Screener `/sports/nba/props` | renders, 0 rows | Default sort **Confidence**; **Tier** "build-grade/edge"; **Locks** filter; "20-Team Field"; "Verify the Odds API key" leak; "Unknown" timestamps; "Manual or generated board". |
| Free Preview `/free/nba` | honest ✅ | Patched `free_tier.html`. No action. |
| Daily Card `/tools/daily-card` | honest ✅ | Inherits 1a–1e once NBA props load; no separate change. |
| Review Center `/candidate-review` | renders | NBA **absent** from the sport filter — must appear once results grade (test §4.7). |
| Matchup Lens `?sport=nba` | renders | "playoff context, series state" — reframe for regular season (Blocker 3 copy). |

*End of focused Days 3–5 P0 specification (rev 2 — five decisions frozen, no open branches). No new
model/scoring/research/architecture. Awaiting approval before the implementation gate opens.*
