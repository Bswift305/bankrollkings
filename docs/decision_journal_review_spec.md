# Decision Journal & Review — Specification (read-only)

**Status: SPECIFICATION ONLY. No code, no UI, no model tuning, no recommendations, no confidence
scoring, no implementation.** Produced per the Director's directive to turn recent results — the wins
*and* the earlier misses — into evidence the product can learn from. Roadmap position: step 2 (after
CFB Gate 1; before the NFL/NBA prop-capture spec). We currently know whether a ticket won; we do
**not** know which reasoning produced the result. This spec defines the record that closes that gap.

Governing principle: **the journal records decisions and reasons; the review reports what happened by
reason. Nothing here tunes a model, makes a recommendation, or assigns a system authority score.**
Confidence, if entered, is the user's personal judgment — never a model number.

Date: 2026-10-16.

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
| **decision source** (You / BK / Both) | ❌ | missing |
| **leg structure** (parlay → legs) | ❌ | a parlay is one flat entry; no leg result vs ticket result |
| **reason** (streak/coaching/effort/matchup/injuries/pace…) | ❌ | missing |
| **BK information consulted** | ❌ | missing |
| **confidence** (optional, personal) | ❌ | missing |

**Verdict:** a usable foundation for price/stake/CLV/result, but it cannot answer "which reasoning
produced the result." The Journal **extends** this record (same per-user JSON store); it does not
replace it, and existing bets migrate as single-leg decisions with `source` unknown until edited.

---

## 2. The canonical decision observation

Mirrors the Wave Watch canonical observation (`docs/wave_watch_data_diagnostic_spec.md`): **a decision
is recorded leg-by-leg, with the line and price captured at decision time, before the game.** The unit
is one **leg**; a **ticket** is one or more legs.

### 2a. Leg (the atomic record)
| Field | Required | Meaning |
|---|---|---|
| `decision_source` | ✅ | **You / Bankroll Kings / Both** — who produced this leg's read |
| `sport` | ✅ | NBA / NFL / CFB / … |
| `game` | ✅ | event (teams + date; an id where available) |
| `player` | prop only | subject of a player prop |
| `market` | ✅ | side/total/spread, or the prop stat (Rec Yds, Points…) |
| `line` | ✅ | the number **as captured at decision time** |
| `price` | ✅ | American odds for this leg at decision time |
| `book` | ✅ | sportsbook, or a defined consensus source |
| `decision_time` | ✅ | timestamp the line/price were seen — **must precede kickoff/tip** |
| `reason_tags` | ✅ | one or more: `streak` · `coaching` · `effort` · `matchup` · `injuries` · `pace/game-env` · `line-value` · `model` · `other` |
| `bk_surfaces_consulted` | ✅ (may be none) | which BK surfaces informed it (Wave Watch, ATS Streaks, Matchup, Heat Map, Daily Card, …) — a list, "none" is valid |
| `confidence` | optional | the user's personal 1–5 judgment, **labeled "your read, not a system score"** |
| `alt_line` / `alt_price` | optional | an alternate line considered (for the alt-line review) |
| `leg_result` | settle | win / loss / push / void |
| `thesis_correct` | settle, optional | did the underlying read happen (e.g., the player went over the *captured* line) **independent** of the ticket result |

### 2b. Ticket
| Field | Meaning |
|---|---|
| `ticket_id`, `legs[]` | the legs above |
| `ticket_type` | straight (1 leg) / parlay (≥2) |
| `stake`, `combined_price` | combined price labeled "assumes independence" (per the house honesty rule) |
| `ticket_result` | win / loss / push / void (a parlay loses if **any** leg loses) |
| `placed` / `settled` | timestamps |

**Push/void handling** is explicit at the leg level (a push is money back, not a loss) and propagates
to the ticket (a parlay re-prices around a pushed leg). Same rule as the prop-capture canonical
observation.

---

## 3. Decision source — the spine of the review

Every leg is **You**, **Bankroll Kings**, or **Both**:
- **You** — your own read (eye test: effort, coaching, play-calling), *not* taken from a BK surface.
- **Bankroll Kings** — taken from a BK surface (the leg existed on Wave Watch / a board / the Daily
  Card) and you followed it.
- **Both** — your read **and** a BK surface agreed.

This is what lets the review separate your standalone record from the site's from the combination —
the whole point of the journal.

---

## 4. The review (what it answers — reporting only, no tuning)

All computed from the recorded legs/tickets; no weights change.
1. **Your standalone record** — legs/tickets where `decision_source = You`: W/L/push, price-adjusted
   ROI where the recorded price supports it (else −110-assumed, disclosed), CLV.
2. **Site-generated record** — `decision_source = Bankroll Kings`.
3. **Combined-decision record** — `decision_source = Both`.
4. **Straight bets vs parlays** — each of the three records, split by ticket type.
5. **Performance by reason and by market** — hit rate + ROI grouped by `reason_tags` and by `market`
   (which reasons and which markets actually produce results, and for which source).
6. **Breaker legs** — within tickets that lost, the legs that lost while the rest won: which
   `reason` / `market` / `source` repeatedly break otherwise-correct tickets.
7. **Alternate-line value** — where `alt_line`/`alt_price` were recorded: did the alternate line's
   realized hit rate improve **enough to justify its price**? (compare realized hit rate + price vs the
   taken line).
8. **Thesis-correct-despite-loss** — for losing parlays, how many legs' `thesis_correct` were true
   (the read happened even though the ticket lost) — so a correct process behind a lost ticket is
   visible, per the doctrine's "good decisions ≠ good outcomes."

---

## 5. Seeding the initial sample (the 10 shown tickets)

- Enter the ~10 tickets already shown as the **initial historical sample**, each leg's
  `decision_source` marked **honestly** (You / BK / Both), with the line/price **as they actually
  were at decision time** where known (flag any reconstructed value).
- **Do not tune anything from these ten** — the sample is far too small, and some lines are
  reconstructed rather than captured. They are a worked example of the schema, not evidence.

## 6. Prospective protocol (how the journal is actually used)

- Log **~30–50 decisions prospectively**, with **every line and price captured *before* the game**
  (the `decision_time` must precede kickoff/tip; a line entered after the result is invalid data).
- **Weekly review** of §4 — **without changing any weight, threshold, or model**.
- Only after the prospective sample shows a **repeated, specific tendency** do we consider a
  **controlled diagnostic** (step 7 of the roadmap) — and even then, out-of-sample or it does not
  count.

---

## 7. Governance (hard limits)
- **No model tuning, no recommendations, no confidence scoring, no implementation** in this phase.
- `confidence` is the user's **personal** read, never surfaced or used as a system authority number
  (it would violate the do-not-build "universal score" rule otherwise).
- The journal **learns by reporting**; it never auto-adjusts the product. Any product change is a
  separate, separately-approved gate.
- Relationship to Gate 2: the Journal's leg observation and the prop-capture canonical observation
  share the same bar (decision-time line + price + source + timestamp + push handling) — the Journal
  can begin with **team ATS and straight bets now** (fully gradeable) while player-prop legs wait on
  the Gate 2 capture, exactly as the staged capability in the Wave spec.

---

## 8. Out of scope here
No schema is implemented, no UI is built, no `bet_tracker.py` change is made. This document is the
specification to review before any Decision Journal implementation gate opens.
