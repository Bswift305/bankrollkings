# Decision Journal & Review — Specification (read-only)

**Status: SPECIFICATION ONLY. No code, no UI, no model tuning, no recommendations, no confidence
scoring, no implementation.** Produced per the Director's directive to turn recent results — the wins
*and* the earlier misses — into evidence the product can learn from. Roadmap position: step 2 (after
CFB Gate 1; before the NFL/NBA prop-capture spec). We currently know whether a ticket won; we do
**not** know which reasoning produced the result. This spec defines the record that closes that gap.

Governing principle: **the journal records decisions and reasons; the review reports what happened by
reason. Nothing here tunes a model, makes a recommendation, or assigns a system authority score.**
Confidence, if entered, is the user's personal judgment — never a model number.

**Approved disposition:** once these corrections are applied, the Decision Journal is the **next
implementation gate**. That gate is a *separate* authorization — it still builds no code here, and it
must first resolve the open storage-design question in §8 before any store is declared authoritative.

Date: 2026-10-16. Revision: 2 (eight factual corrections applied — see §9 changelog).

---

## 1. Inventory of the existing tracker (the starting point)

`services/bet_tracker.py` — per-user JSON at `data/user_bets/<uid>.json`, pure JSON, no network. One
flat **bet** record (`add_bet`):

| Field | Present | Note |
|---|---|---|
| `id`, `sport`, `result` (pending/win/loss/push), `stake` | ✅ | basic log |
| `odds` (American **price**) | ✅ | the price |
| `closing_odds` → CLV (`_clv_points`) | ✅ | closing-line value supported |
| `placed` (date) + `logged` (UTC datetime) | ~ | a **date**, not a decision-time; no proof the line was captured *before* the game |
| `description`, `selection` (free text ≤140) | ~ | **unstructured** — no distinct game / player / market / line |
| **selection origin** (user-selected / rule-assembled / imported) | ❌ | missing |
| **information consulted** (which BK surfaces) | ❌ | missing |
| **agreement** (did the user endorse it before the bet) | ❌ | missing |
| **leg structure** (parlay → legs) | ❌ | a parlay is one flat entry; no leg result vs ticket result |
| **reason** (streak/coaching/effort/matchup/injuries/pace…) | ❌ | missing |
| **actual financial settlement** (returned amount, bonuses, partial cashout) | ❌ | only `stake` + win/loss — no recorded payout |
| **confidence** (optional, personal) | ❌ | missing |

**Verdict:** a usable foundation for price/stake/result/CLV, but it cannot answer "which reasoning
produced the result." The Journal **extends** this record; it does not replace it. **Migration rule
(correction 3):** an existing entry that genuinely was a single straight bet migrates as a one-leg
ticket; an existing **parlay or multi-leg** entry is **preserved intact as a `legacy_flat_ticket`**
(ticket-level result and stake known, individual legs marked unreconstructed) and is **not** flattened
into a single leg. Legs are only populated when they are actually reconstructable from the record;
otherwise they stay unknown. **Storage is NOT decided here** — see §8.

---

## 2. The canonical decision observation

Mirrors the Wave Watch canonical observation (`docs/wave_watch_data_diagnostic_spec.md`): **a decision
is recorded leg-by-leg, with the line and price captured at decision time, before the game.** The unit
is one **leg**; a **ticket** is one or more legs. A value that is not known is recorded as **unknown /
null — never inferred or back-filled** (correction 7).

### 2a. Leg (the atomic record)
| Field | Required | Meaning |
|---|---|---|
| `selection_origin` | ✅ | **user-selected / rule-assembled / imported / unknown** — *how this leg came to be on the ticket* (not who was "right"). Separate from what was consulted and from whether the user agreed (correction 4) |
| `bk_surfaces_consulted` | ✅ (may be empty) | which BK surfaces were looked at for this leg — a list (Wave Watch, ATS Streaks, Matchup, Heat Map, Daily Card, …); **empty list is valid and distinct from "unknown"** |
| `user_agreed_before_bet` | ✅ | **yes / no / unknown** — did the user personally endorse this leg *before* it was placed. Captures "rule-assembled leg I did not personally vet" vs "leg I agreed with" (correction 4) |
| `sport` | ✅ | NBA / NFL / CFB / … |
| `game` | ✅ | event (teams + date; an id where available) |
| `player` | prop only | subject of a player prop |
| `market` | ✅ | side/total/spread, or the prop stat (Rec Yds, Points…) |
| `line` | ✅ | the number **as captured at decision time** (unknown if not captured — never inferred) |
| `price` | ✅ if known | American odds for this leg at decision time. **May be unknown** (the seed tickets lack per-leg prices, §5) — unknown is recorded honestly, never reconstructed |
| `book` | ✅ | sportsbook, or a defined consensus source |
| `decision_time` | ✅ | timestamp the line/price were seen — **must precede kickoff/tip** |
| `leg_rationale` | optional | free-text *why this leg* — **frozen at `decision_time`, before the event** (correction 5) |
| `reason_tags` | ✅ | one or more: `streak` · `coaching` · `effort` · `matchup` · `injuries` · `pace/game-env` · `line-value` · `model` · `other` |
| `confidence` | optional | the user's personal 1–5 judgment, **labeled "your read, not a system score"** |
| `alt_line` / `alt_price` | optional | an alternate line considered (for the alt-line review) |
| `leg_result` | settle | **objective:** win / loss / push / void (how the book graded it) |
| `read_happened` | settle, optional | **objective, separate from the ticket:** did the underlying event occur (e.g., the player passed the *captured* line) — a factual yes/no, independent of whether the ticket won |

### 2b. Ticket
| Field | Meaning |
|---|---|
| `ticket_id`, `legs[]` | the legs above |
| `ticket_type` | straight (1 leg) / parlay (≥2) / `legacy_flat_ticket` (migrated multi-leg, legs unreconstructed) |
| `game_thesis` | ticket-level free-text thesis, **frozen at decision time, before the event** (correction 5) |
| `stake` (= `risk`) | amount risked |
| `combined_price` | the book's **actual offered ticket odds / payout price**. This is a real payout, **not** an estimate — it carries **no "assumes independence" caveat** (correction 1). The independence caveat applies *only* to a combined *probability* figure obtained by multiplying leg probabilities; if such a probability is ever displayed, that figure — and only that figure — is labeled "assumes independence" |
| **settlement block** | `returned` (total amount returned by the book), `profit_loss` (= `returned − risk`), `void_push_treatment` (how pushed/void legs were handled), `bonuses` (free-bet / odds-boost / promo applied), `partial_cashout` (if cashed out early, the amount). **Ticket ROI is computed from this actual settlement — `(returned − risk) / risk` — never from reconstructed odds** (correction 6) |
| `ticket_result` | win / loss / push / void (a parlay loses if **any** leg loses) |
| `placed` / `settled` | timestamps |
| `thesis_correct` | settle, optional — **an explicitly SUBJECTIVE user judgment**: "did your thesis play out, in your own assessment?" It is the user's call, recorded as the user's opinion, and is **never silently computed from objective results** (correction 5). The objective counterpart is the per-leg `read_happened` / `leg_result`, kept separate |

**Push/void handling** is explicit at the leg level (a push is money back, not a loss) and propagates
to the ticket via the settlement block (a parlay re-prices around a pushed leg, and the recorded ROI
reflects the **actual** returned amount, not an assumed re-price). Same rule as the prop-capture
canonical observation.

---

## 3. Origin, consultation, agreement — the spine of the review

The old single "You / BK / Both" field conflated three different questions. It is replaced by three
independent fields (correction 4), because each answers something the others cannot:

- **`selection_origin`** — *how the leg got onto the ticket*: the user picked it themselves
  (`user-selected`), a BK rule/board assembled it (`rule-assembled`), it was imported from a
  sportsbook slip (`imported`), or it is not known (`unknown`).
- **`bk_surfaces_consulted[]`** — *what BK information was looked at* for that leg (possibly none).
  Consulting a surface is not the same as the surface originating the pick.
- **`user_agreed_before_bet`** — *whether the user personally endorsed the leg before placing it*
  (yes / no / unknown).

This separation is what lets the review honestly distinguish, e.g., "a rule-assembled leg the user
did **not** personally vet but that consulted Wave Watch" from "a user-selected leg the user agreed
with that consulted nothing" — distinctions the old 3-way label silently erased.

---

## 4. The review (what it answers — reporting only, no tuning)

All computed from the recorded legs/tickets; no weights change. Every record is split along the three
spine fields of §3 rather than a single You/BK/Both axis.

1. **By selection origin** — W/L/push and ROI for `user-selected` vs `rule-assembled` vs `imported`.
2. **By agreement** — within each origin, split by `user_agreed_before_bet` (did personally endorsing
   the leg change the realized record?).
3. **By surfaces consulted** — record when a given BK surface was in `bk_surfaces_consulted` vs not.
4. **Straight bets vs parlays** — each cut above, split by `ticket_type`.
5. **Performance by reason and by market** — hit rate + ROI grouped by `reason_tags` and by `market`.
6. **Breaker legs** — within tickets that lost, the legs that lost while the rest won: which
   `reason` / `market` / `origin` repeatedly break otherwise-correct tickets.
7. **Alternate-line value** — where `alt_line`/`alt_price` were recorded: did the alternate line's
   realized hit rate improve **enough to justify its price**?
8. **Read-happened-despite-loss** — for losing parlays, how many legs' objective `read_happened` were
   true (the event occurred even though the ticket lost) — so a correct process behind a lost ticket
   is visible, per the doctrine's "good decisions ≠ good outcomes." (This is the *objective* version;
   the user's *subjective* `thesis_correct` is reported separately and never conflated with it.)

**ROI rules (corrections 2 & 6).** ROI is reported from **actual financial settlement** — the ticket's
`returned − risk` over `risk`. Where the settlement (or, for a single leg, the price) is **not
recorded**, ROI is shown as **"unavailable"** alongside the plain **W / L / push** record — it is
**never fabricated from an assumed −110**. A −110 (or any assumed-price) figure may appear **only** as
an explicitly labeled **separate sensitivity calculation** ("if these had been priced at −110…"), and
is **never** presented as the bettor's recorded ROI.

---

## 5. Seeding the initial sample (the ~10 shown tickets)

- Enter the ~10 tickets already shown as the **initial historical sample**, each leg's
  `selection_origin`, `bk_surfaces_consulted`, and `user_agreed_before_bet` marked **honestly**.
- **These tickets lack individual leg prices.** Record each unknown leg `price` as **unknown / null —
  never inferred, estimated, or back-filled** (correction 7). The ticket's `combined_price` and
  settlement are recorded only where the screenshot actually shows them; otherwise unknown.
- **Do not tune anything from these ten** — the sample is far too small, and several values are
  unknown rather than captured. They are a worked example of the schema, not evidence.

## 6. Prospective protocol (how the journal is actually used)

- Log **~30–50 decisions prospectively**, with **every line and price captured *before* the game**
  (the `decision_time` must precede kickoff/tip; a line entered after the result is invalid data) and
  the **actual settlement recorded after** (returned amount, bonuses, partial cashout).
- **Weekly review** of §4 — **without changing any weight, threshold, or model**.
- Only after the prospective sample shows a **repeated, specific tendency** do we consider a
  **controlled diagnostic** (step 7 of the roadmap) — and even then, out-of-sample or it does not
  count.

---

## 7. Governance (hard limits)
- **No model tuning, no recommendations, no confidence scoring, no implementation** in this phase.
- `confidence` is the user's **personal** read, never surfaced or used as a system authority number
  (it would violate the do-not-build "universal score" rule otherwise).
- `thesis_correct` is the user's **subjective** judgment and is labeled as such — never computed from
  objective results and never presented as an objective fact.
- **No fabricated numbers.** Unknown fields stay unknown (§5). ROI comes from actual settlement, and
  an assumed-price ROI only ever appears as a labeled sensitivity (§4), never as the recorded ROI.
- The journal **learns by reporting**; it never auto-adjusts the product. Any product change is a
  separate, separately-approved gate.
- Relationship to Gate 2: the Journal's leg observation and the prop-capture canonical observation
  share the same bar (decision-time line + price + source + timestamp + push handling) — the Journal
  can begin with **team ATS and straight bets now** (fully gradeable) while player-prop legs wait on
  the Gate 2 capture, exactly as the staged capability in the Wave spec.

---

## 8. Open implementation-design question — storage (NOT frozen)

This spec defines the *record*, not where it lives. **Per-user JSON is explicitly NOT yet adopted as
the authoritative store** (correction 8). Before the implementation gate commits to any store, it must
resolve:

- **Concurrency** — the existing flat `data/user_bets/<uid>.json` is a read-modify-write of a whole
  file; two near-simultaneous writes (web + a settlement job) can lose data without a locking or
  append discipline.
- **Atomic writes** — a settlement update must not leave a half-written file on crash (write-temp +
  rename, or a durable store).
- **Migration** — the `legacy_flat_ticket` preservation (§1) and the leg schema need a defined,
  reversible migration path, not an in-place overwrite.
- **Growth / query** — prospective + historical volume and the §4 group-bys may outgrow a per-file
  scan.

The chosen store (per-user JSON with discipline, a single-file DB such as SQLite, or another option)
is decided **at the implementation gate**, with its concurrency/atomicity/migration design, before any
record is written.

---

## 9. Changelog — rev 2 (eight corrections)

1. `combined_price` is the book's **actual payout**, carries **no "assumes independence" caveat**; that
   caveat is reserved for a multiplied-leg **probability** figure only. (§2b)
2. Missing-price ROI is **"unavailable" + W/L/push**, never an invented −110 ROI; assumed −110 is a
   separate **labeled sensitivity**, not the recorded ROI. (§4)
3. Old parlays are preserved as **`legacy_flat_ticket`**, not migrated as single-leg, unless legs are
   genuinely reconstructable. (§1, §2b)
4. Split the old `decision_source` into **`selection_origin`** / **`bk_surfaces_consulted[]`** /
   **`user_agreed_before_bet`**. (§2a, §3, §4)
5. **`game_thesis`** (ticket) + optional **`leg_rationale`** (leg) frozen **before the event**;
   **`thesis_correct`** is **explicitly subjective**, separated from the objective
   `leg_result` / `read_happened`. (§2a, §2b)
6. Added the **actual-settlement block** (risk, returned, profit/loss, void/push treatment, bonuses,
   partial cashout); **ticket ROI from actual settlement**, not reconstructed odds. (§2b, §4)
7. Unknown fields (the seed tickets' per-leg prices) are **kept unknown, never inferred**. (§2a, §5)
8. **Storage is not frozen** — per-user JSON is not yet authoritative; concurrency / atomic-writes /
   migrations / growth are an **open implementation-design question**. (§1, §8)

## 10. Out of scope here
No schema is implemented, no UI is built, no `bet_tracker.py` change is made, and **no storage is
chosen**. This document is the specification to review before the Decision Journal implementation gate
opens.
