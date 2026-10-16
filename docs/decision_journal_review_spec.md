# Decision Journal & Review — Specification (read-only)

**Status: SPECIFICATION ONLY. No code, no UI, no model tuning, no recommendations, no confidence
scoring, no implementation.** Produced per the Director's directive to turn recent results — the wins
*and* the earlier misses — into evidence the product can learn from. Roadmap position: step 2 (after
CFB Gate 1; before the NFL/NBA prop-capture spec). We currently know whether a ticket won; we do
**not** know which reasoning produced the result. This spec defines the record that closes that gap.

Governing principle: **the journal records decisions and reasons; the review reports what happened by
reason. Nothing here tunes a model, makes a recommendation, or assigns a system authority score.**
Confidence, if entered, is the user's personal judgment — never a model number.

**Approved disposition:** with the Rev 3 corrections applied, this specification is **approved** and
the **implementation-design gate opens automatically** — no further substantive review cycle. That
gate is a *separate* authorization: it still builds no code here, and it must first resolve the open
storage-design question in §8 before any store is declared authoritative. The central design
constraint carried into that gate: **the journal must never manufacture precision a sportsbook ticket
did not provide** — unknown stays unknown, and the book's settlement is authoritative.

Date: 2026-10-16. Revision: 3 (five data-contract corrections + one reporting safeguard — see §9).

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
| **selection origin** (user-selected / BK-rule-assembled) | ❌ | missing |
| **entry method** (manual / sportsbook-import / BK-builder / migration) | ❌ | missing |
| **pre-bet review** (did the user deliberately review this leg) | ❌ | missing |
| **record provenance** (prospective vs historical vs reconstructed vs legacy) | ❌ | missing |
| **leg structure** (parlay → legs) | ❌ | a parlay is one flat entry; no leg result vs ticket result |
| **reason** (streak/coaching/effort/matchup/injuries/pace…) | ❌ | missing |
| **book settlement** (cash/promo stake, total returned, cashout, book note) | ❌ | only `stake` + win/loss — no authoritative settlement |
| **confidence** (optional, personal) | ❌ | missing |

**Verdict:** a usable foundation for price/stake/result/CLV, but it cannot answer "which reasoning
produced the result." The Journal **extends** this record; it does not replace it. **Migration rule:**
an existing entry that genuinely was a single straight bet migrates as a one-leg ticket
(`entry_method = migration`, `record_provenance = legacy-flat`); an existing **parlay or multi-leg**
entry is **preserved intact as a `legacy_flat_ticket`** (ticket-level result and stake known,
individual legs marked unreconstructed) and is **not** flattened into a single leg. Legs are only
populated when they are actually reconstructable from the record; otherwise they stay unknown.
**Storage is NOT decided here** — see §8.

---

## 2. The canonical decision observation

Mirrors the Wave Watch canonical observation (`docs/wave_watch_data_diagnostic_spec.md`): **a decision
is recorded leg-by-leg, with the line and price captured at decision time, before the game — where the
ticket actually provides them.** The unit is one **leg**; a **ticket** is one or more legs. A value
that is not known is recorded as **unknown / null — never inferred or back-filled**.

### 2a. Leg (the atomic record)
| Field | Required | Meaning |
|---|---|---|
| `selection_origin` | ✅ | **user-selected / BK-rule-assembled / unknown** — *who produced the pick*. NOT a channel: a user's own pick entered from a sportsbook slip is still `user-selected` (correction 1) |
| `entry_method` | ✅ | **manual / sportsbook-import / BK-builder / migration** — *how the record got into the journal*, independent of who originated the pick (correction 1) |
| `bk_surfaces_consulted` | ✅ (may be empty) | which BK surfaces were looked at for this leg — a list (Wave Watch, ATS Streaks, Matchup, Heat Map, Daily Card, …); **empty list is valid and distinct from "unknown"** |
| `user_reviewed_before_bet` | ✅ | **yes / no / unknown** — did the user *deliberately review this specific leg* before placing. Placing a ticket already implies acceptance, so acceptance is not the signal; **deliberate review of the leg** is (correction 2) |
| `sport` | ✅ | NBA / NFL / CFB / … |
| `game` | ✅ | event (teams + date; an id where available) |
| `player` | prop only | subject of a player prop |
| `market` | ✅ | side/total/spread, or the prop stat (Rec Yds, Points…) |
| `line` | ✅ if known | the number **as captured at decision time** (unknown if not captured — never inferred) |
| `quote_scope` | ✅ | **individual-leg / combined-ticket / unavailable** — whether an independent price actually existed *for this leg*. Same-game/correlated parlays frequently price only the combined ticket (correction 4) |
| `price` | ✅ **only when `quote_scope = individual-leg`** | American odds for this leg at decision time. **Not required — and not fabricated — when the leg had no independently offered price** (correction 4) |
| `book` | ✅ | sportsbook, or a defined consensus source |
| `decision_time` | ✅ for prospective; may be absent for historical | timestamp the line/price were seen — **must precede kickoff/tip** for a prospective record. A historical record may lack a valid pregame `decision_time` (see `record_provenance`, §2b) and is then excluded from prospective comparisons (correction 3) |
| `leg_rationale` | optional | free-text *why this leg* — **frozen at `decision_time`, before the event** (prospective records only) |
| `reason_tags` | ✅ | one or more: `streak` · `coaching` · `effort` · `matchup` · `injuries` · `pace/game-env` · `line-value` · `model` · `other`. Tags **overlap** — a leg may carry several, and the review must disclose that (§4 safeguard) |
| `confidence` | optional | the user's personal 1–5 judgment, **labeled "your read, not a system score"** |
| `alt_line` / `alt_price` | optional | an alternate line considered (for the alt-line review) |
| `leg_result` | settle | **objective, as the book graded it:** win / loss / push / void |
| `read_happened` | settle, optional | **objective, separate from the ticket:** did the underlying event occur (e.g., the player passed the *captured* line) — a factual yes/no, independent of whether the ticket won |

### 2b. Ticket
| Field | Meaning |
|---|---|
| `ticket_id`, `legs[]` | the legs above |
| `ticket_type` | straight (1 leg) / parlay (≥2) / same-game-parlay (correlated) / `legacy_flat_ticket` (migrated multi-leg, legs unreconstructed) |
| `record_provenance` | **prospective-captured / historical-documented / historical-reconstructed / legacy-flat** — how trustworthy the record's timing is. Only **prospective-captured** records (pregame `decision_time` present) enter the **prospective decision-quality** comparisons of §4; historical and reconstructed records remain usable as **history** but are reported separately and never mixed into the prospective sample (correction 3) |
| `game_thesis` | ticket-level free-text thesis, **frozen at decision time, before the event** (prospective records only) |
| `combined_price` | the book's **actual offered ticket odds / payout price**. A real payout, **not** an estimate — **no "assumes independence" caveat**. The independence caveat applies *only* to a combined *probability* figure obtained by multiplying leg probabilities; if such a probability is ever displayed, only that figure is labeled "assumes independence" |
| **settlement block** (book-authoritative) | the sportsbook's settlement is **authoritative** (correction 5): `book_ticket_result` (the book's own win/loss/push/void/cashout grade), `cash_stake`, `promotional_stake` (free-bet / bonus wager), `total_returned`, `cashout_amount` (if cashed out early), `book_settlement_note` (house-specific grading, void re-pricing, promo rules). `net_cash_pl` (derived) is computed **only when the cash inputs support it**; otherwise it is **unavailable** |
| `placed` / `settled` | timestamps |
| `thesis_correct` | settle, optional — **an explicitly SUBJECTIVE user judgment**: "did your thesis play out, in your own assessment?" The user's call, recorded as the user's opinion, **never silently computed from objective results**. Its objective counterpart is the per-leg `read_happened` / `leg_result`, kept separate |

**Ticket result is the book's, not a derived rule (correction 5).** We do **not** universally assert
"a parlay loses if any leg loses" — cashouts, promos, void re-pricing and house-specific grading break
that. `book_ticket_result` records what the book actually settled; a derived view may *explain* it
(e.g., "leg 3 lost") but never *overrides* it. **Push/void** is recorded at the leg level and reflected
in the book's settlement and the actual `total_returned`, not an assumed re-price.

---

## 3. Origin, entry, review, consultation — the spine of the review

The old single "You / BK / Both" field conflated several distinct questions. It is replaced by four
independent fields, because each answers something the others cannot:

- **`selection_origin`** — *who produced the pick*: the user (`user-selected`), a BK rule/board
  (`BK-rule-assembled`), or unknown. This is about authorship, **not** how it was entered.
- **`entry_method`** — *how the record reached the journal*: `manual`, `sportsbook-import`,
  `BK-builder`, or `migration`. A user's own pick can arrive by `sportsbook-import`; the two are
  orthogonal (correction 1).
- **`user_reviewed_before_bet`** — *whether the user deliberately reviewed that specific leg* before
  placing (yes / no / unknown). Acceptance is implied by placing the ticket; the signal is deliberate
  review (correction 2).
- **`bk_surfaces_consulted[]`** — *what BK information was looked at* for that leg (possibly none).
  Consulting a surface is not the same as the surface originating the pick.

Together these let the review honestly distinguish, e.g., "a BK-rule-assembled leg the user did **not**
deliberately review, imported from the book" from "a user-selected leg the user reviewed that consulted
nothing" — distinctions the old 3-way label silently erased.

---

## 4. The review (what it answers — reporting only, no tuning)

All computed from the recorded legs/tickets; no weights change. Every record is split along the spine
fields of §3, and **only `record_provenance = prospective-captured` records enter the prospective
decision-quality comparisons** — historical/reconstructed records are reported separately as history
(correction 3).

1. **By selection origin** — W/L/push and net-cash P/L for `user-selected` vs `BK-rule-assembled`.
2. **By pre-bet review** — within each origin, split by `user_reviewed_before_bet` (did deliberately
   reviewing the leg change the realized record?).
3. **By surfaces consulted** — record when a given BK surface was in `bk_surfaces_consulted` vs not.
4. **Straight vs parlay vs same-game parlay** — each cut above, split by `ticket_type`.
5. **Performance by reason and by market** — hit rate + P/L grouped by `reason_tags` and by `market`.
6. **Breaker legs** — within tickets the book settled as losses, the legs that lost while the rest
   won: which `reason` / `market` / `origin` recur. (Explains the book's result; never overrides it.)
7. **Alternate-line value** — where `alt_line`/`alt_price` were recorded: did the alternate line's
   realized hit rate improve **enough to justify its price**?
8. **Read-happened-despite-loss** — for losing tickets, how many legs' objective `read_happened` were
   true (the event occurred even though the ticket lost) — so a correct process behind a lost ticket is
   visible, per the doctrine's "good decisions ≠ good outcomes." (Objective; the user's *subjective*
   `thesis_correct` is reported separately and never conflated with it.)

**P/L & ROI rules.** Reported P/L is the **book-authoritative `net_cash_pl`** (from the §2b settlement
block), computed only where the cash inputs support it. Where settlement or an individual-leg price is
**not recorded**, P/L is **"unavailable"** alongside the plain **W / L / push** record — **never**
fabricated from an assumed −110. An assumed-price figure may appear **only** as an explicitly labeled
**separate sensitivity calculation**, never as the bettor's recorded P/L.

**Reporting safeguards (new, mandatory).** Every breakdown in §4:
- **displays its sample size (n)** beside each cell/row — no rate without its denominator;
- **discloses overlapping reason tags** — because a leg can carry several tags, the per-tag cuts are
  **not** mutually exclusive and their counts do not sum to the total; the report says so explicitly;
- **presents differences as descriptive, not causal** — a gap between two cuts is "what the record
  shows," never "what works." No causal or recommending language, consistent with doctrine (small,
  overlapping, observational samples cannot establish cause).

---

## 5. Seeding the initial sample (the ~10 shown tickets)

- Enter the ~10 tickets already shown as the **initial historical sample** — `record_provenance =
  historical-documented` where the screenshot shows the facts, `historical-reconstructed` where a
  value had to be recovered. They are **excluded from the prospective comparisons** (§4) and reported
  only as history (correction 3).
- Mark each leg's `selection_origin`, `entry_method`, `bk_surfaces_consulted`, and
  `user_reviewed_before_bet` **honestly**.
- **These tickets lack individual leg prices**, and several are correlated same-game parlays with only
  a combined ticket price. Set `quote_scope` accordingly (`combined-ticket` or `unavailable`) and
  record each unknown leg `price` as **unknown / null — never inferred** (correction 4). Record the
  book's `combined_price` and settlement only where the screenshot actually shows them.
- **Do not tune anything from these ten** — far too small, several values unknown, timing not pregame.
  They are a worked example of the schema, not evidence.

## 6. Prospective protocol (how the journal is actually used)

- Log **~30–50 decisions prospectively** (`record_provenance = prospective-captured`), with **every
  available line/price captured *before* the game** (`decision_time` must precede kickoff/tip; a line
  entered after the result is invalid data) and the **book's actual settlement recorded after** (cash
  and promo stake, total returned, cashout, book note).
- **Weekly review** of §4 — **without changing any weight, threshold, or model**.
- Only after the prospective sample shows a **repeated, specific tendency** do we consider a
  **controlled diagnostic** (step 7 of the roadmap) — and even then, out-of-sample or it does not
  count.

---

## 7. Governance (hard limits)
- **No model tuning, no recommendations, no confidence scoring, no implementation** in this phase.
- `confidence` is the user's **personal** read, never surfaced or used as a system authority number.
- `thesis_correct` is the user's **subjective** judgment and is labeled as such — never computed from
  objective results, never presented as objective fact.
- **The book's settlement is authoritative** — ticket results, pushes, voids, cashouts and promos come
  from what the sportsbook actually settled, never from a universal derived rule (correction 5).
- **No manufactured precision.** Unknown fields stay unknown; `price` is recorded only where an
  individual-leg quote existed; P/L comes from actual settlement, and an assumed-price figure appears
  only as a labeled sensitivity (corrections 4 & 5).
- **No causal claims.** Every breakdown shows its sample size, discloses overlapping reason tags, and
  frames differences descriptively — never as proof that a reason "works" (reporting safeguard).
- **Provenance is honored** — reconstructed/historical records never enter the prospective
  decision-quality comparisons (correction 3).
- The journal **learns by reporting**; it never auto-adjusts the product. Any product change is a
  separate, separately-approved gate.
- Relationship to Gate 2: the Journal's leg observation and the prop-capture canonical observation
  share the same bar (decision-time line + price + source + timestamp + push handling) — the Journal
  can begin with **team ATS and straight bets now** (fully gradeable) while player-prop legs wait on
  the Gate 2 capture, exactly as the staged capability in the Wave spec.

---

## 8. Open implementation-design question — storage (NOT frozen)

This spec defines the *record*, not where it lives. **Per-user JSON is explicitly NOT yet adopted as
the authoritative store.** Before the implementation-design gate commits to any store, it must resolve:

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
is decided **at the implementation-design gate**, with its concurrency/atomicity/migration design,
before any record is written.

---

## 9. Changelog

### Rev 3 (five data-contract corrections + one reporting safeguard)
1. **Origin ≠ channel.** `selection_origin` is now *who produced the pick*
   (user-selected / BK-rule-assembled / unknown); the new **`entry_method`** (manual /
   sportsbook-import / BK-builder / migration) carries *how the record was entered*. `imported` is no
   longer an origin. (§1, §2a, §3)
2. **`user_agreed_before_bet` → `user_reviewed_before_bet`.** Placing a ticket already implies
   acceptance; the useful signal is deliberate review of the specific leg. (§2a, §3, §4)
3. **Record provenance** added (prospective-captured / historical-documented / historical-reconstructed
   / legacy-flat). Historical records may lack a pregame `decision_time`; they stay usable as history
   but are **excluded from prospective decision-quality comparisons**. (§2a, §2b, §4, §5)
4. **Combined-ticket-only quotes supported.** New `quote_scope` (individual-leg / combined-ticket /
   unavailable); `price` required **only** when an individual-leg quote actually existed, so correlated
   same-game parlays are not forced to invent per-leg prices. (§2a, §5)
5. **Book settlement is authoritative.** No universal "parlay loses if any leg loses" rule. Record
   `book_ticket_result`, `cash_stake`, `promotional_stake`, `total_returned`, `cashout_amount`,
   `book_settlement_note`; derive `net_cash_pl` only when the inputs support it. (§2b, §4, §7)
6. **Reporting safeguard.** Every breakdown must show sample size (n), disclose overlapping reason
   tags, and present differences descriptively — never as causal evidence. (§4, §7)

### Rev 2 (eight factual corrections)
`combined_price` = actual payout, no independence caveat (1); missing-price ROI "unavailable", −110
only as a labeled sensitivity (2); old parlays preserved as `legacy_flat_ticket`, not flattened (3);
`decision_source` split into origin / surfaces-consulted / agreement (4 — superseded by Rev 3 #1–2);
`game_thesis` + `leg_rationale` frozen pre-event, `thesis_correct` explicitly subjective (5);
actual-settlement block, ROI from settlement (6 — expanded by Rev 3 #5); seed-ticket unknowns kept
unknown (7); storage not frozen (8).

## 10. Out of scope here
No schema is implemented, no UI is built, no `bet_tracker.py` change is made, and **no storage is
chosen**. With Rev 3 applied, the specification is approved and the implementation-design gate opens —
this document is the contract that gate builds against.
