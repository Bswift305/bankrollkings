# NFL Usage Distribution (committee backfields & receiver-room splits)

Adds a **usage-distribution** signal to the NFL prop model so that, as players
develop through the season, the model reflects how a team actually spreads its
carries and targets — and prices props accordingly.

> Two good RBs → the Detroit "dual-back" look: fade the lead back's rushing
> over, buy the developing RB2. The same idea applies to the receiver room.

## How it fits the model

`BK_NFL_PropScore` is a sum of independent, clamped components
(`UsageStability + MatchupAdvantage + GameScriptFit + LineValue +
VolatilityPenalty + NGSModifier`). This adds one more:

```
+ BackfieldShare        # committee / target-share aware, clamped to ±7
```

It follows the same pattern as the existing components: a `calculate_*`-style
per-row signal plus a note column (`BackfieldShareNote`) for the UI.

## Pieces

| File | Role |
| --- | --- |
| `services/nfl_usage_distribution.py` | Pure, stdlib-only core: scheme classification, aggregation, and the per-prop signal. Unit-tested. |
| `build_nfl_usage_distribution.py` | Pipeline step: reads per-game player stats, writes the usage profile CSV. |
| `calculate_nfl_prop_score.py` | Loads the profile and adds `BackfieldShare` + `BackfieldShareNote`. |
| `run_bk_edge_engine_pipeline.py` | Runs the builder right before `NFL PropScore`. |
| `tests/test_nfl_usage_distribution.py` | Runnable smoke test (no pandas). |

## Data flow

```
data/historical/NFL_PlayerStats_2025.csv   (from build_nfl_player_stats_from_pbp.py)
        │  season totals + last 4 weeks (development trend)
        ▼
build_nfl_usage_distribution.py
        │
        ▼
data/tracking/NFL_Usage_Distribution.csv   (Player, Team, Position, Role, Scheme,
        │                                    CarryShare, TargetShare, Trend)
        ▼
calculate_nfl_prop_score.py  →  BackfieldShare, BackfieldShareNote
```

## Schemes detected

- **Backfield:** `bell_cow` · `dual_back` · `committee`
- **Receiver room:** `wr_alpha` · `wr_two_headed` · `wr_spread`

Thresholds live at the top of `services/nfl_usage_distribution.py` and are easy
to tune. The signal amplifies for a second option whose recent usage share is
trending up (in-season development).

## Signal summary

| Context | Prop | Effect |
| --- | --- | --- |
| Committee / dual-back | lead back rushing OVER | fade (−) |
| Committee / dual-back | RB2 rushing OVER | support (+), amplified if trending up |
| Bell-cow | lead back rushing OVER | support (+); backups faded |
| Two-headed WR room | WR1 receiving OVER | fade (−); WR2 supported |
| Alpha WR room | WR1 receiving OVER | support (+); other WRs faded |
| Spread WR room | top WR receiving OVER | mild fade (−) |

(Unders are mirrored.)

## Safety / graceful degradation

- No player-stats input → builder prints a notice and exits 0.
- No profile CSV → `load_usage_profiles()` returns `{}` and `BackfieldShare` is
  `0.0` for every row. The rest of the model is unchanged.

## Run

```bash
python3 tests/test_nfl_usage_distribution.py     # core logic (no deps)
python3 build_nfl_usage_distribution.py          # build the profile (needs pandas + data)
python3 calculate_nfl_prop_score.py              # score with the new component
```

## Validation note

`BackfieldShare` is a new additive term, so it shifts `BK_NFL_PropScore`. Before
promoting, run `validate_nfl_prop_score_oos.py` to confirm the tiered hit-rate
buckets hold up out-of-sample.
