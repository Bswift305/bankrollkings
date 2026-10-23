# Entity destination matrix — NFL / CFB / NBA / WNBA / MLB

The capability map behind the universal entity-link contract. "No destination exists" is an **open capability
gap** recorded here, not a permanent reason to leave an eligible, resolved name unlinked. Resolver:
`services/entity_links.py` (URL shape) + `app.py` `player_url` / `team_url` / `entity_anchor` (data-gated
resolution → plain text when unknown/ambiguous/historical/unsupported/gated).

## Resolution identity strategy (item 5)
- Resolution is **sport-scoped**: identical names in different sports never cross-link (sport is part of the
  key and, for the shared `/player` route, an explicit `?sport=`).
- A name resolves only when it maps to **exactly one** current entity in that sport's source. A key with
  count > 1 is **ambiguous → plain text, counted as unresolved** (never a guessed link).
- **Stable-ID target:** where a provider gives a stable entity id (nflverse `gsis_id`/`player_id`, Odds API
  participant id, CFBD id), the destination should carry `?pid=<id>` so an ambiguous display name still
  resolves and the page asserts the exact entity. Today only NFL has an id-backed resolver (roster lookup);
  the others resolve by canonical name-key and **abstain to plain text on ambiguity**. Closing the ID gap is
  tracked per sport below. Unresolved is reported explicitly in the coverage report — never counted as linked.

## The matrix
| Sport | Player page | Team page | Resolution source | Legally cleared fields | Unavailable / gated fields | Duplicate-name strategy | Destination status |
|---|---|---|---|---|---|---|---|
| **NFL** | `/tools/player-check?q=<name>` ✅ (id-backed) | `/tools/nfl-team?team=<abbr>` ✅ | `build_nfl_current_roster_lookup` (NFL_CurrentRoster.csv, id-backed); team `NFL_ABBR_TO_FULL` | nflverse stats (open), Odds API market | — | name-key now; `pid` target = nflverse id → ambiguous resolves | **COMPLETE** |
| **CFB** | — (no player page) → plain text | `/tools/cfb-team?team=<team>` ✅ | team by CFBD conference/name; player: none | CFBD/public team facts, Odds API market | player stats thin/unproven (see cfb_research_audit) | team name-key; player always plain | player **GAP** (plain text, intentional today); team complete |
| **NBA** | `/player/<name>?sport=nba` ⚠️ gated | `/team/<team>?sport=nba` ⚠️ gated | current-data keyset (`_entity_player_keyset('nba')`), **empty while `BK_NBA_STATS_ENABLED=0`** | **Odds API market facts (cleared)** | **NBA.com stats (PROHIBITED while gated)** | name-key; ambiguous → plain | **CONTRACT GAP:** while gated the keyset is empty → links vanish. Item 4 wants the link to a **market-facts** page to persist (identity + schedule/market only) — needs identity from the **cleared Odds feed**, not the gated stats. Tracked as a build. |
| **WNBA** | `/player/<name>?sport=wnba` ⚠️ gated | `/tools/wnba-team?team=<team>` ✅ | team by **licensed Odds schedule** (`_wnba_current_team_set`, NOT stats.nba.com → resolves while gated); player: current-data keyset (gated with NBA) | Odds API market facts (cleared) | stats.nba.com WNBA gamelogs (gated) | name-key; ambiguous → plain | **team COMPLETE** (cleared schedule page; stats abstain visibly); player: same gated-identity gap as NBA |
| **MLB** | `/player/<name>?sport=mlb` ✅ | `/tools/mlb-team?team=<team>` ✅ | team by licensed Odds schedule (`_mlb_current_team_set`); player: current-data keyset (MLB props/roster) | pybaseball/public + Odds API | — | name-key; ambiguous → plain | player **COMPLETE**; **team COMPLETE** |

## Capability gaps → builds (item 3, separate reversible commits)
A **minimal honest destination** contains only: cleared identity (name + team + sport), schedule/market facts
(Odds API — cleared), links to the relevant boards, and a visible "detailed stats unavailable" notice where a
richer page is gated or not built. It must **not** expose NBA/WNBA restricted statistics or invent identity.
1. **MLB team page** — ✅ BUILT `/tools/mlb-team` (`6ac3746`): team identity + its schedule/game lines from
   the Odds feed + links to the MLB board. No stat tables beyond cleared sources.
2. **WNBA team page** — ✅ BUILT `/tools/wnba-team`: same shape, obeying the gate — the licensed Odds
   schedule renders and resolves while `BK_NBA_STATS_ENABLED=0`; stats.nba.com statistics abstain visibly.
3. **NBA/WNBA player+team gated pages** — resolve **identity from the cleared Odds participant/team list** so
   the link persists while `BK_NBA_STATS_ENABLED=0`, render the market-only facts, and **abstain visibly** on
   every NBA.com-derived stat. This decouples the *link contract* from the *stat gate* (item 4).
4. **CFB player page** — only if a cleared per-player source is adopted (today CFB is a sides/totals program;
   player page stays a documented gap → plain text).

Until a build lands, the affected names remain **plain text and are counted as "missing-destination"** in the
coverage report (not "linked", not silently dropped). Fetch-based destination tests (`qc_entity_links.py`)
cover every *existing* destination and assert the rendered sport + entity; new destinations add their own
fetch test asserting cleared-only content + the gated-stat abstention.
