# Bankroll Kings To-Do

## Resolved

- Injury warning badges now use a red-and-white warning treatment across the main live surfaces.
  - Completed on `2026-05-22`.
  - Goal was to make injury risk read like a true warning state instead of blending into the normal accent system.

- Future-dated prop refresh timestamps were corrected.
  - Completed on `2026-05-22`.
  - `LastUpdated` now falls back to real fetch time instead of future event start time when the upstream feed does not provide bookmaker update time.

- Internal-only test-drive and under-construction surfaces are owner-gated.
  - Completed on `2026-05-22`.
  - These pages should no longer behave like public-facing external tester routes.

 - `Market Watch Tonight` density was tightened.
   - Completed on `2026-05-22`.
   - Reduced vertical padding and made the card stack denser so the section wastes less space on desktop.

- The command center now stays sport-specific and the extra NBA subnav layer was removed.
  - Completed on `2026-05-22`.
  - Once a main sport is selected, the command rail now acts like a local tool strip instead of repeating cross-sport navigation.

- The universal command center was removed.
  - Completed on `2026-05-22`.
  - Cross-sport navigation now lives only in the top sport nav so the site does not pretend generic links like `Props` or `Market Edge` are all-sport hubs when they are not.

- Platform Lens cards now include example-based teaching copy.
  - Completed on `2026-05-22`.
  - `Market Read`, `Matchup Read`, `Trend Read`, and `Verdict` all now include plain-language examples.

- `Tonight's Card` now explains itself in novice-facing language.
  - Completed on `2026-05-22`.
  - Added clearer card intro copy, plain-English tag explanations, and in-card explanations for sample, unit size, and profile language.

- Duplicate tags on `Tonight's Card` are now deduplicated before rendering.
  - Completed on `2026-05-22`.
  - Repeated tags like `Balanced Profile` should no longer appear twice on the same card.

- `Curated Lens Board` labels now have plain-English support copy.
  - Completed on `2026-05-22`.
  - The short tags remain as signals, and the supporting line now explains what those tags mean in betting terms.

- Repeated meaning inside the same widget was cleaned up.
  - Completed on `2026-05-22`.
  - Tag rows now act as quick signals while the supporting line does the real explanation work.

- The redundant lower row under `Conference Finals Matchups` was removed from the rendered dashboard.
  - Completed on `2026-05-22`.
  - The extra `Today / Tomorrow / Upcoming` row is no longer shown below the main matchup cards.

- Universal method routing now uses one honest model.
  - Completed on `2026-05-30`.
  - Global method clicks now land on `/tools/...` hubs, sport-specific work lives under `/sports/...`, and old root paths like `/props` and `/market-edge` only remain as compatibility redirects.

## Open

- **Queued — Green Light decision-convergence workshop (after the current Research Candidate OFF-state deployment work is closed).**
  - Owner intent: Green Light should reflect the way a person actually reaches a decision. A Hot Streak / Trend is one input, not the play by itself. A team or player becomes more interesting when it appears across several independently useful views the user trusts.
  - First workshop case: **UCLA -23 vs Nevada (2026-10-31), covered.** The owner noticed UCLA's sustained ATS performance and a recurring willingness by others/the market to fade the team. Treat this as a pregame-observation case to reconstruct—not as proof of an edge. The workshop should identify which additional evidence was actually available before kickoff (matchup, opponent quality, injuries, line movement, verified public/market positioning, and contradictions), which factors influenced the wager, and what would have invalidated it.
  - Learning requirement for that case: preserve the placed line, timestamp, pregame rationale, factors consulted, missing evidence, closing line, result, and later evaluation. Keep the factual result (UCLA covered) separate from the still-unproven hypothesis (UCLA was systematically undervalued or disproportionately faded).
  - Workshop scope: identify the owner's required and optional signals; sport- and market-specific combinations; disqualifiers and contradiction rules; honest treatment of missing or stale evidence; grouping/ranking; default-visible detail versus drill-down; and account-level preferences.
  - Desired experience: open Green Light and immediately see which teams or players align across the selected factors, which factors support them, which are missing, and which invalidate the idea. A compact summary such as “4 of 6 preferred signals aligned” may organize the evidence, but must not become an invented confidence score, guaranteed play, or template-side betting decision.
  - Starting contract: [`green_light_preferences_contract.md`](green_light_preferences_contract.md). Reconcile the workshop decisions into that contract rather than creating a competing Green Light specification.
  - Boundary: queued product design only. No implementation begins until the current deployment arc is finished and the workshop decisions are reviewed.
