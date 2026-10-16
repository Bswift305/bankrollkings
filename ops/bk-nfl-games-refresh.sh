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

# Refresh then verify in ONE entrypoint that PROPAGATES failure: it fetches (self-gating off-season),
# ALWAYS runs the ATS synchronization verifier even after a fetch failure, and returns nonzero when the
# fetch/publication or the verifier fails -- so systemd/journal monitoring reports a real failure. A
# "behind"/"unchanged"/off-season tick is success.
"$PY" fetch_nfl_games.py --run --gate
rc=$?
echo "[nfl-games] refresh+verify exit ${rc}"
exit "$rc"
