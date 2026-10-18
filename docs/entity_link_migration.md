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
| Injury Report (multi-league) | `templates/injury_report.html` | player + team, per-row `r.league` | ✅ migrated + prod-verified |
| NFL Team route | `app.py nfl_team_tool` / `build_nfl_ats_context` | accepts `?team=<abbr>` → pre-selects profile | ✅ new destination |

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
