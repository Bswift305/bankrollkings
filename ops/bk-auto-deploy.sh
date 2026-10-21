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

# Do NOT auto-discard working-tree changes. Runtime-generated data now lives OUTSIDE the checkout
# (BK_RUNTIME_DIR; see docs/cfb_runtime_data_corrective.md), so a clean tree is the normal case and the
# old blanket `git checkout -- .` is gone -- it silently deleted EVERY uncommitted tracked change, not
# just regenerable data. Instead: if any TRACKED file is modified (staged or unstaged; untracked files
# excluded), HOLD the deploy -- print only the offending paths, leave the running service on the current
# commit, and never delete or reset anything. An operator then inspects/commits/reverts deliberately.
DIRTY=$(git status --porcelain --untracked-files=no)
if [ -n "$DIRTY" ]; then
    echo "deploy held: unexpected modified tracked files (not auto-discarded):"
    printf '%s\n' "$DIRTY" | sed 's/^.. /  /'
    exit 1
fi

# --ff-only so a diverged tree still fails loudly instead of silently merging.
# Leave the service running on the old code if the pull fails.
if ! git pull --ff-only --quiet origin "$BRANCH"; then
    echo "pull failed (diverged tree) - service left on ${LOCAL:0:7}"
    exit 1
fi

# RESTART, not reload: gunicorn runs with preload_app, so a HUP will not
# re-import changed app.py/template code.
if ! sudo systemctl restart "$SERVICE"; then
    echo "restart failed after pulling ${REMOTE:0:7}"
    exit 1
fi

# Confirm it actually came back up rather than assuming the restart worked.
#
# curl already prints 000 itself when it cannot connect, so `|| echo 000` would
# APPEND a second 000 -- yielding "000000", which is != 000 and would report a
# false green on a service that never came back. Assign on failure instead.
#
# The window is generous because gunicorn runs with preload_app plus a prewarm:
# it routinely needs longer than a few seconds before it answers, and a probe
# that gives up early would flag a healthy deploy as failed.
for _ in $(seq 1 20); do
    sleep 3
    STATE=$(systemctl is-active "$SERVICE")
    [ "$STATE" = active ] || continue
    CODE=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$PROBE_URL" 2>/dev/null) || CODE=000
    if [ -n "$CODE" ] && [ "$CODE" != 000 ]; then
        echo "deployed $(git rev-parse --short HEAD) | service: $STATE | probe: HTTP $CODE"
        # POST-RESTART cache warming (lifecycle event #2: a deploy may bump APP_CACHE_VERSION, which
        # invalidates every disk artifact). We warm AFTER the restart -- not before -- because the
        # artifacts must be rebuilt by the NEW code at the NEW schema; a pre-restart warm would publish
        # old-schema artifacts the new workers would then reject. Running it here, synchronously, before
        # the deploy reports success, keeps the first real visitor from becoming the warmer. It runs as
        # this (ubuntu) service user, makes no upstream network calls, writes no user data, and is
        # time-bounded. A warm failure is logged LOUDLY (never a silent cold deploy) but does not fail
        # the deploy: the app still serves (cold) and the next source refresh re-warms.
        if timeout 300 venv/bin/python refresh_runtime_snapshots.py --prewarm-only; then
            echo "prewarm: ok (disk artifacts warmed for $(git rev-parse --short HEAD))"
        else
            echo "WARNING: post-deploy prewarm failed/timed out for $(git rev-parse --short HEAD) - routes may be COLD until the next refresh"
        fi
        exit 0
    fi
done

echo "WARNING: deployed $(git rev-parse --short HEAD) but service did not answer (state: $(systemctl is-active "$SERVICE"))"
exit 1
