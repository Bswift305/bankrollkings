# Launch Infrastructure Runbook

## Current State

- Git is initialized locally.
- `.env.local` is ignored and contains local-only secrets.
- `SECRET_KEY` is loaded from environment instead of being hardcoded.
- Stripe checkout routes exist, but checkout QC is still in demo mode until hosted Stripe URLs are configured.
- MLB refresh pipeline writes a manifest and can be run end to end with `python refresh_mlb_daily.py`.

## Required Production Environment Variables

- `SECRET_KEY`
- `ODDS_API_KEY`
- `CFBD_API_KEY` if college-football data refresh is enabled
- `STRIPE_PRO_MONTHLY_URL`
- `STRIPE_PRO_ANNUAL_URL`
- `STRIPE_SHARP_MONTHLY_URL`
- `STRIPE_SHARP_ANNUAL_URL`
- `STRIPE_ELITE_MONTHLY_URL`
- `STRIPE_ELITE_ANNUAL_URL`
- `STRIPE_BILLING_PORTAL_URL`

## Deployment Basics

- Install dependencies from `requirements.txt`.
- Start the app with `gunicorn app:app`.
- Keep generated data directories persistent or refresh them on deploy:
  - `data/props`
  - `data/odds`
  - `data/schedules`
  - `data/gamelogs`
  - `data/injuries`
  - `data/tracking`
  - `data/cache`

## Prelaunch Checks

Run these before opening paid access:

```powershell
python qc_checkout_readiness.py
python run_prelaunch_scorecard.py
python run_mlb_99_scorecard.py
python refresh_mlb_daily.py
```

## Launch Blockers

- Configure and test all six Stripe hosted checkout URLs.
- Configure Stripe billing portal URL.
- Add production scheduled refresh jobs.
- Add weather and umpire feeds for MLB game context.
- Add Batter Strikeouts fallback source if The Odds API remains blank.
