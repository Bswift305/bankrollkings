#!/bin/bash
# SessionStart hook — make a Claude Code on the web container able to run the
# Bankroll Kings stack on its own (deps + data dirs + key check).
#
# Background: cloud sessions clone the repo fresh and start with no Python
# packages. data/ ships the committed baseline (NFL_Props_History.csv, the CFB
# scenario JSONs) but NOT the live feeds, which are gitignored and fetched from
# The Odds API / CollegeFootballData. Without this hook every cloud session
# starts by hand-installing pandas before it can read anything.
set -euo pipefail

# Local machines already have a venv and real data; only the web needs this.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-$(dirname "$0")/../..}"

# A venv, not the system interpreter: this image's Flask deps (blinker) are
# Debian-managed and pip refuses to upgrade them ("RECORD file not found").
VENV="$PWD/.venv"
if [ ! -x "$VENV/bin/python" ]; then
  echo "[bk] creating virtualenv..."
  python3 -m venv "$VENV"
fi

echo "[bk] installing Python dependencies..."
# pip install (not a locked sync) so the container cache is reused across sessions.
"$VENV/bin/pip" install --quiet --disable-pip-version-check -r requirements.txt

# Put the venv first on PATH so `python` in this session is the one with deps.
echo "export PATH=\"$VENV/bin:\$PATH\"" >> "$CLAUDE_ENV_FILE"
echo "export VIRTUAL_ENV=\"$VENV\"" >> "$CLAUDE_ENV_FILE"

# The live feeds are gitignored, so these arrive empty. Scripts assume they exist.
echo "[bk] ensuring runtime data directories..."
mkdir -p data/{odds,props,live_scores,schedules,injuries,rosters,gamelogs,cache,debug,user_notes}

# Flask needs a SECRET_KEY to import; the real one only matters in prod.
if [ -z "${SECRET_KEY:-}" ]; then
  echo "export SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')" >> "$CLAUDE_ENV_FILE"
fi
echo 'export PYTHONPATH="."' >> "$CLAUDE_ENV_FILE"

# Report key status rather than failing: the repo is still readable/editable
# without keys, but nothing can be REFRESHED, and a silently stale feed is the
# exact failure mode run_daily.py's qc_odds_feed guard exists to prevent.
missing=()
[ -z "${ODDS_API_KEY:-}${THE_ODDS_API_KEY:-}" ] && missing+=("ODDS_API_KEY")
[ -z "${CFBD_API_KEY:-}${COLLEGEFOOTBALLDATA_API_KEY:-}" ] && missing+=("CFBD_API_KEY")

if [ ${#missing[@]} -gt 0 ]; then
  echo "[bk] WARNING: no data-feed credentials: ${missing[*]}"
  echo "[bk] Committed baseline data is available; live refresh is NOT."
  echo "[bk] Add these in the Claude Code environment config to enable run_daily.py."
else
  echo "[bk] data-feed credentials present — live refresh available."
fi

echo "[bk] ready."
