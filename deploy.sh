#!/usr/bin/env bash
# One-command production deploy for Bankroll Kings.
# Run on the server:  ./deploy.sh
# Pulls the latest committed code and warm-reloads the web tier (re-runs the
# boot prewarm and rolls gunicorn workers with zero downtime).
set -euo pipefail

cd /opt/bankrollkings

echo "[deploy] $(date -u '+%Y-%m-%d %H:%M:%S UTC') pulling latest..."
git pull origin master

echo "[deploy] reloading web service..."
sudo systemctl reload bankrollkings

echo "[deploy] done — live at https://bankrollkings.com"
