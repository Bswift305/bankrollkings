# Micro Conformance Exception Review — PropScore + residual authority cues

**Scope: narrow.** The known PropScore exception plus the residual authority-language / visual-cue
items surfaced during remediation. **Review only — exact replacements proposed, nothing
implemented.** Does not reopen the closed remediation gate or claim product-wide conformance.
Against the frozen contract (`docs/matchup_page_product_contract.md`). Dated 2026-10-09.

---

## Exception 1 — PropScore "validated" / "proven" (the real one)

- **Surfaces (customer-facing):**
  - `templates/nfl_board.html:64` — "a **validated** PropScore play or a wind-under outranks a model
    total, because one is **proven** and the other is context."
  - `templates/cfb_board.html:45` — "CFB has **no backtested edge** in our record **the way NFL
    PropScore and wind-unders do**…" (asserts NFL PropScore has a backtested edge).
- **Governance status:** there is **no governance record** documenting PropScore as Qualified —
  and, more seriously, **our own out-of-sample test contradicts the claim.**
  `validate_nfl_prop_score_oos.py` (docstring, line 16): *"the relationship INVERTS. Players…"* — the
  in-sample PropScore edge **inverted** on a clean 2024→2025 holdout.
- **Why it conflicts:** "validated" / "proven" assert earned, graded authority. Not only is that
  authority undocumented, it is **refuted by our own holdout**. This is the strongest conformance
  exception found — the copy claims the opposite of what the OOS test showed.
- **Exact replacement:**
  - `nfl_board.html:64` → "a PropScore play or a wind-under is ranked above a plain model total as
    **context — status-labeled, not a proven edge** (our out-of-sample test did not confirm a
    PropScore edge)."
  - `cfb_board.html:45` → "CFB has **no backtested edge** in our record — like the rest of the
    board, every play here is a **model lean, not a proven edge**." (drop the "the way NFL PropScore
    … do" clause that implies PropScore is proven.)
- **Note for the governance-source gate (not this review):** PropScore's OOS inversion is a
  *ranking* question too — the board still elevates PropScore rows. Whether it should is a
  governance/logic matter for the Governance Source gate, **out of scope here** (copy only).

## Exception 2 — Visual "lock" cue still rendered (matchup page)

- **Surface:** `templates/matchup.html:330` — the `prop.is_lock` branch still renders a **gold
  gradient badge** (`linear-gradient(135deg, var(--accent-blue) → var(--accent-copper))`). The
  *text* is now neutral ("{N}% market-implied"), but the gold elevation is a **visual conviction/lock
  cue** — the only thing distinguishing the former "Lock" tier.
- **Governance status:** no governed tier; `is_lock` is an internal flag with no earned authority.
- **Why it conflicts:** §3/§7 — a visual tier elevation implies authority as much as the word did.
  Removing "Lock" text but keeping the gold "lock" badge leaves the cue intact.
- **Exact replacement:** render the `is_lock` branch with the **plain `grade-badge`** styling,
  identical to the `confidence >= 70` branch (drop the gold inline gradient). All three branches then
  show the same neutral "{N}% market-implied" badge. *Explicit non-change:* the `is_lock` flag and
  the 70% threshold are untouched — only the badge's visual styling.

## Exception 3 — Green Light residual "independent" claim

- **Surface:** `templates/green_light.html:92` — "each lens is a genuinely **independent** argument
  the market tends to average away…"
- **Governance status:** independence is the method's *intent*, not a demonstrated fact (per the
  accepted independent→configured correction; the attribution harness has not yet shown the lenses
  are independent out-of-sample).
- **Why it conflicts:** asserts independence as established. (The intro and lens-key were already
  corrected; this third instance was missed.)
- **Exact replacement:** "each lens is a genuinely **distinct** argument the market tends to average
  away…" (keep the rest; "we count agreement, we don't blend a score" stays — it's mechanical).

## Secondary — "validated edge" for wind-unders / methodology category (lower priority)

- **Surfaces:** `football_method_board.html:331` ("~55%, our one **validated** totals edge"), `:357`
  ("the **validated edge**"); `how_we_analyze.html:127` lists "a **validated edge**" as a category.
- **Governance status:** wind-unders are supported by our internal backtest (and, unlike PropScore,
  are **not** contradicted by an OOS test), but there is still **no frozen governance record** that
  documents a "validated" status.
- **Why it's lower priority:** the claim is not *refuted* (PropScore is); it is merely *undocumented*
  pending the governance registry.
- **Proposed handling:** either (a) keep "validated" **only once** the Governance Source / Registry
  (Gate 3) documents a wind-under Qualified record, or (b) interim-soften to "our strongest-supported
  totals signal (wind-under ~55% in our backtest)". Recommend deferring to the governance-source
  gate rather than editing now — it hinges on the registry that gate creates.

---

## Summary

| # | Exception | Severity | Proposed action |
|---|---|---|---|
| 1 | PropScore "validated/proven" | **High — refuted by our own OOS test** | Remove; replacement text above |
| 2 | Visual gold "lock" badge (matchup) | Medium — visual authority cue | Neutral badge styling |
| 3 | Green Light "genuinely independent" (3rd instance) | Medium | "independent" → "distinct" |
| — | Wind-under "validated edge" / category | Low — undocumented, not refuted | Defer to Governance Source gate |

**No implementation is authorized by this review.** Exceptions 1–3 have exact, mechanical
replacements ready; if authorized, they are a small copy/styling patch (same discipline as the
remediation: labels/styling only, no logic). Exception 4 waits on the Governance Source gate.
