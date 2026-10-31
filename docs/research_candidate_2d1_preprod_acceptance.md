# Research Candidate 2D1 — Linux Pre-Production Acceptance Gate (flag OFF) — Rev 1.1

**Status: MANDATORY GATE before the dark 2D1 route may ever be enabled.** 2D1 local integration is approved
and closed (`fd63b10`), but the POSIX permission guarantees — `[P]` live-sidecar 0600, `[Q]` sidecar
chmod/verify fail-closed, `[R]` post-commit relock → 503 — are **skipped on the Windows dev box** (chmod
cannot set NTFS ACLs). They must be exercised on a **Linux, deployment-like filesystem** (ext4/xfs, not a
network-mounted share) **before enabling**. Production enablement remains unauthorized.

Rev 1.1 makes the runbook a real gate: it binds the receipt to code identity (branch + full HEAD + worktree
status, and `fd63b10` must be an ancestor), accumulates failures and exits nonzero, asserts every required
`[P]/[Q]/[R]` line individually (and fails on a `skipped`), and uses a unique `mktemp -d` output dir.

**Invariants this gate does NOT change:** the feature flag `BK_RESEARCH_CANDIDATE_ENABLED` stays **OFF by
default** (unset on the systemd unit / `.env`); no UI, candidate-freeze, outcome, evaluation, thesis
generation, backup unit, deletion, or promotion. The QC runs in an isolated process against **temp
directories only** — it never touches prod data or the live DB, and running it does NOT enable the feature
(it sets the flag in its own test process, not on the deployed service).

## What to run

On a **Linux** checkout of the feature branch `claude/jolly-ishizaka-c6519a` (a staging host or container
with the project venv), with the flag unset. The script self-asserts and exits nonzero on any failure —
paste the full output (ending in `PREPROD ACCEPTANCE: PASS`/`FAIL`) as the receipt:

```bash
set -u
cd /path/to/bankrollkings-branch-checkout || { echo "FATAL: cd failed"; exit 2; }
unset BK_RESEARCH_CANDIDATE_ENABLED
export SECRET_KEY="preprod-acceptance-dummy"
PY=$( [ -x venv/bin/python ] && echo venv/bin/python || { [ -x .venv/bin/python ] && echo .venv/bin/python || echo python3; } )

# (1) bind the receipt to code identity
BRANCH=$(git rev-parse --abbrev-ref HEAD)
HEAD_SHA=$(git rev-parse HEAD)
DIRTY=$(git status --porcelain | wc -l | tr -d ' ')
echo "branch=$BRANCH head=$HEAD_SHA worktree_changes=$DIRTY os=$("$PY" -c 'import os;print(os.name)') flag=${BK_RESEARCH_CANDIDATE_ENABLED:-<unset>}"
[ "$DIRTY" = "0" ] || echo "WARNING: worktree has uncommitted changes — receipt may not describe committed code"
git merge-base --is-ancestor fd63b10 HEAD || { echo "FATAL: fd63b10 is not an ancestor of HEAD (different code)"; exit 3; }

# (4) unique temp output dir + cleanup trap
OUT=$(mktemp -d) || { echo "FATAL: mktemp failed"; exit 2; }
trap 'rm -rf "$OUT"' EXIT

FAILED=0
for f in qc_research_candidate_contract qc_research_candidate_store qc_research_candidate_backup \
         qc_research_candidate_idempotency qc_nfl_identity_event_adapter qc_research_candidate_route \
         qc_nfl_season_contract; do
  "$PY" "$f.py" > "$OUT/$f.out" 2>&1; rc=$?
  nfail=$(grep -c '\[FAIL\]' "$OUT/$f.out")
  printf '%-38s exit=%s ok=%s FAIL=%s\n' "$f" "$rc" "$(grep -c '\[ok\]' "$OUT/$f.out")" "$nfail"
  { [ "$rc" -eq 0 ] && [ "$nfail" -eq 0 ]; } || FAILED=1   # (2) accumulate suite failures
done

# (3) assert every required [P]/[Q]/[R] POSIX line individually; fail on absence or a skip
RT="$OUT/qc_research_candidate_route.out"
if grep -q 'POSIX-only.*skipped' "$RT"; then echo "GATE FAIL: [Q] skipped (not run on a POSIX fs)"; FAILED=1; fi
while IFS= read -r line; do
  grep -qF "$line" "$RT" || { echo "GATE FAIL: missing required POSIX line: $line"; FAILED=1; }
done <<'LINES'
approved directory is 0700
DB file is 0600
every present DB/WAL/SHM file is 0600
a sidecar chmod failure raises ConfigError
a sidecar whose mode is not 0600 fails verification
the post-commit relock failure returns 503
exactly one observation was committed
LINES

echo "flag_after_run=${BK_RESEARCH_CANDIDATE_ENABLED:-<unset>}"
if [ "$FAILED" -eq 0 ]; then echo "PREPROD ACCEPTANCE: PASS"; exit 0; else echo "PREPROD ACCEPTANCE: FAIL"; exit 1; fi
```

## Receipt must show (to pass the gate)

1. Header: `branch=claude/jolly-ishizaka-c6519a`, a `head=<sha>` for which `fd63b10` is an ancestor
   (the script hard-fails otherwise), `worktree_changes=0`, `os=posix`, `flag=<unset>`.
2. Every suite `exit=0 FAIL=0` (notably `qc_research_candidate_route` = 51 checks).
3. No `GATE FAIL:` lines (every required `[P]/[Q]/[R]` POSIX line present; no `[Q] skipped`).
4. Final line `PREPROD ACCEPTANCE: PASS` (exit 0).

The run is read-only w.r.t. production (temp dirs only) and leaves the deployed flag OFF.
