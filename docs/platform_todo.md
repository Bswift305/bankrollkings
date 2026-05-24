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

## Open

- No active To-Do items at the moment.
