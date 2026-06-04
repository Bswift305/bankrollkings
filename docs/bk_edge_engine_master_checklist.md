# Bankroll Kings Edge Engine Master Checklist

This is the build map for turning Bankroll Kings from a prop board into a sport-specific simulation and calibration platform.

Source document:

- `C:/Users/Decatur/Downloads/BK_Edge_Engine_Work_Instruction.docx`
- Instruction ID: `BK-WI-001`
- Version: `1.0`
- Reviewed into this checklist on `2026-05-27`

Core principle:

> One brand engine, separate sport formulas, separate calibration loops.

The system should not become one universal formula. It should become a formula family:

- BK Edge Engine
- BK NFL EdgeScore
- BK NFL PropScore
- BK NBA EdgeScore
- BK WNBA EdgeScore
- BK MLB PitcherScore / HitterScore
- BK Correlation Engine
- BK BankrollIQ
- BK Calibration Lab

Repeatable pipeline:

- [x] `run_bk_edge_engine_pipeline.py` runs the current Edge Engine build chain end-to-end.
- [x] Latest successful run log: `logs/bk_edge_engine_pipeline_20260528_080600.log`.
- [x] Latest successful all-scorecard log: `logs/all_scorecards_20260528_054340.log`.
- [x] Latest successful daily operator log: `logs/daily_operator_20260527_141936.log`.
- [x] Latest run-status artifact: `data/tracking/Run_Status.json`, overall `GREEN`, `14` fresh checks.

Current checkpoint - 2026-05-28:

- [x] NFL EdgeScore, PropScore, and simulation probability are visible on NFL board rows.
- [x] NFL promotion signals are attached to live and historical NFL prop rows.
- [x] NBA, WNBA, and MLB active-sport simulation v1 outputs are generated.
- [x] Active sport simulations are included in the shared Edge Engine pipeline.
- [x] Dashboard run status tracks active simulations as a first-class precheck.
- [x] Convert active-sport simulation v1 from backtest-style distributions to rolling/prior-only windows before using it as live-board authority.
- [x] Calibrate NBA simulation scoring before surfacing it as a live-board authority signal.
  - Decision: NBA simulation is WATCH-only for now, not LIVE_AUTHORITY.
  - Current strongest NBA sim buckets: `BLK UNDER`, `3PM UNDER`, `STL OVER`, and `PTS UNDER`.
- [x] Calibration and backfill discipline now run before visual QA.
  - Latest Edge Engine pipeline passed NFL backfill/scoring/simulation, active sport simulations, team priors, MLB context/umpires/weather, metadata normalization, sport-driver calibration, cross-sport calibration, promotion inputs, streak heat, drift alerts, and formula status.
  - Latest scorecard pass confirms NBA, WNBA, MLB, NFL, and prelaunch checks are clean after injury refresh.
  - Visual QA is intentionally the final closeout gate, not the next build step.

## Phase 0 - Current Foundation Audit

- [x] Identify existing NFL historical scripts.
  - Existing: `build_nfl_player_stats_from_pbp.py`
  - Existing: `build_nfl_historical_calibration.py`
  - Existing: `backfill_nfl_historical_props.py`
  - Existing: `calibrate_nfl_model.py`
- [x] Identify shared calibration engine.
  - Existing: `services/model_calibration.py`
- [x] Identify existing scorecard layer.
  - Existing: `run_nfl_99_scorecard.py`
  - Existing: `run_nba_99_scorecard.py`
  - Existing: `run_wnba_99_scorecard.py`
  - Existing: `run_mlb_99_scorecard.py`
- [x] Identify current public explanation surface.
  - Existing: `/systems-lab`
- [x] Review `BK_Edge_Engine_Work_Instruction.docx`.
- [x] Check critical bug list from the work instruction against the current repo.

Critical bug status from `BK-WI-001`:

- [x] `fetch_game_lines.py`: fixed. `fetch_events()` uses `sport`, not undefined `SPORT`.
- [x] `app.py`: fixed. `split_game_label()` exists.
- [x] `app.py`: fixed. MLB context uses `load_mlb_game_market_odds()`, not missing `load_mlb_odds()`.
- [x] `app.py`: fixed. Duplicate `_safe_int` cleanup completed.
- [x] `app.py`: acceptable. Only one `build_matchup_lens_hub_context()` definition found in current repo.
- [x] `floor_parlay_builder.py`: fixed. Removed machine-specific working-directory assumption and moved to `BASE_DIR`.

Done means:

- We know which code already exists and which pieces are still missing before building new logic.
- The work-instruction blocker list is cleared before Phase 1 scripts run.

## Phase 1 - NFL Historical Data Baseline

Goal:

Use the completed 2025 NFL season to create a preseason-ready NFL formula baseline.

Tasks:

- [x] Confirm available 2025 NFL historical files.
  - `data/historical/NFL_Props_History.csv` exists.
  - `data/historical/NFL_Games_nfldata.csv` exists.
  - Current inventory shows seasons `2024` and `2025`.
- [ ] Confirm whether additional player game-log/stat files are needed for PropScore usage inputs.
- [x] Confirm historical props schema.
  - Includes `SnapshotDate`, `Season`, `Week`, `Player`, `Team`, `Opponent`, `Stat`, `Line`, `Actual`, `Book`, `OverOdds`, `UnderOdds`, `Game`, `AwayTeam`, `HomeTeam`, `AwayAbbr`, `HomeAbbr`.
- [x] Confirm game context schema.
  - Includes `season`, `week`, `gameday`, `away_team`, `home_team`, `spread_line`, `total_line`, `wind`, `temp`, `roof`, `surface`, `away_rest`, `home_rest`.
- [x] Normalize all NFL historical props into one schema.
  - Player
  - Team
  - Opponent
  - Season
  - Week
  - GameDate
  - Stat
  - Line
  - OverOdds
  - UnderOdds
  - Actual
  - Book
- [x] Normalize all NFL game context into one schema.
  - Spread
  - Total
  - Home/away
  - Wind
  - Temperature
  - Roof
  - Rest days
  - Divisional game
- [x] Generate `data/tracking/NFL_AllPropResults.csv` from 2025 backfill.
- [x] Preserve `IsBackfill = True` on historical rows.
- [ ] Preserve live rows separately as `IsBackfill = False`.
- [x] Run `py build_nfl_historical_calibration.py`.
- [x] Verify `data/tracking/NFL_AllPropResults.csv` row count is greater than 0.
- [x] Verify `OutcomeState` contains only `Hit`, `Miss`, `Push`, or `Pending`.
- [x] Verify console hit rate is between 45% and 80%.
- [x] Confirm `NFL_GameScript_Calibration_Report.csv` exists.
- [x] Confirm `NFL_Player_Hit_Profiles.csv` exists.

Done means:

- NFL has resolved historical rows before the next season starts.
- We can filter NFL results by backfill vs live.
- We can grade 2025 NFL props without manual work.

Current Phase 1 status:

- Historical inputs exist.
- `NFL_AllPropResults.csv` rebuilt successfully.
- Output: `34,788` rows.
- Resolved: `32,980` rows.
- Pending: `1,808` rows.
- Seasons: `2024`, `2025`.
- Outcome hit rate: `50.0%`.
- Top game-script signals from the rebuild:
  - `WIND_PASS_OVER_RISK`: `37.7%` hit rate on `353` rows.
  - `WIND_UNDER_SUPPORT`: `57.3%` hit rate on `206` rows.
  - `TRAILING_RB_RUSH_OVER_RISK`: `44.6%` hit rate on `439` rows.
  - `TRAILING_RB_UNDER_SUPPORT`: `55.4%` hit rate on `439` rows.

## Phase 2 - NFL Formula v1

Goal:

Create the first explicit NFL scoring formula.

Formula:

`BK NFL EdgeScore = Projection Edge + Market Edge + Matchup Edge + Game Script Edge - Risk Penalty`

Tasks:

- [x] Create `calculate_nfl_edge_score.py`.
- [x] Define `Projection Edge`.
  - Team strength
  - Offensive efficiency
  - Defensive weakness
  - Expected pace
- [x] Define `Market Edge`.
  - No-vig implied probability
  - Book disagreement
  - Opening vs current vs closing line
  - Best available book
- [x] Define `Matchup Edge`.
  - Offense strength vs defense weakness
  - Position-specific defensive weakness
  - Scheme if available
- [x] Define `Game Script Edge`.
  - Favorite/underdog
  - Spread size
  - Total
  - Projected pass/run environment
- [x] Define `Risk Penalty`.
  - Injury
  - Weather
  - Short rest
  - Travel
  - Volatility
  - Divisional game
- [x] Output score fields onto each NFL row.
  - `ProjectionEdge`
  - `MarketEdge`
  - `MatchupEdge`
  - `GameScriptEdge`
  - `RiskPenalty`
  - `BK_NFL_EdgeScore`
- [x] Write scored output to `data/tracking/NFL_AllPropResults_Scored.csv`.
- [x] Add `/sports/nfl/edge-score` route or equivalent NFL board surface.
  - Added `/nfl-formula-lab`.

Done means:

- Every NFL side/total/team-total row can explain why it graded the way it did.
- The score is not just one opaque number.

Current Phase 2 status:

- `calculate_nfl_edge_score.py` built and executed.
- Output file: `data/tracking/NFL_AllPropResults_Scored.csv`.
- Required columns present:
  - `ProjectionEdge`
  - `MarketEdge`
  - `MatchupEdge`
  - `GameScriptEdge`
  - `RiskPenalty`
  - `BK_NFL_EdgeScore`
  - `ModelVersion`
- Backtest shape:
  - EdgeScore `20+`: `70.2%` hit rate on `104` resolved rows.
  - EdgeScore `10-20`: `54.8%` hit rate on `5,402` resolved rows.
  - EdgeScore `0-10`: `50.3%` hit rate on `23,237` resolved rows.
  - EdgeScore `<0`: `41.9%` hit rate on `4,237` resolved rows.
- Status: v1 has the correct directional shape, but needs calibration before UI promotion.
- UI surface:
  - `/nfl-formula-lab` now shows EdgeScore bands, PropScore bands, simulation probability bands, promote/reduce buckets, and human calibration notes.

## Phase 3 - NFL PropScore v1

Goal:

Create a separate formula for NFL player props.

Formula:

`BK NFL PropScore = Usage Stability + Matchup Advantage + Game Script Fit + Line Value - Volatility`

Tasks:

- [x] Create `calculate_nfl_prop_score.py`.
- [x] Build usage stability inputs.
  - Snap share
  - Route participation
  - Target share
  - Rush share
  - Red-zone usage
- [x] Build matchup advantage inputs.
  - WR/TE vs defense
  - RB rushing environment
  - QB pressure environment
  - Defensive/sack context
- [x] Build game-script fit inputs.
  - Trailing pass volume
  - Leading rush volume
  - Blowout risk
  - Low-total suppression
- [x] Build line value inputs.
  - Current line vs player projection
  - Best book
  - Book disagreement
  - Market movement
- [x] Build volatility penalties.
  - Injury
  - Weather
  - Role uncertainty
  - Thin sample
  - Bad market gate
- [x] Output score fields onto each NFL prop row.
  - `UsageStability`
  - `MatchupAdvantage`
  - `GameScriptFit`
  - `LineValue`
  - `VolatilityPenalty`
  - `BK_NFL_PropScore`
- [x] Route logic by `RoleLabel`.
  - `PASSING`
  - `RUSHING`
  - `RECEIVING`
  - `UNSPECIFIED`
- [x] Append PropScore fields to `NFL_AllPropResults_Scored.csv`.

Done means:

- QB, RB, WR, TE, and defensive props can be graded by separate logic.
- NFL props are not treated like NBA or MLB props.

Current Phase 3 status:

- `calculate_nfl_prop_score.py` built and executed.
- Output appended to `data/tracking/NFL_AllPropResults_Scored.csv`.
- Required columns present:
  - `UsageStability`
  - `MatchupAdvantage`
  - `GameScriptFit`
  - `LineValue`
  - `VolatilityPenalty`
  - `BK_NFL_PropScore`
  - `PropModelVersion`
- Backtest shape:
  - PropScore `25+`: `66.3%` hit rate on `2,171` resolved rows.
  - PropScore `15-25`: `61.1%` hit rate on `5,973` resolved rows.
  - PropScore `0-15`: `52.7%` hit rate on `9,374` resolved rows.
  - PropScore `<0`: `41.7%` hit rate on `15,462` resolved rows.
- Status: v1 has strong directional separation, but needs calibration before it drives live promotion.

## Phase 4 - NFL Simulation v1

Goal:

Move from one projection to probability distributions.

Tasks:

- [x] Create `simulate_nfl_props.py`.
- [x] Define the first simulation scope.
  - Start with player props, not full game simulation.
  - Start with QB pass yards, RB rush yards, WR receptions, WR receiving yards.
- [x] Build outcome distributions from 2025 data.
  - Player average
  - Standard deviation
  - Usage stability
  - Game-script adjustment
  - Weather adjustment
- [x] Simulate each prop 5,000 to 10,000 times.
- [x] Convert simulated outcomes to hit probability.
- [x] Compare simulated probability to model confidence.
- [x] Store:
  - `SimMean`
  - `SimMedian`
  - `SimP25`
  - `SimP75`
  - `SimHitProbability`
  - `SimVolatility`
- [x] Store `SimEdgePct`.
- [x] Write simulation output to `data/tracking/NFL_Simulation_Results.csv`.

Done means:

- A prop can say: "This line hit in 63.4% of simulations," not just "confidence 63."

Current Phase 4 status:

- `simulate_nfl_props.py` built and executed.
- Output file: `data/tracking/NFL_Simulation_Results.csv`.
- Simulation rows: `26,066`.
- Resolved simulation rows: `24,638`.
- First scope:
  - `PASS YDS`
  - `RUSH YDS`
  - `RECEPTIONS`
  - `REC YDS`
- Backtest shape:
  - Sim probability `70+`: `70.4%` actual hit rate on `2,604` resolved rows.
  - Sim probability `60-70`: `58.4%` actual hit rate on `4,040` resolved rows.
  - Sim probability `50-60`: `52.3%` actual hit rate on `5,731` resolved rows.
  - Sim probability `<50`: `41.8%` actual hit rate on `12,263` resolved rows.
- Status: v1 simulation is directionally calibrated enough to surface in a lab view, but should stay marked as historical/backtest until live 2026 rows arrive.

Active sport simulation v2:

- `simulate_active_sport_props.py` now builds rolling/prior-only simulation outputs for active sports.
- Each slate is simulated only from resolved results known before that slate date.
- Output rows are stamped with `SimulationMode=ROLLING_PRIOR_ONLY`, `AsOfDate`, and `TrainingResolvedRows`.
- Current outputs:
  - `data/tracking/NBA_Simulation_Results.csv`
  - `data/tracking/WNBA_Simulation_Results.csv`
  - `data/tracking/MLB_Simulation_Results.csv`
  - `data/tracking/Active_Sport_Simulation_Summary.csv`
- Latest run:
  - NBA: `2,341` simulation rows, `373` high-calibrated rows, `57.1%` hit rate on high-calibrated resolved rows.
  - WNBA: `1,178` simulation rows, `228` high-calibrated rows, `64.7%` hit rate on high-calibrated resolved rows.
  - MLB: `20,672` simulation rows, `4,675` high-calibrated rows, `71.7%` hit rate on high-calibrated resolved rows.
- Authority layer:
  - NBA: `407` WATCH rows, `56.2%` hit rate on resolved authority rows. No NBA rows are marked `LIVE_AUTHORITY` yet.
  - WNBA: `418` WATCH/LIVE_AUTHORITY rows, `58.3%` hit rate on resolved authority rows.
  - MLB: `7,526` WATCH/LIVE_AUTHORITY rows, `66.3%` hit rate on resolved authority rows.
- Status: MLB is strongest under calibrated no-leakage simulation. WNBA is useful but needs more resolved rows. NBA is correctly limited to WATCH-only buckets until it earns live authority.

## Phase 5 - NFL Calibration Lab

Goal:

Backtest the NFL formula and adjust weights before the season.

Tasks:

- [x] Run `py calibrate_nfl_model.py`.
- [x] Run NFL calibration on 2025 backfilled rows.
- [x] Split calibration by market type.
  - Spread
  - Total
  - Team total
  - QB props
  - RB props
  - WR/TE props
  - Sack/defensive props
- [x] Split calibration by confidence band.
  - 50-60
  - 60-70
  - 70-80
  - 80+
- [x] Split calibration by game-script tag.
  - Projected trail
  - Projected blowout win
  - Low total
  - High total
  - Wind game
  - Short rest
- [x] Identify overconfident buckets.
- [x] Identify underweighted strong buckets.
- [x] Write calibration recommendations into `NFL_Calibration_Report.csv`.
- [x] Write formula-family summary into `NFL_Formula_Calibration_Summary.csv`.
- [x] Write human notes into `Calibration_Notes_NFL_2025.txt`.
- [ ] Make formula changes only when sample size is large enough.

Current Phase 5 status:

- Calibration report generated at `data/tracking/NFL_Calibration_Report.csv`.
- Formula-family summary generated at `data/tracking/NFL_Formula_Calibration_Summary.csv`.
- Human notes generated at `data/tracking/Calibration_Notes_NFL_2025.txt`.
- Resolved rows: `32,980`.
- Pending rows: `1,808`.
- Overall hit rate: `50.0%`.
- Initial lying buckets:
  - `HOLD`: `41.4%` actual vs `55.0%` expected on `804` rows.
  - `OVER | STABLE | HOLD`: `41.4%` actual vs `55.0%` expected on `804` rows.
  - `RUSH ATT | OVER | 50-60`: `44.9%` actual vs `55.0%` expected on `726` rows.
- Initial recommendation:
  - Reduce HOLD / Rush Attempts OVER trust by roughly `15%` and monitor next cycle.
- Formula-family notes:
  - Simulation probability `70+`: `70.3%` actual on `2,572` rows.
  - PropScore `25+`: `66.6%` actual on `2,110` rows.
  - Wind under support: `62.5%` actual on `365` rows.
  - Wind pass over risk: `37.5%` actual on `365` rows.
  - MarketGate `HOLD`: `41.4%` actual on `804` rows.

Done means:

- If the model says 70-80%, we know whether those rows actually hit near 70-80%.
- The system can tell us where the NFL formula is lying.

## Phase 6 - Cross-Sport Calibration Standard

Goal:

Use the same calibration workflow across sports, but not the same formula weights.

Universal calibration questions:

- [x] Did projected confidence match actual hit rate?
- [x] Did high-confidence props outperform low-confidence props?
- [ ] Did CLV move in our favor?
- [x] Which buckets were overvalued?
- [x] Which buckets were undervalued?
- [x] Which player profiles were reliable?
- [x] Which market gates added value?
- [x] Which volatility flags mattered?
- [x] Which missed winners should have been promoted?

Done means:

- Every sport gets the same calibration report structure.
- Every sport keeps its own weighting logic.

Current Phase 6 status:

- `generate_cross_sport_calibration_summary.py` built and executed.
- Output file: `data/tracking/CrossSport_Calibration_Summary.csv`.
- Notes file: `data/tracking/CrossSport_Calibration_Notes.txt`.
- `/calibration-lab` route added.
- `generate_promotion_signal_inputs.py` built and executed.
- Player reliability output: `data/tracking/CrossSport_Player_Reliability_Summary.csv`.
- Missed winner promotion output: `data/tracking/Missed_Winner_Promotion_Candidates.csv`.
- Promotion notes: `data/tracking/Promotion_Signal_Notes.txt`.
- Player reliability rows: `5,661`.
- Missed winner promotion candidates: `6,041`.
- Current cross-sport read:
  - NBA: `2,042` resolved, `51.3%` overall, `55.8%` on `509` high-confidence rows.
  - WNBA: `452` resolved, `56.0%` overall, `47.6%` on only `21` high-confidence rows.
  - MLB: `17,901` resolved, `49.2%` overall, `78.5%` on `4,157` high-confidence rows.
  - NFL: `32,980` resolved, `50.0%` overall, `100.0%` on only `7` high-confidence rows.
  - NCAAF: no usable rows yet.

## Phase 7 - Sport-Specific Calibration Modules

### NBA

- [x] Calibrate by minutes.
- [x] Calibrate by usage.
- [ ] Calibrate by pace.
- [ ] Calibrate by rotation/teammate injury.
- [x] Calibrate by stat type.
- [x] Calibrate by player reliability.

Primary driver:

`Minutes + Usage + Pace + Role Change`

Current NBA status:

- `calibrate_nba_model.py` rerun successfully.
- Driver calibration artifact: `data/tracking/Sport_Driver_Calibration.csv`.
- Current driver proxy: `Minutes/Usage Proxy = Stat + Direction + RoleLabel`.
- Player reliability is available through `CrossSport_Player_Reliability_Summary.csv`.
- Current caution: `PTS OVER` and some `AST OVER` buckets are overtrusted.
- Current support: `Floor Play UNDER`, `REB UNDER`, `BLK UNDER`, and `STL OVER` buckets.

### WNBA

- [x] Calibrate separately from NBA.
- [x] Use WNBA-specific player profiles.
- [x] Track floor UNDER performance.
- [x] Track team/rotation stability.
- [x] Track small-sample warnings harder than NBA.

Primary driver:

`Minutes + Role Stability + Floor Reliability`

Current WNBA status:

- `calibrate_wnba_model.py` rerun successfully.
- Driver calibration artifact: `data/tracking/Sport_Driver_Calibration.csv`.
- Current driver buckets: `Role Stability` and `Stat Direction`.
- Current support: `Market Edge UNDER`, `Floor Plays UNDER`, `REB UNDER`, and `AST UNDER`.
- Current caution: `70-80` confidence and `AST OVER 50-60` are not earning their confidence yet.

### MLB

- [x] Calibrate by pitcher props.
- [x] Calibrate by hitter props.
- [x] Calibrate by ballpark.
- [x] Calibrate by weather.
- [ ] Calibrate by pitcher/batter matchup.
- [x] Calibrate by book disagreement.

Primary driver:

`Pitcher/Batter Context + Park + Weather + Market`

Current MLB status:

- `fetch_mlb_weather_context.py` built and executed.
- Weather sidecar output: `data/context/MLB_WeatherContext.csv`.
- Weather rows: `15`.
- Missing temperature: `0`.
- Missing wind: `0`.
- `build_mlb_game_context.py` rerun after weather sidecar.
- Game context rows: `15`.
- Missing ballparks: `0`.
- Missing weather: `0`.
- Missing umpires: `15`.
- `calculate_mlb_context_scores.py` built and executed.
- Scored output: `data/tracking/MLB_AllPropResults_Scored.csv`.
- Calibration summary: `data/tracking/MLB_Formula_Calibration_Summary.csv`.
- Human notes: `data/tracking/Calibration_Notes_MLB_2026.txt`.
- `/mlb-formula-lab` route added.
- Rows scored: `25,180`.
- Resolved rows: `17,901`.
- ContextScore `20+`: `87.5%` actual on `1,586` rows.
- Promote candidate:
  - `STOLEN BASES | UNDER`: `94.4%` actual on `839` rows.
- Reduce-trust candidates:
  - `STOLEN BASES | OVER`: `4.0%` actual on `708` rows.
  - `BATTER WALKS | OVER`: `28.4%` actual on `659` rows.
- Caveat:
  - Weather is now automatic through Open-Meteo forecast data.
  - Umpire assignment handling now has a managed sidecar/template flow through `build_mlb_umpire_context.py`.
  - Current slate still needs actual umpire names before the umpire layer can become a full `PASS`.
- MLB 99% scorecard after weather:
  - Decision: `MLB 99% READY`.
  - Pass: `9`.
  - Watch: `2`.
  - Fail: `0`.
- Watch items: missing selected markets (`Batter Strikeouts`, `Pitcher Walks`) and missing umpire assignments.
- Umpire context status:
  - `data/context/MLB_UmpireAssignments.csv` is rebuilt from the slate schedule.
  - `data/context/MLB_UmpireProfiles.csv` exists as the profile lookup sidecar.
  - Current assignment rows: `15`.
  - Confirmed umpires: `0`.
  - Needs assignment: `15`.

### NFL

- [x] Calibrate by EPA/game script.
- [x] Calibrate by usage.
- [x] Calibrate by weather.
- [ ] Calibrate by injury.
- [x] Calibrate by market type.

Primary driver:

`EPA + Usage + Game Script + Weather`

Current NFL status:

- NFL 99% scorecard adjusted for formula-lab/offseason mode.
- Live prop absence is now a `WATCH` when historical formula data exists, not a hard formula failure.
- Latest NFL scorecard:
  - Decision: `NFL 99% READY`.
  - Pass: `7`.
  - Watch: `2`.
  - Fail: `0`.
  - Historical formula rows: `32,980` resolved, `1,808` pending.
- Driver calibration artifact: `data/tracking/Sport_Driver_Calibration.csv`.
- Current NFL driver buckets: `EPA/Game Script Proxy`, `Total Script`, `Spread Script`, `Weather Script`, `Game Script Tags`, and `Risk Tags`.

### NCAAF

- [x] Calibrate by returning production.
  - Game-line formula lane added through `calculate_ncaaf_edge_score.py`.
  - Returning production contributes to `CFBTeamContextScore`.
- [x] Calibrate by transfer/roster volatility.
  - Portal in/out and player-master transfer flags contribute to the NCAAF team context profile.
- [ ] Calibrate by scheme and pace.
- [ ] Calibrate by opponent quality.

Primary driver:

`Roster Turnover + Scheme + Pace`

Current NCAAF status:

- NCAAF is now treated as a game-line and totals product first, not a prop-heavy product.
- Formula doc: `docs/ncaaf_game_line_formula.md`.
- CFBD historical line fetcher added: `fetch_cfbd_game_lines_history.py`.
- Game-line backfill grader added: `build_ncaaf_game_line_backfill.py`.
- EdgeScore scorer added: `calculate_ncaaf_edge_score.py`.
- Historical TeamRankings research importer added: `import_teamrankings_ncaaf_historical_stats.py`.
  - Output: `data/historical/NCAAF_TeamRankings_2025_TeamStats.csv`.
  - Current import: `136` teams, `20` curated stat pages, `2720` long-form rows.
  - Use: last-season formula research only; 2026 live product should use official/API-based feeds.
- `calibrate_cfb_model.py` now prefers `NCAAF_GameLineResults_Scored.csv` over prop-only featured rows.
- Current blocker: `CFBD_API_KEY` is not configured locally and `data/historical/NCAAF_GameLines_History.csv` currently contains only headers.
- Current live Odds API NCAAF board is offseason-empty, so live lines will populate closer to football season.

### CBB

- [ ] Calibrate by tempo.
- [ ] Calibrate by efficiency.
- [ ] Calibrate by travel/rest.
- [ ] Calibrate by matchup style.

Primary driver:

`Tempo + Efficiency + Matchup Style`

Done means:

- Calibration says "NFL weather is overweighted" or "WNBA floor UNDERs are strong," not generic advice.

## Phase 8 - Live vs Backfill Separation

Goal:

Do not let historical data hide current-season drift.

Tasks:

- [x] Add `IsBackfill` to every historical result row.
- [x] Add `Season` to every result row.
- [x] Add `ModelVersion` to every scored row.
  - Current script: `normalize_result_metadata.py`.
  - NBA rows stamped live `2025-26`.
  - WNBA and MLB rows stamped live `2026`.
  - NFL rows stamped backfill `2024,2025`.
- [x] Compare backfill hit rate vs live hit rate.
- [x] Create drift alerts.
  - 30-day live hit rate vs all-time
  - current season vs backfilled season
  - featured vs unplayed
  - CLV trend vs hit-rate trend
  - Current script: `generate_drift_alerts.py`.
  - Current output: `data/tracking/Live_Drift_Alerts.csv`.
  - Current notes: `data/tracking/Live_Drift_Notes.txt`.
  - Latest run wrote `25` drift rows.

Done means:

- If 2025 backtest was strong but 2026 live starts weak, the system catches it early.

## Phase 9 - UI Surfaces

Goal:

Make the quant layer visible without overwhelming users.

Tasks:

- [x] Add NFL EdgeScore explanation to NFL board rows.
  - `app.py` attaches NFL EdgeScore details from `NFL_AllPropResults_Scored.csv`.
  - `templates/football_method_board.html` shows EdgeScore plus projection, market, script, and risk components.
- [x] Add NFL PropScore explanation to NFL prop rows.
  - `app.py` attaches NFL PropScore details from scored output.
  - `templates/football_method_board.html` shows usage, matchup, game-script, and line-value components.
- [x] Add simulation probability card.
  - `app.py` attaches simulation hit probability from `NFL_Simulation_Results.csv`.
  - NFL method pages now add a simulation summary card when matching rows are present.
  - `templates/football_method_board.html` shows sim hit probability, mean, P25/P75, and volatility on rows.
- [x] Add calibration status card per sport.
- [x] Add sport-specific formula page.
- [x] Add Calibration Lab route.
- [x] Add "formula version" and "last calibrated" labels.
  - Current script: `generate_formula_status.py`.
  - Current outputs: `data/tracking/Formula_Status.json` and `data/tracking/Formula_Status.csv`.
  - `app.py` injects formula status into templates.
  - `templates/bk_base.html` shows a hoverable formula/status badge for the active sport on the new shell.
- [x] Add first-pass formula/driver visibility to NBA prop rows.
  - `app.py` attaches formula fields from `Sport_Driver_Calibration.csv`.
  - `templates/props.html` and `templates/smart_picks_v2.html` display formula read/sample when available.
- [x] Add a check-off table to Systems Lab.
  - `app.py` now passes a `build_checklist` into `/systems-lab`.
  - `templates/quant_systems.html` shows live/build/planned state for the quant system family.

Done means:

- A user can see what the model believes, why it believes it, and whether that belief has been calibrated.

## Phase 10 - Automation

Goal:

Make the process repeatable.

Tasks:

- [x] One command runs NFL historical backfill.
- [x] Create shared Edge Engine pipeline.
  - Current script: `run_bk_edge_engine_pipeline.py`.
  - backfill
  - calibrate
  - score
  - simulate
  - active sport simulations
- [x] One command runs NFL calibration.
- [x] Add all current calibration generators to shared pipeline.
- [x] One command runs all sport calibrations.
- [x] One command rebuilds player profiles.
- [x] One command rebuilds missed winners.
- [x] One command rebuilds streak heat.
  - Current script: `rebuild_streak_heat_index.py`.
  - Current output: `data/tracking/Streak_Heat_Index.csv`.
  - Latest rebuild wrote `1,000` buckets, including `765` buckets with a `3+` hit streak.
- [x] One command refreshes live data.
  - Current script: `run_daily.py`.
  - Supports `--sports nba,wnba,mlb`.
  - Supports `--skip-refresh`, `--skip-edge`, `--skip-scorecards`, and `--continue-on-error`.
- [x] One command runs scorecards.
  - Current script: `run_all_scorecards.py`.
- [x] Create `run_daily.py`.
  - injuries
  - props
  - lines
  - snapshots
  - scorecards
- [x] Dashboard shows last successful run for each.
  - Current script: `generate_run_status.py`.
  - Current outputs: `data/tracking/Run_Status.json` and `data/tracking/Run_Status.csv`.
  - `run_bk_edge_engine_pipeline.py` and `run_daily.py` refresh run status after their log files are written.
  - `templates/dashboard_overview.html` shows a compact daily engine health panel.
  - Run status now includes `Active Simulations`.

Done means:

- We are not manually remembering the daily process.
- The platform tells us what is stale.

Current automation status:

- `run_all_scorecards.py` passes NBA, WNBA, MLB, NFL, and Prelaunch scorecards.
- `run_bk_edge_engine_pipeline.py` passes NFL backfill/scoring/simulation, active sport simulations, MLB weather/context/scoring, result metadata normalization, sport driver calibration, cross-sport calibration, promotion signal generation, streak heat rebuild, live drift alert generation, formula status generation, and run-status refresh.
- `generate_run_status.py` now treats the injury refresh as a data-artifact check against the current injury CSV files, so successful injury refreshes show fresh status even when no wrapper log is written.
- `run_daily.py` dry-run path passed and wrote `logs/daily_operator_20260527_141831.log`.
- `run_daily.py --skip-refresh` passed the Edge Engine and all scorecards, and wrote `logs/daily_operator_20260527_141936.log`.
- Latest all-scorecards clean log: `logs/all_scorecards_20260528_054340.log`.
- Latest Edge Engine clean log: `logs/bk_edge_engine_pipeline_20260528_080600.log`.
- Latest run-status artifact says overall `GREEN` with `14` fresh checks.

## Build Order

1. [x] Confirm NFL 2025 data coverage.
2. [x] Run or repair NFL historical backfill.
3. [x] Produce NFL scored/backfilled result rows with `IsBackfill`.
4. [x] Run NFL calibration report.
5. [x] Define NFL EdgeScore v1 fields.
6. [x] Define NFL PropScore v1 fields.
7. [x] Add NFL simulation v1 for core prop types.
8. [x] Standardize calibration report schema for active sports.
9. [x] Add Calibration Lab UI.
10. [x] Add Systems Lab check-off table.
11. [x] Add dashboard run-status precheck panel.
12. [x] Add NFL formula visibility to board rows.
13. [x] Wire promotion signals into NFL live/historical scoring.
14. [x] Add NBA/WNBA/MLB active-sport simulation v1.
15. [x] Convert active-sport simulation to rolling/prior-only windows.
16. [x] Surface NBA/WNBA/MLB simulation cards on the relevant board rows.
    - NBA props board shows calibrated sim probability with NBA capped at WATCH.
    - WNBA main and method boards show calibrated sim probability and authority status.
    - MLB main and method boards show calibrated sim probability and authority status.
17. [x] Feed promotion boosts into next-day featured-play selection across all active sports.
    - NBA featured play builder applies promotion boosts before the min-confidence feature filter.
    - WNBA and MLB featured flags are recalculated after promotion-sorted ordering.
    - Guardrail/QC still runs after promotion so boosted rows cannot bypass safety checks.
18. [x] Add stake sizing / Kelly bands to the EV and parlay surfaces.
    - Parlay Builder now has a live BankrollIQ panel that converts selected priced legs into a conservative quarter-Kelly stake cap.
    - Elite Cross-Sport EV Builder now shows BankrollIQ label, bankroll cap, and risk note beside true probability, implied probability, EV, and decimal odds.
19. [x] Build correlation matrix v1 for same-game and cross-sport parlays.
    - CorrelationIQ v1 scores duplicate-player, same-game, same-team, same-stat-side, and cross-sport diversification effects.
    - Parlay Builder now updates correlation risk live as legs are selected.
    - Elite Cross-Sport EV Builder now uses the shared CorrelationIQ read and displays pair-level risk notes.
20. [x] Build team-strength priors / ELO-style ratings for game environment.
    - `calculate_team_strength_priors.py` builds `data/tracking/Team_Strength_Priors.csv`.
    - v1 combines market-implied win probability, spread, resolved team prop texture, and NBA net-rating prior where available.
    - Edge Engine pipeline and run-status prechecks now treat Team Priors as a first-class artifact.
    - NBA, WNBA, and MLB board rows now show the team-prior score/read inside the Game Env or Context cell.
    - NBA, WNBA, and MLB boards now show a compact Intelligence Snapshot with top team priors and top calibrated simulation reads.
21. [x] Calibrate NBA simulation weights after the rolling-window conversion.
    - NBA is WATCH-only after calibration; live authority is intentionally withheld.
    - Current WATCH buckets: `BLK UNDER`, `3PM UNDER`, `STL OVER`, `PTS UNDER`.
22. [x] Finish a same-day MLB umpire assignment source.
    - `fetch_mlb_umpire_assignments.py` imports the public RefMetrics same-day assignment board into `data/context/MLB_UmpireAssignments.csv`.
    - The Edge Engine pipeline now runs the assignment fetch before the umpire/context/scoring steps.
    - Latest run confirmed `15` home-plate umpires with `0` missing MLB umpire assignments.
    - Run status now includes `MLB Umpires` as a first-class precheck.
23. [x] Add CLV-vs-hit-rate drift tracking.
    - `generate_drift_alerts.py` now computes line-based CLV from available close/current/bet line fields.
    - Drift alerts include `POSITIVE_CLV_VS_NONPOSITIVE` buckets where enough closing-line rows exist.
    - Latest drift rebuild wrote `33` alerts, including CLV comparison rows for NBA and MLB.
24. [x] Start legacy page conversion onto the new BK shell.
    - `templates/bk_base.html` now supports older `{% block content %}` pages through a compatibility wrapper while preserving the new topbar, logo rail, sidebar, and formula/status badge.
    - First converted pages: `ops.html`, `game_lines.html`, `injuries.html`, and `missed_opportunities.html`.
    - Browser verification passed for `/game-lines`, `/injuries`, `/missed-opportunities`, `/heat-map`, and `/systems-lab` after restarting the local server.
25. [x] Convert the first utility-page batch onto the new BK shell.
    - Converted `info.html`, `glossary.html`, `schedule.html`, `raw_data.html`, and `player_archive.html`.
    - Browser verification passed for `/info`, `/glossary`, `/schedule`, `/raw-data`, and `/player/Josh%20Naylor`.
    - All verified pages kept the new topbar, logo rail, sidebar, compatibility content wrapper, and no horizontal overflow.
26. [x] Convert account and signup surfaces onto the new BK shell.
    - Converted `account.html`, `access_gate.html`, `login.html`, `signup.html`, `password_reset.html`, and `pricing.html`.
    - Added new-theme compatibility styles for `board-shell`, `parlay-surface-soft`, `signup-*`, and `pricing-*` classes so the old account/pricing structure keeps its card polish inside the new cockpit shell.
    - Browser verification passed for `/login`, `/signup`, `/pricing`, `/password-reset`, and `/account`.
27. [x] Convert small support and state pages onto the new BK shell.
    - Converted `test_drive.html`, `under_construction.html`, and `player_not_found.html`.
    - Converted `season_review.html` and `team_season_review.html`; route rendering is heavy and should get a separate performance pass before visual QA.
    - Browser verification passed for `/test-drive`, `/sports/nfl`, and `/player/NoSuchPlayerXYZ`.
28. [x] Convert secondary learning/review pages onto the new BK shell.
    - Converted `elite_learn.html`, `nba_calibration.html`, `bet_review.html`, and `method_hub.html`.
    - Browser verification passed for `/elite/learn`, `/nba-calibration`, `/bet-review`, and `/props/floor`.
    - These are now ready for page-by-page content polish after the high-traffic board pages are migrated.
29. [x] Convert the NBA dashboard family onto the new BK shell.
    - Converted `dashboard.html`, which powers `/sports/nba` and `/matchup-lens`.
    - Browser verification passed for `/dashboard?postseason=1`, `/sports/nba?postseason=1`, and `/matchup-lens?postseason=1`.
    - Verified there is only one `.bk-app` shell and no horizontal overflow on the migrated dashboard routes.
30. [x] Convert active sport dashboards onto the new BK shell.
    - Converted `mlb_dashboard.html`, `wnba_dashboard.html`, and `nfl_dashboard.html`.
    - Flask route checks passed for `/sports/mlb`, `/sports/wnba`, `/sports/nfl`, and `/sports/ncaaf`.
    - Browser lightweight verification passed for `/sports/mlb` and `/sports/wnba`: one `.bk-app`, new topbar/rail/sidebar present, no horizontal overflow.
31. [x] Convert active sport method boards onto the new BK shell.
    - Converted `mlb_method_board.html`, `wnba_method_board.html`, and `football_method_board.html`.
    - Flask route checks passed for representative MLB, WNBA, and NFL method routes.
    - Browser lightweight verification passed for `/sports/mlb/floor`, `/sports/wnba/floor`, and `/sports/nfl/props`: one `.bk-app`, new topbar/rail/sidebar present, no horizontal overflow.
32. [x] Convert Candidate Review onto the new BK shell.
    - Converted `candidate_review.html` to `bk_base.html`.
    - Flask route checks passed for `/candidate-review?review_limit=50&profile_limit=50` and an MLB-filtered slice.
    - Browser lightweight verification passed: one `.bk-app`, new topbar/rail/sidebar present, no horizontal overflow.
    - Payload trim completed: capped the hot-hand card heat strip to the intended `1-10` cells and capped the detailed streak table to top `50`, reducing capped-page HTML from about `1.06 MB` to about `516 KB`.
33. [x] Convert the universal NBA Props board onto the new BK shell.
    - Converted `props.html` to `bk_base.html` with the shared topbar, logo rail, sidebar, and formula status badge.
    - Flask route checks passed for `/props?date=all&page_size=25`, `/props/floor?date=today&page_size=25&postseason=1`, and `/props/locks?date=all&page_size=25`.
    - Browser lightweight verification passed for `/props?date=all&page_size=25`: one `.bk-app`, new topbar/rail/sidebar present, `25` board rows rendered, and no horizontal overflow.
34. [x] Convert the live Parlay Builder onto the new BK shell.
    - Converted `parlay_formula.html`, the template used by `/parlay`, to `bk_base.html`.
    - Flask route checks passed for `/parlay?sample=current` and `/parlay?date=all&sample=current`.
    - Browser lightweight verification passed for `/parlay?sample=current`: one `.bk-app`, new topbar/rail/sidebar present, `59` available-leg rows rendered, and no horizontal overflow.
35. [x] Convert active player intelligence pages onto the new BK shell.
    - Converted `player.html` to `bk_base.html`, with active sport inferred from the player's historical prop profile when available.
    - Flask route checks passed for `/player/Josh%20Naylor` and `/player/Jalen%20Brunson`.
    - Browser lightweight verification passed for `/player/Jalen%20Brunson`: one `.bk-app`, new topbar/rail/sidebar present, `12` data tables rendered, and no horizontal overflow.
36. [x] Convert Market Edge onto the new BK shell.
    - Converted `smart_picks_v2.html`, the template used by `/market-edge`, to `bk_base.html`.
    - Flask route checks passed for `/market-edge?date=all&page_size=25` and `/market-edge?date=today&sample=current`.
    - Browser lightweight verification passed for `/market-edge?date=all&page_size=25`: one `.bk-app`, new topbar/rail/sidebar present, `14` market-edge rows rendered, and no horizontal overflow.
37. [x] Convert NBA matchup pages onto the new BK shell.
    - Converted `matchup.html` to `bk_base.html` for game-environment and matchup-detail views.
    - Flask route checks passed for `/matchup/OKC-SAS` and `/matchup/NYK-CLE`.
    - Browser lightweight verification passed for `/matchup/OKC-SAS`: one `.bk-app`, new topbar/rail/sidebar present, `6` matchup tables rendered, and no horizontal overflow.
38. [x] Convert the Elite Cockpit onto the new BK shell.
    - Converted `elite_dashboard.html` to `bk_base.html`.
    - Flask route check passed for `/elite`.
    - Browser lightweight verification passed for `/elite`: one `.bk-app`, new topbar/rail/sidebar present, `7` Elite tables rendered, and no horizontal overflow.
39. [x] Convert Elite Matchup Builder and MLB Lab onto the new BK shell.
    - Converted `elite_matchup_builder.html` and `elite_mlb_lab.html` to `bk_base.html`.
    - Flask route checks passed for `/elite/matchup-builder`, `/elite/matchup-builder?sport=MLB`, and `/elite/mlb-lab`.
    - Browser visual QA is queued for a later pass because the local browser connection timed out while loading the heavier MLB Lab page.
40. [x] Convert the public frontpage onto the new BK shell.
    - Converted `frontpage.html` to `bk_base.html` so first-time visitors see the same product shell and brand system as logged-in users.
    - Flask route check passed for `/`.
    - Browser lightweight verification passed for `/`: one `.bk-app`, new topbar/rail/sidebar present, and no horizontal overflow.
41. [x] Convert Trend Board onto the new BK shell.
    - Converted `trend_board.html` to `bk_base.html`.
    - Flask route checks passed for `/trend-board?sample=current` and `/trend-board?sample=full&stat=PTS`.
    - Browser lightweight verification passed for `/trend-board?sample=full&stat=PTS`: one `.bk-app`, new topbar/rail/sidebar present, `24` trend rows rendered, and no horizontal overflow.
42. [x] Convert football and WNBA matchup detail pages onto the new BK shell.
    - Converted `nfl_matchup.html` and `wnba_matchup.html` to `bk_base.html`.
    - Flask route checks passed for `/sports/nfl/matchup/CAR%20@%20TB` and `/sports/wnba/matchup/phoenix-mercury-at-new-york-liberty`.
    - Both routes rendered the shared BK shell and theme successfully.
43. [x] Convert NBA team and series detail pages onto the new BK shell.
    - Converted `team.html` and `series.html` to `bk_base.html`.
    - Flask route checks passed for `/team/NYK` and `/series/knicks-hawks`.
    - Both routes rendered the shared BK shell and theme successfully.
44. [x] Convert legacy stat trend heatmap template onto the new BK shell.
    - Converted `heatmap.html` to `bk_base.html`.
    - The active `/trends/<stat>` routes now redirect into `/trend-board`, which is already on the shared shell.
    - Follow-redirect route checks passed for `/trends/PTS` and `/trends/REB?direction=under`.
45. [x] Remove the last old `base.html` template dependency.
    - Converted the legacy unused `parlay.html` template to `bk_base.html`.
    - Repository scan confirms all templates now extend `bk_base.html`; no remaining template extends the old `base.html`.

## Current Next Action

Visual QA is the last step. Continue in this order:

1. Keep calibration reproducible through `run_bk_edge_engine_pipeline.py`.
2. Keep backfill/live discipline clean through `normalize_result_metadata.py`, drift alerts, and scorecards.
3. Build NCAAF/CBB as game-line and totals products first; props remain support surfaces only.
4. Only after the data/check layer is green, run the dedicated visual QA pass page by page.
