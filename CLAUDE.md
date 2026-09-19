# Bankroll Kings — working notes for Claude

## Branches

`master` is the real project (Flask/Python, `app.py`, ~41k lines, 265 routes).
`main` is an unrelated Next.js scaffold with **no shared history**. If a session
cloned `main`, it has the wrong codebase — switch to `master`.

## Cloud sessions (Claude Code on the web)

`.claude/hooks/session-start.sh` runs on startup and handles setup: creates
`.venv`, installs `requirements.txt`, creates the gitignored runtime data dirs,
and generates a throwaway `SECRET_KEY`. It is a no-op outside the web.

The hook puts `.venv/bin` first on `PATH`, so plain `python` is the right one.

## Data: what ships vs. what doesn't

Committed (~8 MB, in `data/`):

- `data/historical/NFL_Props_History.csv` — the purchased prop lab. Not
  regenerable; do not delete.
- `data/historical/NFL_Games_*.csv`
- `data/scenarios/*.json` — CFB/NFL/MLB scenario engines
- `data/context/MLB_BallparkFactors.csv`

**Gitignored** (fetched, never in git): `data/odds/`, `data/props/`,
`data/live_scores/`, `data/schedules/`, `data/injuries/`, `data/rosters/`,
`data/gamelogs/`.

So a fresh clone has the historical baseline but **nothing current**. Check
`data/scenarios/cfb_matchup.json` → `meta.generated` before trusting any read;
the committed snapshot is only as fresh as the last commit that touched it.

## Refreshing data

Needs two credentials, as environment variables:

- `ODDS_API_KEY` — The Odds API (alias `THE_ODDS_API_KEY`)
- `CFBD_API_KEY` — CollegeFootballData (alias `COLLEGEFOOTBALLDATA_API_KEY`)

Env vars win over `.env` / `.env.local` everywhere. Then:

    python run_daily.py          # full refresh; qc_odds_feed.py guards first
    python refresh_nfl_featured_results.py
    python refresh_ncaaf_featured_results.py

`run_daily.py` opens with `qc_odds_feed.py` deliberately: fetches preserve the
last-good file on failure, so a dead key leaves the site serving stale lines
silently. That guard is the only thing that makes the failure loud. Don't skip it.

## Verifying a change

    python smoke_test.py               # in-process, no network/login; flags any 5xx
    SMOKE_SKIP_SWEEP=1 python smoke_test.py   # CSRF checks only (fast)

There is no pytest suite and no linter config.

## The live site

`bankrollkings.com` is reachable, but every tool page (`/smart-picks`,
`/trend-board`, `/tools/track-record`, `/tools/slate-pulse`, ...) is behind
session-cookie login and returns 401. There is no token or API-key bypass, so a
session cannot read gated pages — work from local data instead.
