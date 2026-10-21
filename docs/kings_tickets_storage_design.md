# Step 4 — active-draft vs persistent-history storage design (RETURN, no code)

Returned per directive **before** any persistence is written. Nothing here is implemented. No localStorage,
no new server records, no Decision Journal writes, no hidden session state has been added. King's Tickets
edits remain **browser-page-only** (labelled as such) until this design is reviewed and approved.

---

## 1. Two storage classes — keep them separate

| | **Active draft** | **Persistent history** |
|---|---|---|
| What | the one editable ticket a user is building right now (2–5 legs) | a durable record of a ticket the user acted on + how it resolved |
| Lifetime | ephemeral — minutes/hours; replaced by the next draft | permanent (until the user deletes it) |
| Count | **one** per account (the current draft) | many, append-only |
| Purpose | UI convenience: survive a refresh / nav within a session | the Decision Journal — "which reasoning produced which result" |
| Sensitivity | low (assembled options, not a placed bet) | **high** — implies betting activity; privacy + legal exposure |
| Gate | product decision (this doc) | **attorney/privacy review** — stays DARK (`DECISION_JOURNAL_ENABLED=0`) |

**The boundary is the whole point:** an active draft is a scratchpad, not a betting record. Conflating them
is what the Decision Journal gate exists to prevent. This design lets the *draft* persist without opening
the *history*.

## 2. Active-draft — options (pick one in review)

The draft is `{legs:[{game,label,tier,sport,reason,price}], size, updated_at}` — the SAME leg shape the
shared editor already emits (no new per-leg fields invented; book/timestamp/scope stay *unavailable*, as
today). It is NOT a bet and carries no result.

- **A. None (status quo).** Browser-page-only; refresh resets. Honest, zero storage, zero privacy
  surface. The label already says so. Cost: the draft doesn't survive a refresh or a cross-tool hop.
- **B. Server-side, session-scoped, short-lived.** One draft per signed-in account in a short-TTL store
  (e.g. a dedicated `active_draft/{uid}.json` under a private runtime dir, or the existing server session),
  **account-bound, single-slot, overwritten on each save, auto-expiring (e.g. 24h), never appended.**
  Reuses the `card_prefs` storage pattern (same dir discipline, 0600). Survives refresh + cross-route.
  Privacy: holds assembled options tied to a uid; must be deletable on request + excluded from any export;
  **must be provably NOT a betting-history log** (single-slot, no results, no timestamps of action).
- **C. Browser localStorage.** Per-device, per-origin, never reaches the server. Survives refresh on that
  device only; no cross-device, no server privacy surface. The directive flagged localStorage for review —
  it is viable but is per-device and invisible to us (can't honor a server-side delete).

**Recommendation:** **B**, strictly bounded — one slot, account-bound, short TTL, overwrite-only, no
results, with an explicit "clear draft" control and deletion on account action. It gives the workflow its
"my ticket is still here" behaviour without a history log. If review prefers the smallest surface, **A**
stays correct and honest; **C** only if a server draft is unacceptable.

## 3. Persistent history — unchanged, stays dark

The durable record = the frozen **Decision Journal** leg-provenance contract (event id, player/team,
market+side, exact line, individual price *when a book gave one*, book, **quote_scope**, source/capture
timestamp, decision-source). King's Tickets must **reuse that one contract** when (and only when) history
opens — never a second log. Until the legal/privacy gate clears, `DECISION_JOURNAL_ENABLED` stays `0`,
`/journal*` stays 404, and King's Tickets writes **nothing** durable. The active draft (option B) is
explicitly a different store with a different lifetime and must never be presented as, or silently promoted
to, history.

## 4. What review must decide before any code
1. Active-draft option (A / B / C) and, if B, the store location, TTL, and deletion path.
2. Confirmation that a single-slot, result-less active draft is **not** "betting history" for the legal
   gate (vs. the Decision Journal).
3. Retention + deletion policy for the draft (and its appearance, if any, in a data-export/delete request).
4. Whether a draft may ever be "promoted" to a journal record — and that this requires the journal's own
   gate, not a draft-save.

## 5. Invariants any implementation must keep (when approved)
- One active draft per account; overwrite-only; never append; no results/outcomes in it.
- No ticket contents, prices or provenance in URLs or logs.
- No price/book/timestamp/scope fabricated — unknown stays unavailable (as the editor already does).
- Combined price stays illustrative/calculated, separate from leg prices.
- Draft and history are separate stores; a draft never becomes history without the journal gate.
- Deterministic membership/order parity across both surfaces preserved.

**Stop point:** awaiting review of §4. No persistence code until then.
