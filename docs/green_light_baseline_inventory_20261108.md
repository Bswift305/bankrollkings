# Green Light baseline inventory for Release 1A (read-only evidence, 2026-11-08) — UNCOMMITTED DRAFT

Evidence only: no fix design, no program-table change, no code. Sources: git history at `3d7cda1`/`b12eec3`, the parked
code-history input (`docs/green_light_audit_code_history_20261107.md`), today's live/prod read-only audits
(`docs/nov7_cross_sport_landing_audit_20261108.md`), and owner statements recorded in this program.

## Baseline
- **Last classic-default version: `9055594` (2026-10-21)**, parent of `9057ba1`. `/tools/green-light` →
  `build_green_light(limit=40, pos=None)`, NFL only, paid-gated; classic engine/template unchanged `614b5d9` → `9055594`.
- **Lineage:** `0291393` (2026-10-04) rename Kings Wisdomism → Green Light; `b98c351` multi-channel/fragile lens;
  `60226f6` Rev 3 Final remediation (authority language → observational); `c4ca828` PropScore containment (sort,
  line-state, "not a best-bets board", wind wording); `99c3754`/`5ebe75e` position filter; `614b5d9` King's Tickets
  entry points; `103ecb1` preference-workspace contract v1 (docs); `6a26e97`, `0a32bbb` workspace plumbing;
  **`9057ba1` default flipped to the workspace.**
- **Approval evidence.**
  - `60226f6`: "Authorized implementation of the approved remediation spec" — **explicit owner approval** (Rev 3 Final).
  - `c4ca828`: implements `docs/propscore_incident_containment_spec.md` "exactly as frozen" (`ca93375`) — **explicit
    owner approval** (frozen spec).
  - Core convergence engine (`0291393` lineage): deployed and in use; **no formal production-acceptance record found**.
    Owner directive 2026-11-07 (GL 1B) restores classic as the default — **explicit owner approval of classic as the
    restoration target**.
  - `9057ba1`: commit cites "adapters… green on prod" and says the legacy route is removed "only after production
    acceptance on the default URL"; **no acceptance or owner approval recorded**; contradicts the frozen contract
    `103ecb1` ("with no saved preferences a user sees today's default board unchanged").
- **Deployment ≠ approval.** Rows below mark deployment-only states "no recorded approval".

## Comparison
Classic engine at `b12eec3` is byte-identical to baseline except the 5-line banner (`9057ba1`).

| Capability | Owner-approved baseline (`9055594`) | Current Classic (`?view=classic`) | Current default Workspace | Classification | Approval evidence |
|---|---|---|---|---|---|
| Candidate generation | Featured non-defense usage players, primary over (Rush Yds / Rec Yds), FanDuel row | Same | None; "proposed ticket" = `build_daily_cards` output | Classic **PRESERVED** (hidden off default); Workspace **REPLACED** | Engine: no formal acceptance; workspace: no recorded approval |
| Convergence / lens count + tiers | Count of agreeing lenses; tiers "4+/3/2/1 configured lenses" | Same | Absent (12 non-convergence adapters) | Classic **HIDDEN**; default **REGRESSED** | Tier wording: explicit (`60226f6`) |
| Opportunity | Season-to-date share role vote | Same; VERIFIED today; "locked role" text from static 10-09 file (stale) | Not present | **HIDDEN** (+ inherited label staleness) | No formal acceptance |
| Matchup | Opp. defense adj. rank via `_nfl_game_scripts()` | Same — **cross-event overwrite** (11 of 28 teams bound to next week) present in the baseline code | `matchup_context` factual module (different) | Classic **PRESERVED with inherited P0**; Workspace **REPLACED** | No formal acceptance |
| Game Identity | Spread size / favourite via same scripts | Same, same overwrite defect | Not present | **PRESERVED with inherited P0** / **HIDDEN** | No formal acceptance |
| Coaching | Static 2023–25 team tendencies (`a62f37a`) | Same; INVALID for ATL 2026 (new staff) | Not present | **PRESERVED** (data aged; no staff check) | No formal acceptance |
| Concentration | Static 2023–25 TD-angle note, not counted | Same; name-key collision (St. Brown ↔ A.J. Brown) | Not present | **PRESERVED with inherited defect** | No formal acceptance |
| Fragile-leg flag | Single-channel × script certainty | Same (inherits wrong-event scripts) | Not present | **HIDDEN** | `b98c351`, no formal acceptance |
| Pricing / sportsbook attribution | FanDuel price shown, no book label or source time | Same (below the `17b5e69` quote-time standard) | Ticket path uses executable-leg contract (book, price, source time) | Classic **PRESERVED (deficient)**; Workspace ticket **INTEGRITY_PROTECTION** | `17b5e69` hotfix accepted (Integrity+D4) |
| Freshness | None (`_nfl_wisdom_props` reads file directly) | None — 24h-old quotes shown as live (today) | Adapter envelopes STALE/UNAVAILABLE; ticket path 6h rule | Classic **PRESERVED (deficient)**; Workspace **INTEGRITY_PROTECTION** | D4/quote contracts accepted |
| Kickoff eligibility | None | None | D4 kickoff gate in ticket path | Classic **PRESERVED (deficient)**; Workspace **INTEGRITY_PROTECTION** | D4 accepted |
| Player availability | None (OUT/IR not filtered) | None | `injuries_return` adapter (no freshness check) | **PRESERVED (deficient)** / partial | No formal acceptance |
| Contradictions / missing evidence | Fragile note + market line-state (display) | Same | `contradictions` adapter structurally empty; "validated totals-under flag" wording back | Classic **PRESERVED**; Workspace **REGRESSED** (reverses `c4ca828` S5) | `c4ca828` S5 explicit |
| Market line-state / sort | −convergence then game/player/stat; line-state context only | Same | n/a | **APPROVED_CHANGE** (`c4ca828` S6) preserved | Explicit (frozen spec) |
| Ticket / handoff | Fresh King's Tickets CTA, no state carried (`614b5d9`) | Same | Proposed ticket from Daily Cards under "Green Light" | Classic **PRESERVED**; Workspace **UNAPPROVED_CHANGE** | `614b5d9` Step 3.4; workspace: no recorded approval |
| Position filter, Player Check link | Present | Present | Absent | **HIDDEN** | `99c3754`/`5ebe75e` |
| Learning receipt | `capture_green_light.py` archives classic, graded by `grade_lenses.py` | Same (still archives classic) | Not archived | **PRESERVED** (grades a board the default no longer shows) | No formal acceptance |
| Default route / navigation | `/tools/green-light` = classic; sidebar → classic | `?view=classic` + banner | `/tools/green-light` = workspace; sidebar & King's Tickets back-links → workspace | **UNAPPROVED_CHANGE** (`9057ba1`); classic **HIDDEN** | No recorded approval; contradicts `103ecb1`; owner 2026-11-07: restore classic (GL 1B) |

## Notes for the frozen baseline
- Several defects found today are **inherited from the baseline**, not regressions: cross-event overwrite
  (Matchup/Game Identity/fragile), no freshness, no kickoff gate, no availability filter, unlabelled price/book,
  static Coaching/Concentration/role-stability files, Concentration name collision, opponent-adjusted rank shown
  without that label. Restoring the default alone would restore these.
- Regressions attributable to the default change are presentation/availability (convergence, filters, Player Check
  loop hidden) plus the Workspace's reintroduced "validated" wording and Daily-Card ticket under Green Light.
- Latent spread-price defect (`2e2adc6` held) becomes live only if 1A gives game-line legs a kickoff; it must land first.
