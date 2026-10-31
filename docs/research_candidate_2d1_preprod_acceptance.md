# Research Candidate 2D1 — Linux Pre-Production Acceptance Gate (flag OFF) — Rev 1.2

**Status: MANDATORY GATE before the dark 2D1 route may ever be enabled.** 2D1 local integration is approved
and closed (`fd63b10`), but the POSIX permission guarantees — `[P]` live-sidecar 0600, `[Q]` sidecar
chmod/verify fail-closed, `[R]` post-commit relock → 503 — are **skipped on the Windows dev box** (chmod
cannot set NTFS ACLs). They must be exercised on a **Linux, deployment-like filesystem** (ext4/xfs, not a
network-mounted share) **before enabling**. Production enablement remains unauthorized.

Rev 1.2 makes the runbook a real gate: authoritative code identity is a **clean full HEAD with `fd63b10`
as an ancestor** (branch name is informational, so detached CI checkouts pass); a **dirty worktree fails**
the gate; each suite's **`[ok]` count must equal its expected total** (so a suite silently losing tests
fails); it accumulates failures and exits nonzero, asserts every required `[P]/[Q]/[R]` line individually
(failing on a `skipped`), and uses a unique `mktemp -d` output dir.

**Invariants this gate does NOT change:** the feature flag `BK_RESEARCH_CANDIDATE_ENABLED` stays **OFF by
default** (unset on the systemd unit / `.env`); no UI, candidate-freeze, outcome, evaluation, thesis
generation, backup unit, deletion, or promotion. The QC runs in an isolated process against **temp
directories only** — it never touches prod data or the live DB, and running it does NOT enable the feature
(it sets the flag in its own test process, not on the deployed service).

## What to run

On a **Linux** checkout of this feature code (a staging host or container with the project venv), with the
flag unset. Authoritative identity is a clean HEAD with `fd63b10` as an ancestor — the exact branch name is
informational, so detached CI checkouts pass. The script self-asserts and exits nonzero on any failure —
paste the full output (ending in `PREPROD ACCEPTANCE: PASS`/`FAIL`) as the receipt:

```bash
set -u
cd /path/to/bankrollkings-feature-checkout || { echo "FATAL: cd failed"; exit 2; }
unset BK_RESEARCH_CANDIDATE_ENABLED
export SECRET_KEY="preprod-acceptance-dummy"
PY=$( [ -x venv/bin/python ] && echo venv/bin/python || { [ -x .venv/bin/python ] && echo .venv/bin/python || echo python3; } )

FAILED=0
# (1) code identity: a CLEAN full HEAD with fd63b10 as an ancestor is authoritative (branch informational)
BRANCH=$(git rev-parse --abbrev-ref HEAD)
HEAD_SHA=$(git rev-parse HEAD)
DIRTY=$(git status --porcelain | wc -l | tr -d ' ')
echo "branch=$BRANCH head=$HEAD_SHA worktree_changes=$DIRTY os=$("$PY" -c 'import os;print(os.name)') flag=${BK_RESEARCH_CANDIDATE_ENABLED:-<unset>}"
[ "$DIRTY" = "0" ] || { echo "GATE FAIL: worktree has $DIRTY uncommitted change(s) — receipt must describe committed code"; FAILED=1; }
git merge-base --is-ancestor fd63b10 HEAD || { echo "FATAL: fd63b10 is not an ancestor of HEAD (different code)"; exit 3; }

# (4) unique temp output dir + cleanup trap
OUT=$(mktemp -d) || { echo "FATAL: mktemp failed"; exit 2; }
trap 'rm -rf "$OUT"' EXIT

# (2) each suite must exit 0, have no [FAIL], AND match its expected [ok] total (a lost test fails the gate)
declare -A EXP=( [qc_research_candidate_contract]=128 [qc_research_candidate_store]=80 \
                 [qc_research_candidate_backup]=50 [qc_research_candidate_idempotency]=56 \
                 [qc_nfl_identity_event_adapter]=48 [qc_research_candidate_route]=51 \
                 [qc_nfl_season_contract]=49 )
for f in qc_research_candidate_contract qc_research_candidate_store qc_research_candidate_backup \
         qc_research_candidate_idempotency qc_nfl_identity_event_adapter qc_research_candidate_route \
         qc_nfl_season_contract; do
  "$PY" "$f.py" > "$OUT/$f.out" 2>&1; rc=$?
  nok=$(grep -c '\[ok\]' "$OUT/$f.out"); nfail=$(grep -c '\[FAIL\]' "$OUT/$f.out"); exp=${EXP[$f]}
  printf '%-38s exit=%s ok=%s/%s FAIL=%s\n' "$f" "$rc" "$nok" "$exp" "$nfail"
  { [ "$rc" -eq 0 ] && [ "$nfail" -eq 0 ] && [ "$nok" -eq "$exp" ]; } \
    || { echo "GATE FAIL: $f (exit=$rc ok=$nok expected=$exp FAIL=$nfail)"; FAILED=1; }
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

1. Header: a `head=<sha>` for which `fd63b10` is an ancestor (the script hard-fails otherwise),
   `worktree_changes=0` (a dirty tree is a GATE FAIL), `os=posix`, `flag=<unset>`. The branch name is
   informational.
2. Every suite `exit=0 FAIL=0` and `ok=<n>/<n>` matching its expected total (contract 128, store 80,
   backup 50, idempotency 56, adapter 48, route 51, season 49).
3. No `GATE FAIL:` lines (every required `[P]/[Q]/[R]` POSIX line present; no `[Q] skipped`).
4. Final line `PREPROD ACCEPTANCE: PASS` (exit 0).

The run is read-only w.r.t. production (temp dirs only) and leaves the deployed flag OFF.

## Appendix: running the receipt on EC2 via SSM (disposable worktree)

CTP's chosen path (option 1): a throwaway `git worktree` of the feature branch on the Linux/ext4 EC2 host,
using the production venv. It does **not** touch `/opt/bankrollkings`'s working tree, the running service,
the deploy timer, the `.env`, or the feature flag — the only repo-side effects are a fetched ref and a
temporary worktree entry, both removed at cleanup. A fresh worktree carries code only (data is gitignored);
the QC uses its own temp dirs, and `app` import writes only the worktree's own `data/cache`. If `import app`
fails for a genuinely missing data file (only the `route`/`season` suites import `app`), capture the exact
error and we'll expose just that path read-only without writing to prod.

Run via SSM (ssm-user has passwordless sudo; everything runs as `ubuntu`, who owns the repo + venv):

```bash
sudo -u ubuntu -H bash <<'ACCEPT'
set -u
BRANCH=claude/jolly-ishizaka-c6519a
SCRATCH=$(mktemp -d /tmp/rc2d1.XXXXXX); WT="$SCRATCH/wt"; PY=/opt/bankrollkings/venv/bin/python
git -C /opt/bankrollkings fetch --quiet origin "$BRANCH" || { echo "FATAL: fetch failed"; exit 2; }
git -C /opt/bankrollkings worktree add --quiet --detach "$WT" "origin/$BRANCH" || { echo "FATAL: worktree add failed"; exit 2; }
cleanup(){ cd /; git -C /opt/bankrollkings worktree remove --force "$WT" 2>/dev/null || true; rm -rf "$SCRATCH"; }
trap cleanup EXIT
cd "$WT" || { echo "FATAL: cd worktree"; exit 2; }
unset BK_RESEARCH_CANDIDATE_ENABLED
export SECRET_KEY="preprod-acceptance-dummy"
FAILED=0
HEAD_SHA=$(git rev-parse HEAD); DIRTY=$(git status --porcelain | wc -l | tr -d ' ')
echo "head=$HEAD_SHA worktree_changes=$DIRTY os=$("$PY" -c 'import os;print(os.name)') flag=${BK_RESEARCH_CANDIDATE_ENABLED:-<unset>}"
[ "$DIRTY" = "0" ] || { echo "GATE FAIL: worktree not clean ($DIRTY)"; FAILED=1; }
git merge-base --is-ancestor fd63b10 HEAD || { echo "FATAL: fd63b10 is not an ancestor of HEAD"; exit 3; }
OUT=$(mktemp -d)
declare -A EXP=( [qc_research_candidate_contract]=128 [qc_research_candidate_store]=80 \
                 [qc_research_candidate_backup]=50 [qc_research_candidate_idempotency]=56 \
                 [qc_nfl_identity_event_adapter]=48 [qc_research_candidate_route]=51 \
                 [qc_nfl_season_contract]=49 )
for f in qc_research_candidate_contract qc_research_candidate_store qc_research_candidate_backup \
         qc_research_candidate_idempotency qc_nfl_identity_event_adapter qc_research_candidate_route \
         qc_nfl_season_contract; do
  "$PY" "$f.py" > "$OUT/$f.out" 2>&1; rc=$?
  nok=$(grep -c '\[ok\]' "$OUT/$f.out"); nfail=$(grep -c '\[FAIL\]' "$OUT/$f.out"); exp=${EXP[$f]}
  printf '%-38s exit=%s ok=%s/%s FAIL=%s\n' "$f" "$rc" "$nok" "$exp" "$nfail"
  { [ "$rc" -eq 0 ] && [ "$nfail" -eq 0 ] && [ "$nok" -eq "$exp" ]; } \
    || { echo "GATE FAIL: $f (exit=$rc ok=$nok expected=$exp FAIL=$nfail)"; FAILED=1; }
done
RT="$OUT/qc_research_candidate_route.out"
grep -q 'POSIX-only.*skipped' "$RT" && { echo "GATE FAIL: [Q] skipped"; FAILED=1; }
while IFS= read -r line; do grep -qF "$line" "$RT" || { echo "GATE FAIL: missing POSIX line: $line"; FAILED=1; }; done <<'LINES'
approved directory is 0700
DB file is 0600
every present DB/WAL/SHM file is 0600
a sidecar chmod failure raises ConfigError
a sidecar whose mode is not 0600 fails verification
the post-commit relock failure returns 503
exactly one observation was committed
LINES
echo "flag_after_run=${BK_RESEARCH_CANDIDATE_ENABLED:-<unset>}"
if [ "$FAILED" -eq 0 ]; then echo "PREPROD ACCEPTANCE: PASS"; else echo "PREPROD ACCEPTANCE: FAIL"; fi
ACCEPT
```

Paste the full console output as the receipt. If SSM is unavailable, separately authorize the CI workflow.
