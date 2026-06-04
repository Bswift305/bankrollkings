# Bankroll Kings Developer Handoff

Version `1.0`  
Last updated `2026-05-30`

## Platform Overview

Bankroll Kings is a Flask-based sports betting analytics and intelligence platform. It is not a sportsbook and does not custody wagers or user funds.

Current coverage:

- NBA
- WNBA
- MLB
- NFL
- CFB / NCAAF
- Men CBB
- Women CBB

Core product direction:

> Game context first -> market context -> prop context

A prop should not live by itself. It should carry game environment, line context, player reliability, injury context, and calibration status.

## Current Completion Snapshot

| Layer | Status | Completion | Launch blocker |
| --- | --- | ---: | --- |
| Edge engine + data pipeline | Complete | 88% | No |
| UI / frontend shell | Mostly done | 70% | No |
| Infrastructure (AWS) | Not started | 5% | Yes |
| Security (secrets) | Needs fix / verify | 80% | Yes |
| Payments (Stripe) | Test mode only | 40% | Yes |
| Legal (ToS, Privacy) | Draft needed | 20% | Yes |
| CFB / CBB calibration | Seasonal | 0% | No |

## Already Built

### Engine

- NFL EdgeScore v1 and PropScore v1
- NFL simulation set with `26,066` rows and `70.4%` actual hit rate for `Sim 70+`
- Rolling / prior-only simulation support for NBA, WNBA, and MLB
- MLB high-calibration authority at `71.7%`
- WNBA high-calibration authority at `64.7%`
- NBA correctly capped as watch-only in weaker buckets
- Cross-sport calibration summary
- Missed-winner promotion candidate pipeline
- Streak heat index
- BankrollIQ quarter-Kelly sizing
- CorrelationIQ same-game / same-team / same-stat / cross-sport scoring
- Team strength priors
- CLV vs hit-rate drift tracking
- MLB umpire and weather context automation
- `Formula_Status.json` and formula badge support

### Frontend shell

- `templates/bk_base.html` universal shell
- `static/css/bk-theme.css` design system
- All major templates converted to the new shell
- Major routes browser-verified
- Derivatives Lab, Systems Lab, and Calibration Lab surfaces active

### Automation

- `run_bk_edge_engine_pipeline.py`
- `run_daily.py`
- `run_all_scorecards.py`
- `Run_Status.json` health tracking
- Script freshness shown in the dashboard status layer

## Pre-Launch Blockers

These are the highest-priority items before any public launch.

### 1. Stabilize the repository

- The working tree is active and dirty.
- Do not casually revert files.
- Create a known-good checkpoint before broader launch cleanup.

Recommended commands:

```powershell
git status
git add .
git commit -m "BK checkpoint - pre-launch known good state 2026-05-30"
git checkout -b launch/v1.0
```

### 2. Secret management

- `SECRET_KEY` must come from environment configuration.
- No hardcoded secret should remain in code.
- Startup should fail if the environment key is missing.

Environment template:

```env
SECRET_KEY=your-long-random-secret
```

Generate locally with:

```powershell
py -c "import secrets; print(secrets.token_hex(32))"
```

### 3. AWS deployment

Target stack from the handoff:

| Component | Purpose | Estimated monthly cost |
| --- | --- | ---: |
| EC2 `t3.small` | Flask app | ~$15 |
| ElastiCache Redis | Cache / reduce CSV pressure | ~$13 |
| EBS `30GB gp3` | Data + code storage | ~$3 |
| Elastic IP | Fixed public address | ~$4 |
| Cloudflare | CDN / TLS / DDoS | $0 |
| Let's Encrypt | SSL | $0 |

Target total: roughly `$35–45/mo`

### 4. Stripe live mode + legal

- Switch Stripe from test to live mode
- Create live products and prices
- Update checkout / webhook handling
- Test with a real card before launch
- Finalize:
  - Terms of Service
  - Privacy Policy
  - Responsible Gambling disclaimer
  - Refund Policy

## Post-Launch Priority Queue

1. Compact prop rows
2. Real free-tier test drive
3. Sport dashboards as command centers
4. Fill out Derivatives Lab
5. CB coverage intelligence
6. Real league logos across UI
7. Mobile layout pass
8. Extract `app.py` into services gradually
9. Official tendency event-level feeds
10. CSV -> Postgres migration
11. CFB formula with CFBD integration
12. CBB calibration layer

## Tech Stack Quick Reference

| Component | Value / path |
| --- | --- |
| Backend | Flask |
| Main app file | `app.py` |
| Templates | `templates/` |
| Universal shell | `templates/bk_base.html` |
| Theme | `static/css/bk-theme.css` |
| Data root | `data/` |
| Start server | `.\start_server.ps1 -Port 5000` |
| Stop server | `.\stop_server.ps1 -Port 5000` |
| Syntax check | `py -m py_compile app.py` |
| Edge engine | `py run_bk_edge_engine_pipeline.py` |
| Daily refresh | `py run_daily.py --sports nba,wnba,mlb` |
| Scorecards | `py run_all_scorecards.py` |

## Key Routes

Core:

- `/`
- `/dashboard`
- `/pricing`
- `/billing`
- `/account`
- `/glossary`

Universal tool hubs:

- `/tools/props`
- `/tools/market-edge`
- `/tools/matchup-lens`
- `/tools/injuries`
- `/tools/trends`
- `/tools/parlay`

Legacy compatibility redirects:

- `/props` -> `/tools/props` or `/sports/nba/props`
- `/market-edge` -> `/tools/market-edge` or `/sports/nba/market-edge`
- `/matchup-lens` -> `/tools/matchup-lens`

Sport homes:

- `/sports/nba`
- `/sports/wnba`
- `/sports/mlb`
- `/sports/nfl`
- `/sports/ncaaf`

Deeper analysis:

- `/parlay`
- `/candidate-review`
- `/missed-opportunities`
- `/heat-map`
- `/derivatives`
- `/calibration-lab`
- `/systems-lab`
- `/nfl-formula-lab`
- `/mlb-formula-lab`

Legal drafts:

- `/terms`
- `/privacy`
- `/refund-policy`
- `/responsible-gambling`

## Data Layout

| Folder | Purpose |
| --- | --- |
| `data/props/` | Live prop feeds by sport |
| `data/gamelogs/` | Player game logs |
| `data/schedules/` | Schedules |
| `data/context/` | Context, weather, officiating, umpire data |
| `data/tracking/` | Scorecards, calibration, run status |
| `data/historical/` | Historical props / lines / backfill |
| `data/cache/` | Cached runtime artifacts |

Important tracking files:

- `data/tracking/Formula_Status.json`
- `data/tracking/Run_Status.json`
- `data/tracking/CrossSport_Player_Reliability_Summary.csv`
- `data/tracking/Team_Strength_Priors.csv`
- `data/tracking/Floor_Play_Index.csv`
- `data/tracking/Combined_Prop_Coverage.csv`
- `data/tracking/Live_Drift_Alerts.csv`
- `data/context/MLB_UmpireAssignments.csv`
- `data/context/OfficiatingContext.csv`

## Developer Cautions

- Preserve behavior before refactoring
- Add route checks before changing pages
- Do not rewrite the whole app first
- Cached snapshot workflows can fail silently if schemas change
- Free tier and public home should remain separate product concepts
- CFB / CBB still need real historical calibration depth
- Production exposure should wait for proper reverse proxy, auth, and infra
- Keep API keys in environment configuration only
- The best long-term cleanup is gradually extracting `app.py` into services after launch

## Quick Health Checks

```powershell
py -m py_compile app.py
py audit_combined_prop_coverage.py
py build_officiating_context.py
py build_official_tendency_profiles.py
```

Simple route smoke:

```powershell
py - << 'EOF'
from app import app
client = app.test_client()
for path in ['/', '/dashboard', '/tools/props', '/parlay',
             '/candidate-review', '/heat-map', '/derivatives']:
    r = client.get(path)
    print(path, r.status_code, len(r.get_data()))
EOF
```

Full pipeline:

```powershell
py run_bk_edge_engine_pipeline.py
py run_all_scorecards.py
```

## Final Product Vision

Bankroll Kings should not feel like a picks site. It should feel like a betting intelligence terminal that helps users:

- read what the market is actually saying
- understand the game before the prop
- spot stale numbers and line drift
- build better tickets with BankrollIQ and CorrelationIQ
- track saved tickets and outcomes
- learn from missed winners and calibration loops
- respect bankroll sizing and correlation risk
- pass when the context is not clean

The audience is not casual pick-buyers. It is bettors who want to think and bet more like a sharp, and a platform that rewards learning how to do it right.
