#!/bin/bash
# Poll origin/master and deploy when it moves.
#
# Deploy friction was the problem this solves: SSH to the box is IP-allowlisted
# in the security group, and a churning egress IP (hotel wifi / cellular) blocks
# port 22 without warning -- repeatedly stranding pushed commits undeployed. With
# this timer the server pulls instead of us pushing, so "deploy" is just
# `git push` from anywhere.
#
# THE LIVE COPY RUNS FROM /usr/local/bin/bk-auto-deploy.sh, deliberately OUTSIDE
# the repo: bash reads a script incrementally, so a `git pull` that rewrote this
# file mid-run could execute a spliced mix of old and new lines. This copy is
# the version-controlled reference; after editing it, reinstall with:
#   sudo install -m 755 ops/bk-auto-deploy.sh /usr/local/bin/bk-auto-deploy.sh
#
# Runs as the `ubuntu` user (owns the repo and the GitHub deploy key) and uses
# passwordless sudo only for the service restart.
set -uo pipefail

REPO=/opt/bankrollkings
BRANCH=master
SERVICE=bankrollkings
PROBE_URL=http://127.0.0.1:8000/

# Never let two deploys overlap (a slow restart must not race the next tick).
exec 9>/var/lock/bk-auto-deploy.lock || exit 0
flock -n 9 || exit 0

cd "$REPO" || { echo "repo $REPO missing"; exit 1; }

if ! git fetch --quiet origin "$BRANCH" 2>&1; then
    echo "fetch failed (network or auth) - will retry next tick"
    exit 1
fi

LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse "origin/$BRANCH")
[ "$LOCAL" = "$REMOTE" ] && exit 0   # nothing new; stay quiet

echo "deploy: ${LOCAL:0:7} -> ${REMOTE:0:7}"

# --ff-only so a diverged or dirty tree fails loudly instead of silently
# merging. Leave the service running on the old code if the pull fails.
if ! git pull --ff-only --quiet origin "$BRANCH"; then
    echo "pull failed (diverged or dirty tree) - service left on ${LOCAL:0:7}"
    exit 1
fi

# RESTART, not reload: gunicorn runs with preload_app, so a HUP will not
# re-import changed app.py/template code.
if ! sudo systemctl restart "$SERVICE"; then
    echo "restart failed after pulling ${REMOTE:0:7}"
    exit 1
fi

# Confirm it actually came back up rather than assuming the restart worked.
for _ in $(seq 1 10); do
    sleep 2
    STATE=$(systemctl is-active "$SERVICE")
    [ "$STATE" = active ] || continue
    CODE=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$PROBE_URL" || echo 000)
    if [ "$CODE" != 000 ]; then
        echo "deployed $(git rev-parse --short HEAD) | service: $STATE | probe: HTTP $CODE"
        exit 0
    fi
done

echo "WARNING: deployed $(git rev-parse --short HEAD) but service did not answer (state: $(systemctl is-active "$SERVICE"))"
exit 1
