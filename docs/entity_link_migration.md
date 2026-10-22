# Universal entity-link migration — tracked table

Every place that builds a player/team page link, with its destination status and (where not yet
migrated) the blocking reason. The resolver is `services/entity_links.py` + `player_url` /
`team_url` / `entity_anchor` (app.py); see [[project_entity_links]]. "Migrated" = goes through the
resolver (centralized encoding, sport-scoped, fail-to-plain-text, context-gated). This table is the
directive's required accounting: we do not declare the requirement closed while occurrences remain
unmigrated — they are listed here with a reason and an owner.

## Destination status by sport (the resolver contract)
| Sport | Player dest | Team dest |
|---|---|---|
| NFL | `/tools/player-check?q=` ✅ | `/tools/nfl-team?team=<abbr>` ✅ (now targetable) |
| CFB | — (no player page; plain text) | `/tools/cfb-team?team=` ✅ |
| NBA | `/player/<name>?sport=nba` ✅ (gated → plain text when NBA data off) | `/team/<team>?sport=nba` ✅ |
| MLB | `/player/<name>?sport=mlb` ✅ | **BLOCKED — no MLB per-team page exists** (tracked below) |
| WNBA | `/player/<name>?sport=wnba` (gated) | **BLOCKED — no WNBA per-team page exists** |

## Migrated
| Surface | file | What | Status |
|---|---|---|---|
| Injury Report (multi-league) | `templates/injury_report.html` + `_injury_rows.html` | player + team, per-row `r.league` via `entity_anchor` | ✅ migrated + prod-verified |
| NFL Team route | `app.py nfl_team_tool` / `build_nfl_ats_context` | accepts `?team=<abbr>` → pre-selects profile | ✅ new destination |
| NFL Milestones | `templates/nfl_milestones.html` | player + opponent team via `entity_anchor` | ✅ migrated |
| NFL Matchup Center | `templates/nfl_matchup_center.html` | team via server `team_url('nfl', …)` (`g.away_url`/`g.home_url`) | ✅ migrated |
| **MLB player links (5 surfaces)** | `mlb_dashboard.html` (5), `mlb_matchup.html` (2), `mlb_method_board.html` (2), `elite_mlb_lab.html` (3), `missed_opportunities.html` (1) | 13 hand-built `/player/<name>` (NBA-route, no `?sport=`) → `entity_anchor('player', 'mlb'/row.sport, …)` | ✅ migrated — **fixes a wrong-destination bug** (MLB/cross player was sent to the NBA page); live `/sports/mlb` renders 12 resolver anchors, 0 sport-less `/player/` leaks; `qc_entity_links` fetch-tests the MLB destination |

## Coverage report — fresh mechanical inventory (2026-10-21), by class
618 name outputs / 101 files read. Every occurrence is accounted for in exactly one class (the directive's
"100% accounted-for" bar). Full surface-by-surface file:line detail is in the session inventory; the counts
and dispositions:

| Class | Meaning | Disposition |
|---|---|---|
| **LINKED-via-resolver** | already goes through `entity_anchor`/`player_url`/`team_url` | ✅ done: `_injury_rows`, `nfl_milestones`, `nfl_matchup_center`, injury_report lazy rows, + the MLB batch above |
| **LINKED-hand-built → migrate** | `<a href="/player/…\|/team/…">` not via the resolver | staged in batches below (MLB batch done) |
| **PLAIN-TEXT-intentional** | CFB player, MLB team, WNBA team (no destination); every heading/title; every prose mention; referees/coaches; `<select>` options | ✅ correct as-is — never link |
| **PLAIN-TEXT-eligible** | a name that *could* link but doesn't (e.g. NFL players on nfl_hub/featured, NBA team chips) | candidate to newly link, per batch |
| **CLIENT-RENDERED (JS)** | injected via `innerHTML`/`textContent` in `<script>` — the resolver (Python) cannot reach | plain text, OR inject a server-rendered resolver fragment (the pattern `injury_report` uses). Tracked below |
| **OUT-OF-SCOPE** | Franchise Kings (fictional sim players/teams; internal `pid` routes only) | ✅ never entity-linked |

### Remaining migration batches (staged, reversible — each its own commit + fetch test)
1. **WNBA player links** — `wnba_dashboard.html:290`, `wnba_matchup.html:113`, `wnba_method_board.html:114` → `entity_anchor('player','wnba',…)` (gated → plain text when WNBA data off; same wrong-destination fix as MLB).
2. **football_method_board.html:499** — NFL/CFB player sent to the NBA `/player/` route → `entity_anchor('player', sport_key, …)` (NFL→player-check, CFB→plain text). A clear wrong-destination bug.
3. **NFL board surfaces (row-anchor, nested-anchor care)** — `nfl_hub`, `nfl_heatmap`, `nfl_matchup_edge`, `nfl_prop_floor`, `nfl_featured`: the whole `<tr>`/row is already an `<a>`/`onclick` to `nfl-floor`/`nfl-dvp`. These are **not** entity anchors; linking the name would nest an anchor. Decision: keep the row-click (preserves behavior) and leave the name plain, OR make the name the entity link and demote the row-click. Tracked, not auto-converted (nested-anchor flag).
4. **Cross-sport dashboards** — `candidate_review`, `elite_dashboard`, `elite_matchup_builder`, `dashboard_overview`, `heat_map`, `derivatives` (+ server `player_href` at app.py:13213/39910): hand-built `/player/` with no `?sport=` → `player_url(row.sport, …)`. Some have nested-anchor flags (card is already an `<a>`) — convert the existing anchor, don't add one.
5. **NBA surfaces** — `dashboard`, `matchup`, `series`, `props`, `trend_board`, `smart_picks_v2`, `parlay`, `parlay_formula`, `raw_data`, `team`, `player`, `heatmap`, `schedule`, `injuries`, `season_review`, `team_season_review`, `nba_calibration`: **DEFERRED to NBA Season Readiness** (migrating now would mass-unlink NBA while the gate is off; `entity_anchor` already blocks *new* NBA prose/heading links). Owner: NBA Season Readiness.
6. **CLIENT-RENDERED JS** — `parlay`/`parlay_formula`/`fantasy_league` row builders, `bk_base` ticket tray, `green_light_workspace` lens items, the JS data-boards (`bk_power`, `cfb_ats`, `nfl_ats`, `mlb_luck/nrfi/situational`, `scenario_lab`): names injected in JS. Either keep plain, or (where an entity page exists and it matters) emit a server-rendered resolver fragment. `cfb_matchup.html:154` already builds a `/tools/cfb-team` link in JS (client-side, correct destination). Tracked; no Python-resolver change applies.

### Nested-anchor / heading / prose flags (must NOT get a second anchor or a new link)
Nested-anchor: `dashboard` matchup rows, `series` matchup cards, `game_lines:56`, `dashboard_overview:227→232`, `candidate_review:684→689`, the NFL floor row-anchors, `nfl_prop_floor:83→84`. Headings/titles + prose: `team_season_review`, `wnba_matchup`, `cfb_team`, `series:279`, player page subject, all franchise headings, and the documented prose mentions. These stay plain text by rule.

## To migrate — ACTIONABLE (non-NBA; resolver destination exists)
Each already points at a valid destination today (so not broken), but is a hand-built href that
should route through the resolver for centralized encoding + fail-to-text. Low risk; staged.
| Surface | file:line (from inventory) | Link | Destination |
|---|---|---|---|
| NFL Featured | `nfl_featured.html:99,111` | player (floor/dvp) | nfl player → player-check (or keep floor/dvp as a distinct "view") |
| NFL Heat Map | `nfl_heatmap.html:91` | player row-anchor → nfl-floor | player-check; preserve row-click |
| NFL Hub | `nfl_hub.html:26,38,56,78` | player row-anchors → nfl-floor | player-check; preserve row-click |
| NFL Matchup Edge | `nfl_matchup_edge.html:35` | player row-anchor | player-check |
| NFL Prop Floor | `nfl_prop_floor.html:83` | `<tr onclick>` player | player-check; preserve JS row-click |
| NFL Milestones | `nfl_milestones.html` | player + opponent team | ✅ already via resolver (new page) |
| CFB Matchup | `cfb_matchup.html:154,194` | team "full profile" CTA (JS) | cfb-team (CTA label, not a name-in-prose) |
| MLB dashboards/matchup/boards | `mlb_dashboard.html`, `mlb_matchup.html`, `mlb_method_board.html`, `elite_mlb_lab.html` | player | `/player?sport=mlb` |
| Schedule | `schedule.html:54,56` | team (wraps `team_mark`) | sport-scoped team_url |

## To migrate — DEFERRED (NBA surfaces; coordinate with NBA Season Readiness)
NBA data is behind the data-rights gate; migrating these now would mass-unlink NBA while that
workstream is handling NBA-surface honesty holistically. The `entity_anchor` macro already prevents
*new* NBA prose/heading links. Owner: NBA Season Readiness.
| Surface | file:line | Link | Note |
|---|---|---|---|
| Candidate Review | `candidate_review.html:519 (heading), 578, 721` | player | **:519 is a heading → must become plain text** |
| Dashboard | `dashboard.html:1320 (prose), 1662, 1709` | player | **:1320 is a prose/angle label → plain text** |
| Dashboard Overview | `dashboard_overview.html:308,321,334` | player mini-row anchors | — |
| Elite dashboards | `elite_dashboard.html:129,174,327,506,544`, `elite_matchup_builder.html:104,130,149` | player | — |
| Matchup (NBA) | `matchup.html:72 (team nav), 232 (card heading), 233, 264,265,431,449,472` | player + team | **:232 player-name-as-heading → plain text** |
| Props / Trend / Smart Picks / Raw / Series / Season Review / Team / Team Season Review / Parlay / Parlay Formula / Heatmap / Missed Opportunities / Fantasy League | various (see inventory) | player + team | — |
| Season Review team links | `season_review.html:177,207,235,330,353,392` | team | `/season-review/team/<t>` (NBA) |
| Python-side link dicts | `app.py:13036-13038, 20650, 39281` | `player_url`/`href`/`player_href` | route through resolver |

## BLOCKED — no destination exists (tracked, pending product decision)
| Surface | Entity | Reason |
|---|---|---|
| MLB team names (everywhere) | MLB team | No MLB per-team page exists. Decision pending: build an MLB team profile, or leave plain text. Until then `team_url('mlb', …)` returns None → plain text (NOT a wrong-entity link). |
| WNBA team names | WNBA team | No WNBA per-team page. Same treatment. |
| NBA player links while NBA data-rights gate is OFF | NBA player | Destination renders nothing when gated → resolver returns plain text (honest). Re-links automatically when the gate opens. |

## Rule reaffirmed
"No team page exists" is **not** a permanent resolution: NFL team is now targetable; MLB/WNBA team
destinations are an open product decision recorded above, not a silent dead end. Resolver tests
(`qc_entity_links.py`) FETCH every resolvable destination and assert the intended entity renders.
