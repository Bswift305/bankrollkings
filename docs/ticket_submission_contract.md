# Ticket submission contract (D4)

Frozen by owner decision. Code is the source of truth; this page is the map. QCs:
`qc_ticket_submission_atomic.py`, `qc_ticket_quote_change.py`, `qc_parlay_save_exact.py`.

## 1. Executable ticket range: 2..8 legs

| Legs | Result |
|---|---|
| 1 | rejected, "A ticket needs at least 2 legs" |
| 2..8 | accepted only when every leg is executable and confirmed |
| 9+ | rejected, "A ticket holds at most 8 legs", **never truncated** |

One pair of constants, `TICKET_SUBMIT_MIN_LEGS` / `TICKET_SUBMIT_MAX_LEGS` in `app.py`, enforced by
`_ticket_leg_count_failure` at every boundary:

- `POST /tools/daily-card.png`. This covers the shared editor (Today's Cards, King's Tickets, the Green Light
  proposed ticket) and the Menu slip. Out-of-range counts get `422 wrong_leg_count`.
- The SGP Workbench export / handoff. Out-of-range counts are rejected with reason `leg_count`, and every
  selected leg is kept.

The editor and the Menu JS read the same constants through Jinja globals. The shared editor's
**construction** cap, `TICKET_EDITOR_MAX_LEGS = 5` (the "2-5 leg" King's Tickets product), is a narrower
builder limit inside the contract. Server-built cards (GET) may still be rebuilt before presentation, with
the visible "removed — game started" notice.

## 2. Quote-change atomicity

Every submitted leg carries the quote terms the user saw and confirmed: **sportsbook, event, market,
selection, line, price**. These come from `ticket_quote_terms(leg)`, which is rendered into the page and
sent back verbatim. In the SGP Workbench, the leg id pins book, market, selection and line, and
`cf=<id>~<price>` carries the confirmed price.

At the boundary the confirmed terms are canonicalized and compared with the **current** canonical server
quote:

| Term | Canonicalization (formatting-only differences compare equal) |
|---|---|
| price | whole American odds: `150 == "+150" == "150" == 150.0 == "150.0"` |
| line | float: `-3.5 == "-3.5" == "-3.50"`, `"+3.5" == 3.5` |
| book | `_clean_book`, then NFKC, casefold and strip punctuation/space, then the alias table (`williamhill_us == Caesars`, in parity with `fetch_player_props.BOOKMAKER_TITLES`). Non-book sources canonicalize to `''`. |
| event / market | NFKC, casefold, strip punctuation/space/`_`, numbers respelled (`"QA1 @ QH1" == "qa1@qh1"`) |
| selection | as event, with numbers masked, because the line is compared as its own term |

Any of the following rejects the **whole** ticket with `409` and per-leg reason codes:

- book changed → `BOOK_CHANGED`
- line changed → `LINE_CHANGED`
- price changed, including a **better** price → `PRICE_CHANGED`
- event, market or selection mismatch → `QUOTE_MISMATCH`
- no terms sent (an older client) → `QUOTE_UNCONFIRMED`. This is the conservative choice: the leg is
  rejected and its current terms are shown, never accepted.
- current quote stale → `QUOTE_STALE` (plus `STALE_QUOTE`)
- current quote missing or incomplete → `QUOTE_UNAVAILABLE` (plus the specific code)

A changed leg returns its `current` safe terms: label, book, event, market, selection, line, price,
`updated_utc` and `updated_label`. All of these are server data; the client payload is never echoed. On a
rejection nothing happens: no payout, no image, no export, no handoff, no partial save and no file write.
The UI shows old → new terms per leg with an explicit **Confirm current terms** action, and the user then
resubmits. The server stays authoritative: matching terms are priced from the server quote, and a client
value never prices anything.

The label carries the line. When a line moves, the leg is resolved by event + market + selection with the
line masked, and only a unique match counts; an ambiguous match is `NOT_ON_BOARD`, never a guess. The SGP
Workbench resolves a moved line or book by matching the leg id with that one slot masked.

Unreadable terms (wrong type, `"1x0"`, a fractional price) are `422 malformed_ticket`.

## 3. `/parlay/save`: the legacy review record, frozen at 1..20 picks

The record is not an executable ticket. No payout is computed, and `Payout` stays 0 until a result is
recorded.

- Range: `PARLAY_REVIEW_MIN_PICKS = 1` (the builder's save button needs one selected prop) up to
  `PARLAY_REVIEW_MAX_PICKS = 20` (the historical server cap).
- Over the cap: `422 TOO_MANY_PICKS`. Nothing is saved and the picks are **never truncated**. With 0 picks
  the response is `422 TOO_FEW_PICKS`.
- An invalid pick: `422 INVALID_PICKS` with `invalid: [{index, reasons}]`, where `index` is the 0-based
  position in `picks` and `reasons` are codes such as `MISSING_PLAYER`, `INVALID_DIRECTION`,
  `INVALID_LINE` or `DUPLICATE_PICK`. The payload is not echoed, nothing is saved and nothing is dropped.
- An accepted save stores exactly the submitted picks, in the submitted order, in the record schema.
