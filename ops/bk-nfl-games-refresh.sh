#!/usr/bin/env bash
# Bankroll Kings - NFL games-source refresh (nflverse games.csv -> nflverse_games.parquet).
#
# WHY: the Active ATS Wave (build_nfl_ats_wave) reads data/historical/nflverse_games.parquet, which
# nothing on prod was refreshing -- so the board correctly FAILS CLOSED. This pulls the documented
# nflverse source (CC BY 4.0), validates it, atomically replaces the live parquet and writes the
# freshness sidecar (fetch_nfl_games.py). It then runs the ATS synchronization verifier, because a
# successful download does NOT prove the board is synchronized (overdue games + the freshness budget
# still gate it). Does NOT touch SU or O/U.
#
# Self-gating: fetch_nfl_games.py --gate no-ops off-season. flock prevents overlapping runs.
#
# Installed OUTSIDE the repo so a mid-run `git pull` (bk-deploy) cannot rewrite the executing script
# -- same rationale as bk-auto-deploy.sh. Source of record: ops/bk-nfl-games-refresh.sh
#   sudo install -m 755 ops/bk-nfl-games-refresh.sh /usr/local/bin/bk-nfl-games-refresh.sh
set -uo pipefail

APP=/opt/bankrollkings
PY="$APP/venv/bin/python"
cd "$APP" || exit 0

# No overlapping runs (the timer may fire while a slow fetch is still going).
exec 9>/tmp/bk-nfl-games.lock
if ! flock -n 9; then
  echo "[nfl-games] another refresh is in progress; skipping this tick"
  exit 0
fi

# Refresh the source. --gate self-skips off-season. A validation/network failure leaves the last
# valid parquet untouched and exits nonzero; we still run the verifier below to report true state.
"$PY" fetch_nfl_games.py --gate
rc=$?
echo "[nfl-games] fetch exit ${rc}"

# ALWAYS verify synchronization after a refresh attempt -- a good download is not a synchronized board.
echo "[nfl-games] running NFL ATS synchronization verifier"
"$PY" report_nfl_ats_wave_sync.py || true

exit 0
