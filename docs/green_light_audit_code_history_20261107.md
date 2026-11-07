# Green Light regression audit — code/history input (PARKED, 2026-11-07)

**Status: PARKED input to P1-7 (execution-order step 5). Not the step-5 report. No action taken.**
Read-only code/history pass against `origin/master` @ `3d7cda1`, started before the program reset and finished after
it. Nothing was edited, run or deployed. Production data states were **not** checked; the live signed-in read was
stopped at the reset (one observation: all 12 workspace lenses showed LOADING after page load, matching D3).
Line numbers "M:" refer to `git show origin/master:app.py`. Findings are code readings and must be re-verified
when step 5 opens.

## 1. Baseline — last classic-default state
- Baseline commit **`9055594`** (2026-10-21), parent of **`9057ba1`**, which flipped the default to the workspace.
  The classic engine/template are unchanged from `614b5d9` to `9055594`; the only later classic-template change is
  the 5-line banner added by `9057ba1`.
- Owner approval of `9057ba1` is not evidenced in code. Its message cites "adapters… green on prod". The frozen
  preferences contract `103ecb1` (`docs/green_light_preferences_contract.md:14-16`) says a user with no saved
  preferences sees "today's default board unchanged (full reversibility)"; the flip contradicts that.
- Classic inventory at baseline: `/tools/green-light` → `build_green_light(limit=40, pos=None)` (M:32807), NFL only,
  PRO-gated. Universe = featured non-defense players from `build_nfl_usage_board(limit=600)`; primary over only (Rush
  Yds backs / Rec Yds others); props from `_nfl_wisdom_props()` (FanDuel rows of `NFL_Props.csv`).
  Lenses: Opportunity (M:32844), Matchup (M:32855), Game Identity (M:32866), Coaching (M:32885, static JSON),
  Concentration (M:32892, TD corroborator, not counted). Inclusion via shared
  `services/nfl_inclusion.green_light_lens_verdict` (≥1 lens or TD angle). Market line-state `_wisdom_market_gate`
  (display only). Fragile flag (M:32902). Position filter All/QB/RB/WR/TE (M:32931). Sort −convergence, game,
  player, stat (M:32942); tiers "4+/3/2/1 configured lenses". Links: Player Check, King's Tickets (fresh ticket, no
  state carried, `614b5d9`). Learning receipt: `capture_green_light.py` → `GreenLight_Archive.csv`, graded by
  `grade_lenses.py`, both in `run_daily.py:147-148`.

## 2. Present on master
- `?view=classic` (M:46595-46596): `build_green_light` and its helpers are **byte-identical** to baseline; template
  differs only by the banner (`green_light.html:6-10`).
- Default workspace: none of its 12 lenses (`services/green_light_lenses.py:21-34`) is a convergence lens. Missing:
  convergence count/tiers, per-player why-chips, fragile/TD notes, position filter, line-state badge, Player Check
  link. Its "proposed ticket" (`/tools/green-light/ticket`, M:46644) is `build_daily_cards` output, not derived from
  convergence. Workspace output is not archived; the daily harness still archives the classic engine.

## 3. Hidden only by the default change
The whole convergence board; the Player Check ↔ Green Light explainer loop (Player Check M:33192-33200 still reports
convergence/rank/"select the position", meaningful only on classic); the attribution harness grading plays the
default UI no longer shows; sidebar (`_sidebar.html:54`) and King's Tickets back-links land on the workspace.

## 4. Integrity remediation history
| Commit | Change | Claim vs capability |
|---|---|---|
| `60226f6` | Tier names → "4+/3/2/1 configured lenses"; "independent" → "configured"; Under-Review disclosure | Claim removed; membership unchanged |
| `c4ca828` S6 | Sort (eligible, convergence, opp_score) → −convergence + game/player/stat; gate notes → observable line-state; Eligible/Priced-in badge removed; footer "not a best-bets board" | Claim removed; capability changed (eligible-first ordering + opp_score tiebreak; `eligible` still computed/archived) |
| `c4ca828` S5 | Wind-under → "historical backtest ~55%, governance not yet assigned" | Claim removed — **later regressed** |
| `0185a91` | Shared inclusion predicate (parity proven) | Refactor |
| `614b5d9` | Honest King's Tickets CTA | Capability added |

**Regression after containment (default path):** "validated totals-under flag" returned at M:46297
(`_GL_LENS_SOURCE['weather']`), M:46464 (`_gl_adapt_weather`) — via `f67b212`/`0a91142` — and M:51520 (Matchup
Center, `5f11b5b`). Contradicts `c4ca828` S5.

## 5. Workspace lens adapters (M:46315-46514) — code-level empty/stale/unavailable causes
Envelope: `services/green_light_adapters.build_envelope` (empty→UNAVAILABLE, all gated→GATED, all stale→STALE);
`safe_adapter` turns exceptions into abstain.
- **heat_map** — `build_nfl_hot_hand`; resolver depends on `NFL_SEASON_WEEK1_THURSDAY`; adapter **drops
  `unavailable_reason`** (every cause reads "no current-season hot runs").
- **riding_the_wave** — UNAVAILABLE only if hot AND situational are empty; multi-year situational runs keep it
  "available" when the current-season part is empty; ignores `rw_meta.hot_unavailable`; `data_through` may be last
  season.
- **milestone_streaks** — passes `unavailable_reason`; season items stale when `season_available` false.
- **market_line_streaks** — `NFL_AllPropResults.csv`; unavailable when the current season isn't graded (depends on
  `NFL_GameLogs.csv` carrying it).
- **ats_waves** — NFL fails closed on sidecar/freshness; CFB fails closed when unsynced (CFBD 429 ⇒ no publish ⇒
  stale ⇒ unsynced); **exceptions swallowed** (`except: pass`); CFB season hardcoded 2026 (M:48036); envelope sport
  'nfl' for CFB items.
- **matchup_context** — UNAVAILABLE with no slate; stale odds withhold lines (M:51393-51395).
- **whats_changed** — injury changes never feed it: M:51408 expects a dict from `build_nfl_injury_changes`, which
  returns a **list** (M:7142-7161) ⇒ `inj_by_team` always `{}` (code reading; verify).
- **contradictions** — single rule (wind + team over-trend, M:51529-51533) needs licence-gated weather ⇒
  structurally empty; note conflates "none" with "unavailable"; declared scope mlb/nba/wnba/cfb but NFL-only.
- **injuries_return** — no freshness check (`data_through=None`, ignores `_nfl_injury_source_state` budget);
  label promises return-from-participation the source lacks; no college injury source.
- **weather** — `BK_WEATHER_SOURCE_LICENSED` off by default (M:17265) ⇒ `{}` but note says "no outdoor wind data"
  (misattributes licence gate); "validated" wording (§4).
- **line_movement** — `NFL_LineMovementCurrent.csv`; no staleness / completed-game filter.
- **governed_models** — always GATED by design.
- `BK_NBA_STATS_ENABLED` affects no Green Light path. Kickoff/provenance gates apply only inside the lazy ticket.
- Classic engine causes: empty nflverse log or no FanDuel rows ⇒ misleading "Wisdomism" empty state (template :87);
  usage season = `max(season)` (M:32430), not the shared resolver; coaching/concentration JSONs static.

## 6. Would restoring classic as default reintroduce dishonest claims?
No lock/conviction/edge-tier claim returns — the remediations live inside the classic path (M:32942-32950,
M:32790-32804, template :61/:93/:112/:120). Residual risks: (1) subtitle :61 faint "already in the number" framing;
(2) **quote provenance** — prices shown with no book label or source time; `_nfl_wisdom_props` ignores
`SourceUpdatedAtUTC` (below the `17b5e69` standard); (3) **no kickoff gate** (`EventCommenceAtUTC` unread);
(4) unrendered docstrings still say "INDEPENDENT… un-priced first"; (5) `max(season)` basis.
The current workspace has its own regressions ("validated"; Daily-Card ticket placed under "Green Light").

## 7. Smallest reversible restoration plan (described only — NOT authorized)
1. Forward edit (not a revert of `9057ba1`): classic default, workspace on `?view=workspace`, `?view=classic` alias;
   POST redirect → workspace; swap banner/back-link; invert `qc_green_light_workspace.py:55-68`.
2. Same release: carry `EventCommenceAtUTC`/`SourceUpdatedAtUTC`/`Book`/`EventId` through `_nfl_wisdom_props`;
   `_kickoff_gate_failure` (M:33407); price only with book + `_source_time_label` (never `LastUpdated`); bump
   `BOARD_VERSION` (`capture_green_light.py:43`); new classic kickoff/provenance QC; re-run inclusion-parity,
   Player Check and lens-attribution QCs.
3. Keep fresh-ticket CTA; any per-play hand-off via `_leg_quote_failures`, no URL state, blocked on King's Tickets
   storage review. Cheap: per-row Player Check / Matchup Center links. Learning receipt unchanged except version.
4. Keep neutral sort, configured-lens tiers, Under-Review copy, shared predicate, workspace envelope framework.
5. Separate hygiene items, each with its own QC: "validated" wording ×3; weather licence note; contradictions
   "unavailable"; list/dict at M:51408; "Wisdomism" empty state; pass `unavailable_reason` in heat_map / RtW.

**Open uncertainties:** owner approval of `9057ba1`; cold latency of classic-as-default (`_nfl_wisdom_props`
uncached); whether started-game rows appear in prod props; all production data states.
