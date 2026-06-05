#!/usr/bin/env bash
# One-command production deploy for Bankroll Kings.
# Run on the server:  ./deploy.sh
# Pulls the latest committed code and warm-reloads the web tier (re-runs the
# boot prewarm and rolls gunicorn workers with zero downtime).
set -euo pipefail

cd /opt/bankrollkings

echo "[deploy] $(date -u '+%Y-%m-%d %H:%M:%S UTC') pulling latest..."
git pull origin master

echo "[deploy] restarting web service..."
# Must be restart, not reload: gunicorn runs with preload_app=True, so a HUP
# reload only recycles workers from the already-loaded master and does NOT pick
# up new app.py/template code. A full restart re-imports everything.
sudo systemctl restart bankrollkings

echo "[deploy] done — live at https://bankrollkings.com"
