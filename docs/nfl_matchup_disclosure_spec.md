# NFL Matchup Card — Progressive-Disclosure Specification (DRAFT)

**Status: SPEC ONLY — not implemented.** Step 3 (page hierarchy) stays **open** until this is
approved and the implementation is verified. Surface: `templates/nfl_matchup.html` (the "NFL
Matchup Edge Card", `/tools/nfl-matchup`). Also applies conceptually to the CFB/MLB matchup cards,
but this spec and its implementation are **NFL-scoped**.

**Goal:** reduce the density of each matchup card so the reads that matter are noticed first,
without hiding any material fact. **Hard rule (per review): injuries/availability are material —
they must never fully disappear.** A compact availability summary stays always-visible; the full
lists move into the expandable section.

**Guardrails:** preserve every existing fact, number, warning, and source. No new ranking,
recommendation, interpretation, or wording. No change to any calculation or selection. Visual/
structural only.

---

## 1. Always-visible (primary block) — per matchup, never collapsed
1. **Matchup + kickoff** — teams and time (current header, e.g. "Philadelphia Eagles @
   Jacksonville Jaguars · 09:30").
2. **Current spread and total** — e.g. "-8 · O/U 41.5" (the header line fixed in `24273df`).
3. **Total / model context** — "Total: model 38.3 vs 41.5 — UNDER (-3.2)" plus the existing
   `skill_note` ("Production out: …"). (`nfl_matchup.html:118–120`.)
4. **Key narrative** — the `[OVER]/[Under]` read **and the amber ⚠ warning** (the warning is a
   material caveat and stays in the primary block, never collapsed).
5. **Compact availability summary** — a short, always-visible count derived from the existing
   out/questionable lists, e.g. **"PHI: 4 Out · 2 Q · JAX: 3 Out · 2 Q"** (or a combined
   "7 Out · 4 Questionable"). This is a **count of facts already present** — no new data, no
   interpretation. It signals availability at a glance; the names live in the expandable detail.

## 2. Expandable — "Game detail" (secondary block)
Behind an accessible disclosure control labelled **"Game detail"**:
- **Line movement** — the `MOVE spread … · total …` row.
- **Period splits** — 1H, 1Q, and team-total (TT) rows (`nfl_matchup.html:131–132` + TT).
- **Defensive splits** — PHI D / JAX D lines and the passing-form caveats.
- **Full out/questionable lists** — the complete per-team player lists (the summary in §1.5 is the
  always-visible digest of these).
- **Tackle-prop context** — the "Tackle volume" block and its rows (`nfl_matchup.html:157+`),
  including the "volume read, not a graded edge · sacks excluded" caveat (preserved verbatim).

Nothing is deleted — every item above moves from "always rendered" to "rendered inside an
expandable region." All numbers, caveats, and sources are retained exactly.

## 3. Behavior
- **Collapsed by default on mobile** (≤760px) — primary block visible, "Game detail" collapsed.
- **Desktop (>760px):** the primary block shows; "Game detail" **may default to expanded** (more
  room) while remaining collapsible. Implementation choice to confirm at review: (a) collapsed
  everywhere for consistency, or (b) expanded-by-default on desktop via progressive enhancement.
- **Per-matchup state** — each matchup's disclosure is independent (expanding one does not affect
  others), and toggling one does not reset the page.
- **Accessible disclosure** — use native `<details>/<summary>` (keyboard-operable, screen-reader
  announced, per-instance state for free) **or** a button with `aria-expanded`/`aria-controls`.
  The summary has a clear label ("Game detail") and a visible focus state (consistent with the
  Step-1 focus work).
- **No layout/logic beyond the disclosure** — the only new behavior is show/hide; ordering of the
  retained items is unchanged within each block.

## 4. Implementation notes (for the build, once approved)
- Wrap the §2 items of each matchup in one `<details class="mu-game-detail">` with a
  `<summary>`; keep §1 items outside it. `<details>` gives per-instance state + keyboard support
  natively; collapsed-by-default is the element's default (satisfies the mobile requirement).
- Desktop-expanded (option b) = a tiny progressive-enhancement script that sets the `open`
  attribute on each `<details>` when `innerWidth > 760` at load (and leaves user toggles alone
  after). This small script is the only scripted behavior; flag it explicitly at review.
- The availability summary (§1.5) is computed by counting the existing out/questionable entries
  already passed to the template — add a count, render it; do not fetch or infer anything new.
- Page-local to `nfl_matchup.html` (markup + a little scoped CSS for the summary/disclosure). No
  shared-theme change. One reversible commit.

## 5. Verification (after approval, before closing Step 3)
Desktop + 375px + 600px:
- Primary block (matchup, spread/total, model context, narrative, ⚠ warning, availability
  summary) is visible without expanding.
- "Game detail" expands/collapses by click and by keyboard; focus is visible.
- Expansion is per matchup (one open ≠ all open); no page reset.
- Every number, caveat, source, and the ⚠ warning present before the change is still present
  (in primary or detail).
- Mobile defaults collapsed; desktop behaves per the chosen option.
- No horizontal scroll; the FAB clearance (Step 2) still holds.

*Awaiting approval of this spec (and the desktop default, option a or b) before implementation.*
