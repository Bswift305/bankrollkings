# Hot Hand Audit #1 — Source→Render evidence (build_nfl_hot_hand, `/tools/nfl-heatmap`)

Read-only audit (prod `diag_nfl_hot_hand_audit.py`, HEAD `c9ace3a`; `READ-ONLY PROOF … ALL UNCHANGED`,
exit 0). **No membership, ordering, template, or data-source change made** — this is the evidence report
for review. Shaped for later Evidence-Ledger migration; no receipts/constitutional infra implemented.

## Chain
`Source → Canonical events → Identity → Eligibility → Calculation → Membership → Ordering → Render`

- **Source:** nflverse player-week logs — `NFL_PlayerStats_{2023,2024,2025}.csv` (historical) +
  `data/tracking/_nflverse_stats_2026.parquet` (current, mtime 2026-10-24 09:04 ET); 49,818 rows.
- **Canonical events:** per-player-week game-stat rows (appearances). **No EventId / PlayerId.**
- **Identity:** `idx.get(player.lower())` against the log grouped by lowercased resolved `_full`.
- **Eligibility:** the **current `NFL_Props.csv` board** — 875 (player,stat) groups, all mapped to a floor
  stat; line = median across books; player must resolve in the log index with the stat columns; QB stats
  require attempts>0; most-recent loaded game must be the current season.
- **Calculation:** walk the player's appearances newest-first; `streak` = consecutive rows with actual
  value > **this week's** line; break at the first miss.
- **Membership:** `streak ≥ min_streak (2)`, dedup (player, stat). **Availability does NOT gate membership.**
- **Ordering:** `(active first, −streak, −avg_clear)`, then sliced to the render limit (50).

## Semantics (NOT interchangeable)
The Hot Hand streak is **current consecutive player *appearances* above this week's prop line** — a
**market-line** streak (not a fixed milestone), **not** consecutive team games, **not** consecutive weeks,
**not** a recent-window hit rate. The walk is over appearances (log rows), so a bye / missed game is a
non-row the run **bridges**.

## Findings (ranked; no change made)

**F5 — HEADLINE DEFECT: the board renders `active=0` (all 133 streaks "historical / N weeks behind").**
`through_week = max(loaded week) = 7`, but the resolver's completed week is **6**. A single early Week-7
game advances `through_week` to 7, so every player whose latest completed game is Week 6 computes
`weeks_behind = 1` → `is_active=False`. The top streak (Aaron Jones, 11 straight rushing yards) renders as
"Historical — last played Wk 5, 2 weeks behind." The heat map's "who's hot **right now**" purpose is
defeated by counting an in-progress week as the recency anchor. **Proposed fix (for approval):** anchor the
recency gate (`weeks_behind`) and the "Results through Week X" label to the **resolver completed week**
(`min(max_loaded, completed_week)`), mirroring the data-through capping flagged for the Wave. Same class of
bug (through-week not capped at the completed week).

**F2 — `weeks_label` masks bye/missed weeks (27 runs).** e.g. Austin Hooper rec yds "Wks 2–6" is
appearances `[2,3,4,6]` (Wk5 skipped); Bryce Young pass yds "Wks 1–6" = `[1,2,3,4,6]`; Patrick Mahomes
"Wks 2–6" = `[2,3,4,6]`. The min–max label implies consecutive weeks for consecutive *appearances*.
**Proposed fix:** gap-truthful label (compact ranges with gaps, like the Wave's `_compact_weeks`
"Wks 2–4, 6") + state the unit is appearances.

**F3 — identity (reframed honestly).** The 73 "identity drops" are overwhelmingly **team DEFENSE props**
(`Arizona Cardinals D/ST`, `… Defense`) + fringe players (`CJ Daniels`, `Camden Brown`) with no player-week
row — defense props cannot have a player-appearance streak, so this is an **expected absent-reason**, not a
bug (should be disclosed as such). The 455 `_full` lowercase "collisions" are mostly **legitimate
short↔full merges of the same player** (the resolver working), not distinct-player collisions; without a
player id, true distinct-player collisions are **indeterminate**. Net: name-based identity, no proven
wrong-player merge, no id to guarantee it.

**F1 — prior-season gate.** Membership season = `max(log season)` = 2026, which **matches** the resolver
(no live leak), but is weaker than `build_nfl_prop_streaks` (which fails closed to the resolver season). If
the parquet ever goes stale at a prior season, prior-season runs could render as current. **Proposed fix:**
anchor `cur` to the resolver current season and fail closed if the log doesn't reach it.

**F4 — availability does not gate membership** (by design): unavailable/historical streaks remain members,
sunk in ordering and labeled ("before absence" / "status unknown" / "historical"). Left as-is unless the
product wants membership-level exclusion.

## Suppression / hashes
- Display-limit: **83** qualifying streaks beyond the 50-row render limit are not shown.
- Membership hash (full, player/stat/streak) `a11e942b4f5bfc58`; render hash (top 50 +active) `563840b0522f99ce`.

## Freshness / fail-closed
Empty log or empty props → `available=False`. Stale/missing injury feed → availability STATUS UNKNOWN
(never silent "active"). `pending_latest` triggers only when `through_week < expected_week` (data behind the
calendar) — it does **not** guard the F5 case where `through_week > completed_week` (an in-progress week
loaded).

## Recommended remediation order (AWAITING APPROVAL — no change yet)
1. **F5** (cap recency + label at the resolver completed week) — restores a usable "active" board.
2. **F2** (gap-truthful weeks label + appearances wording).
3. **F1** (resolver-anchored season gate, fail closed) — latent-risk hardening.
4. **F3** disclosure (defense props as an explicit absent-reason).
F4 left by design. Explainer wiring (shared streak explainer) follows after the semantics are correct.
