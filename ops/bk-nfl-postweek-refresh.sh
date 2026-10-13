#!/usr/bin/env bash
# Bankroll Kings - post-week NFL player-stat freshness retry.
#
# WHY: nflverse rewrites the current-season weekly player-stat parquet as each week finalizes
# (Thu->Mon slate, final Tue). The once-daily run_daily fetch can miss the publish window, so the
# Hot Hand Heat Map could sit "pending / through last week" until the next day. This fires
# repeatedly on Tue/Wed (via bk-nfl-postweek.timer) and advances the parquet as soon as the
# completed week is published, so the board stops being a day behind.
#
# Each tick is ONE short attempt -- no long in-process sleep (the timer provides the cadence).
# It self-gates: if the completed week is already on disk it exits immediately, so the Tue/Wed
# ticks after the week lands cost nothing. The in-app calendar gate keeps the board honestly
# "pending" until this advances the data, so a missed tick never shows stale rows as current.
#
# Installed OUTSIDE the repo so a mid-run `git pull` (bk-deploy) cannot rewrite the executing
# script -- same rationale as bk-auto-deploy.sh. Source of record: ops/bk-nfl-postweek-refresh.sh
#   sudo install -m 755 ops/bk-nfl-postweek-refresh.sh /usr/local/bin/bk-nfl-postweek-refresh.sh
set -uo pipefail

APP=/opt/bankrollkings
PY="$APP/venv/bin/python"
cd "$APP" || exit 0

# Already have the calendar's completed week? Cheap on-disk check, no download.
if "$PY" fetch_nfl_player_week.py --check-only; then
  echo "[postweek] completed week already loaded - nothing to do"
  exit 0
fi

echo "[postweek] completed week missing - pulling nflverse player stats"
# One pull this tick (no retries/sleep here; the timer re-fires). --gate exits 2 if the source
# has still not published the completed week, which is fine: we retry on the next tick.
"$PY" fetch_nfl_player_week.py --gate || true

if "$PY" fetch_nfl_player_week.py --check-only; then
  echo "[postweek] completed week now present"
else
  echo "[postweek] still pending - will retry on the next tick"
fi
exit 0
