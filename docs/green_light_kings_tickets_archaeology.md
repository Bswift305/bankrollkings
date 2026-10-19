# P1 Phase A — Green Light → editable King's Tickets archaeology (READ-ONLY)

Returned before any P1 code, per directive. No implementation here. `a94cbf9` (SGP handoff) stays
isolated/undeployed. All file:line from current `master`.

---

## Headline correction (important, evidence-based)

**The editable 2–5-leg ticket was NOT removed. It is live in production today.** It lives under
**"Today's Cards" / Daily Card** (`/tools/daily-card`), not under a surface named "King's Tickets"
(that name has never existed in code). And **"King's Wisdom" was never a shipped label** — the
internal name was **"Kings Wisdomism"**, built 2026-10-04 and **renamed to Green Light the same day**.
Nothing was deleted; the pieces exist but are **not wired into the single flow** you picture
(Discover → Green Light → editable ticket). That wiring, plus a persistent ticket record with full
provenance, is the real gap.

---

## 1. Green Light (the research-assembly layer) — EXISTS

- Route `/tools/green-light` → `green_light_tool()` `app.py:44075`; builder `build_green_light()`
  `app.py:31593`; template `templates/green_light.html`. Premium-gated (`app.py:736`).
- It is a **convergence / lens-COUNTING engine**, explicitly *not* a ranked best-bets list and *not*
  a ticket assembler. For each featured NFL player's primary over it counts up to **5 independent
  lenses** (Opportunity, Matchup, Game Identity, Coaching, Concentration), groups into tiers by
  convergence count, and labels market-state as **context only (never a sort input)**. Honest
  disclaimer baked into the template.
- Feeds: `build_nfl_usage_board`, `_nfl_wisdom_props`, `_nfl_game_scripts`, coaching/concentration
  lens JSON, and the shared `services.nfl_inclusion` verdict (same predicate as Player Check).

## 2. "Kings Wisdomism" → Green Light — RENAMED, not removed

Git lineage: `8529bf9`/`90b3135` (2026-10-03 briefs) → **`896a5a0` 2026-10-04 "feat: Kings Wisdomism
convergence engine + page (/tools/wisdomism)"** → **`0291393` 2026-10-04 "rename → Green Light
(/tools/green-light)"**. `/tools/wisdomism` no longer exists; residual "Wisdomism" strings remain in
comments + the Green Light empty-state. `docs/kings_wisdomism_engine.md` (the concept brief) proposed
a **ranked best→good independent shortlist** (one leg per game) with a **mandatory line-delta gate**
and an optional **"render as card"** into the Daily Card. **Built:** the convergence lens-counting
(as Green Light). **NOT built:** the ranked shortlist, the line-delta gate as a sort input, and the
render-into-ticket handoff.

## 3. Editable 2–5-leg tickets — LIVE in Daily Cards

- Route `/tools/daily-card` → `daily_card_tool()` `app.py:32630`; builder `build_daily_cards(sizes=
  (3,4,5),…)` `app.py:32430` drawing from `_card_pools()` `app.py:32252`; template
  `templates/daily_cards.html`. Cross-game, one leg per game, floors + swing(s).
- **Editing that already works (client-side):** per-leg **Swap** via a modal chooser drawing from a
  server `bench` pool that excludes games already on the card (`daily_cards.html:116,123,183`;
  `build_daily_cards` returns `bench` `app.py:32488`); whole-card **Reroll** (`daily_cards.html:107`);
  size **2↔5** regeneration via the Sizes control; live **reprice** of combined odds + payout on every
  edit (`daily_cards.html:146`).
- **Born** `0696695` (2026-10-01); swap control `d001c23`; user-directed swap chooser `84fcdf3`
  (2026-10-11). **Nothing later removed or restructured** — present in `master`.
- **Missing primitives** if the restored "King's Tickets" needs them: in-card **add / remove /
  reorder** (today: fixed N with per-slot swap + reroll + size regen); and **persistent saved-ticket
  storage** — today a card only renders to a **PNG** (`/tools/daily-card.png` `app.py:33130`); the
  legs are never stored as a ticket record.
- **Lines:** current board numbers with real historical hit rates, **price only — no book, no
  timestamp, no event id, no quote-scope** per leg (`app.py:32275`).

## 4. The Menu & Parlay Builder

- **The Menu** `/tools/menu` → `menu_board_tool()` `app.py:32647`; `build_menu_board()` `app.py:32306`
  — the full candidate pool grouped by game ("build your own by eye"), same `_card_pools` source;
  pick legs → live slip → save as the card PNG.
- **Parlay Builder** `/parlay` → `parlay()` `app.py:41334` (NBA-centric board; `/parlay-builder`
  redirects here). Saved-ticket schema (`save_parlay()` `app.py:41504`) carries per leg sport/player/
  team/stat/line/direction/**book**/market_price/model_prob/ev — but **no per-leg timestamp, no event
  id, no quote-scope**; ticket-level `SavedAt` only; combined odds computed, not stored. Up to 20 legs;
  carries the OOS all-parlay honesty warnings.

## 5. Discovery feeds (all exist as independent dict-returning builders — reusable)

Hot Hand Heat Map (`/tools/nfl-heatmap`, `build_nfl_hot_hand`) · Wave Watch ATS (`/tools/nfl-wave`,
`build_nfl_wave_watch_context`) · Riding the Wave (`/tools/riding-the-wave`, `build_nfl_wave_context`)
· **Milestone Streaks** (`/tools/nfl-milestones`, `build_nfl_milestone_streaks`) · NFL Spots
(`/tools/nfl-spots` — now thin: PropScore removed by containment, only wind-unders + injury-timing) ·
NFL Totals (Wind) (`/tools/nfl-totals-today`) · ATS (`/tools/nfl-ats`, `/tools/nfl-team`) · injuries
(`build_nfl_injury_changes`) · weather (folded into totals/wind) · matchup (`/tools/nfl-matchup`,
`-matchup-edge`, `-dvp`). Plus **Bet Tracker** (`/tools/tracker`, `services.bet_tracker`, real CLV
record) and the dark **Decision Journal** (`/journal`, flag OFF).

## 6. Navigation & naming problems

- Nav lives in `templates/_sidebar.html` (HTML, not a Python table). Under **"Build · the ticket"**:
  Green Light (`:54`), **Today's Cards** (`:58`), The Menu (`:62`).
- **"NFL Spots"** (`_sidebar.html:135` → `/tools/nfl-spots`) is thin after containment — wind-unders +
  injury-timing only. (A prior directive wanted it renamed **NFL Matchup Center** and made honest.)
- **"NFL Totals (Wind)"** (`_sidebar.html:141` → `/tools/nfl-totals-today`). (Prior directive wanted
  **NFL Game Totals (Over/Under)**.)
- **"King's Wisdom" / "King's Tickets" appear in NO nav** (never shipped labels). `bk_base.html` rail
  has Props / Parlay Builder / Review Center only.

## 7. User-preference data (exists)

`data/user_prefs/{uid}.json`: card prefs (`DEFAULT_CARD_PREFS = sizes[3,4,5]/risk/legs/timeframe`,
`app.py:32189`) under key `card`; **home-view archetype** (`HOME_VIEWS`, 5 archetypes →
surface+copy, `app.py:32550`) under key `home`; onboarding `seen_start`. **No lens-ordering
preference exists** — Green Light's lens order is hard-coded. Tied to signed-in `user_id`.

## 8. Restoration boundaries

**Restorable from existing components (no new contract):** Green Light engine; the Daily Card
editable-card UI (swap/reroll/resize/reprice + bench pool); The Menu build-your-own board; every
discovery feed (all return dicts).

**Needs a NEW, governed contract (a decision, not a code revert):**
1. **A persistent ticket record with full per-leg provenance** — event id, player/team, market+side,
   exact line, individual price **when the book gave one**, book, **quote_scope (individual vs
   combined)**, source/capture timestamp, and **decision-source (user-selected / BK-assembled /
   both)**. Current structures lack it (Daily Card: price only; Parlay: no timestamp/event/scope).
   This is the same contract the frozen Decision Journal record spec + your Oct 18 fixture already
   describe — they should share one leg-provenance model.
2. **The Green Light → editable-ticket handoff** — today Green Light emits ranked lens-count plays but
   **no code path converts a Green Light play into a Daily Card / Menu leg**; the card pools pull
   independently from `build_nfl_floor_board`. Wiring that flow (and preserving the "game story" +
   which tool contributed each leg) is net-new.
3. **Combined price kept separate from leg prices, and stored** — today reprice is client-side and
   never persisted; no combined-odds field exists. Never invent per-leg prices where only a combined
   price was given.
4. **In-card add / remove / reorder + reuse the winning parts of a losing ticket** — new UI/record
   affordances beyond today's swap/reroll.
5. **The brief's ranked shortlist + mandatory line-delta gate** — Green Light deliberately does NOT
   rank by goodness or let market-state drive order; restoring that vision is a product-contract
   change, governed by the do-not-build rails (no composite score / lock / auto-EV / Kelly).

**Flags:** no `GREEN_LIGHT_ENABLED` / `KINGS_TICKET_*` flag (Green Light gated only by the premium
route list). `DECISION_JOURNAL_ENABLED` OFF, `LOOKUP_CHANGE_ENABLED` OFF.

---

## Proposed reversible restoration sequence (for your approval — NOT started)

- **B1** — Rename nav to bettor-recognizable labels (NFL Spots → NFL Matchup Center; NFL Totals →
  NFL Game Totals (Over/Under)); make NFL Matchup Center honestly identify its modules + abstain where
  data is missing. One reversible commit, no data-model change.
- **B2** — Persistent **King's Ticket record** = the shared leg-provenance contract (reuse the frozen
  Decision Journal model), feature-flagged dark. Record only; no UI behavior change.
- **B3** — **Green Light → ticket handoff**: a Green Light play (and a Menu/discovery leg) becomes an
  editable card leg carrying its game story + contributing tool + provenance; in-card add/remove/
  reorder; combined price stored separate from leg prices; "what worked inside a loss" reuse.
- **B4** — Green Light as a **preference-driven workspace** (user chooses which factual lenses matter;
  order/visibility only, never hidden confidence), owner default preserved.

Each gates separately; the Oct 18 ticket history is the private, account-bound acceptance fixture
(never committed to this public repo).
