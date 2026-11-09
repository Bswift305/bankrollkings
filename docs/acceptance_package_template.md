# Acceptance package — required header fields (template)

Copy this block to the top of every future release acceptance package. It adds a reference only. It does not
change any release's scope, gates, or acceptance criteria.

## Doctrine reference

| Field | Value |
|---|---|
| Platform Doctrine version reviewed against | e.g. `PLATFORM-DOCTRINE-1` (v1) |
| Doctrine file SHA-256 | from `docs/platform_doctrine_versions.md` |
| Frozen constitution in force | `DIC-1.0` (separate; unchanged by the doctrine) |

## Blind-spot classification (Platform Doctrine v1 §4)

One row per question. Status is exactly one of **Addressed** · **Deferred with destination** · **Not applicable
with reason** · **Open contradiction**. Any *Open contradiction* blocks acceptance until the owner rules.

| # | Topic | Status | Evidence / destination / reason |
|---|---|---|---|
| Q1 | Identity | | |
| Q2 | Temporal provenance | | |
| Q3 | Applicability | | |
| Q4 | Evidence states | | |
| Q5 | Shared root causes | | |
| Q6 | Market independence | | |
| Q7 | Directional symmetry | | |
| Q8 | Why an item appeared | | |
| Q9 | Discovery versus recommendation | | |
| Q10 | Decision-time reconstruction | | |
| Q11 | User reasoning | | |
| Q12 | Research-candidate lifecycle | | |
| Q13 | Human-readable explanations | | |
