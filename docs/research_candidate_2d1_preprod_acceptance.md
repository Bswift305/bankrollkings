# Research Candidate 2D1 — Linux Pre-Production Acceptance Gate (scoped release, flag OFF) — Rev 2

**Status: OPEN for the scoped release — the gate must be re-run against the release HEAD.** The earlier gate
run (feature branch, HEAD `5282f6e`) **PASSED** and that receipt is retained below, but it **does not
authorize the scoped release**: the release `release/research-candidate-2d1` is a different commit on a
different base (`origin/master`), and a differently-scoped release must carry its **own** PASS before deploy.
Rev 2 replaces the feature-branch code-identity binding (`fd63b10` ancestor) with a **scope proof** suited to
a release branch, and otherwise preserves the Rev 1.3 gate (exact suite counts, ext4/xfs allow-list, POSIX
`[P]/[Q]/[R]` assertions, `GATE OK` echoes, exit 0/1).

Why a Linux gate at all: the POSIX permission guarantees — `[P]` live-sidecar 0600, `[Q]` sidecar
chmod/verify fail-closed, `[R]` post-commit relock → 503 — are **skipped on the Windows dev box** (chmod
cannot set NTFS ACLs) and must be exercised on a **Linux ext4/xfs filesystem**. **Clearing this gate
authorizes none of the production behavior by itself** — deploying or enabling `BK_RESEARCH_CANDIDATE_ENABLED`
remains a separate explicit decision; the safest next phase is deployment with the flag still OFF, followed by
an OFF-state production verification (`docs/research_candidate_2d1_offstate_deploy_plan.md` Rev 2).

## Release identity this gate binds to (scope proof)

- **Base:** the release is **one commit** on `origin/master` base
  `d09668c6fd9db7b9e264397b6070103d2d054b66`, so `HEAD~1` **is** that base and `HEAD~1..HEAD` is a single
  commit. (If the release is rebuilt on a newer master, update this sha and re-run.)
- **Scope:** `git diff --name-only HEAD~1 HEAD` is **exactly** these 22 paths — the 2D1 set and nothing from
  the excluded families (Decision Integrity, entity-links, NBA, streak/template, NFL ATS):
  ```
  app.py
  docs/research_candidate_2d1_identity_feasibility.md
  docs/research_candidate_2d1_offstate_deploy_plan.md
  docs/research_candidate_2d1_preprod_acceptance.md
  docs/research_candidate_2d_integration_audit.md
  docs/research_candidate_contract.md
  docs/research_candidate_idempotency_registry_design.md
  docs/research_candidate_identity_event_adapter_design.md
  docs/research_candidate_player_milestone_usage.md
  docs/research_candidate_store_contract.md
  qc_nfl_identity_event_adapter.py
  qc_nfl_season_contract.py
  qc_research_candidate_backup.py
  qc_research_candidate_contract.py
  qc_research_candidate_idempotency.py
  qc_research_candidate_route.py
  qc_research_candidate_store.py
  services/nfl_identity_event_adapter.py
  services/nfl_season_contract.py
  services/research_candidate.py
  services/research_candidate_boundary.py
  services/research_candidate_store.py
  ```
- **`.py` subset:** the only Python changed is `app.py` + the 5 services + the 7 QCs (13 files).

The gate self-asserts all of the above; a dirty tree, a non-single-commit shape, or any path outside the set
is a GATE FAIL.

**Invariants this gate does NOT change:** `BK_RESEARCH_CANDIDATE_ENABLED` stays **OFF by default** (unset on
the unit / `.env`); no UI, candidate-freeze, outcome, evaluation, thesis generation, backup unit, deletion,
or promotion. The QC runs in an isolated process against **temp directories only** — it never touches prod
data or the live DB, and running it does NOT enable the feature (it sets the flag in its own test process).

## What to run

On a **Linux** checkout of the release branch (a staging host or container with the project venv), flag
unset. The script self-asserts and exits nonzero on any failure — paste the full output (ending in
`PREPROD ACCEPTANCE: PASS`/`FAIL`) as the receipt:

```bash
set -u
cd /path/to/bankrollkings-release-checkout || { echo "FATAL: cd failed"; exit 2; }
unset BK_RESEARCH_CANDIDATE_ENABLED
export SECRET_KEY="preprod-acceptance-dummy"
PY=$( [ -x venv/bin/python ] && echo venv/bin/python || { [ -x .venv/bin/python ] && echo .venv/bin/python || echo python3; } )
EXPECT_BASE=d09668c6fd9db7b9e264397b6070103d2d054b66
FAILED=0

# (1) code identity = scope proof: clean tree, ONE commit on the recorded origin/master base, and the diff
#     touches EXACTLY the 22 scoped paths (13 of them .py = app.py + 5 services + 7 QCs). No excluded work.
HEAD_SHA=$(git rev-parse HEAD); BASE_SHA=$(git rev-parse HEAD~1)
DIRTY=$(git status --porcelain | wc -l | tr -d ' ')
NCOMMITS=$(git rev-list --count "$BASE_SHA".."$HEAD_SHA")
echo "head=$HEAD_SHA base=$BASE_SHA expect_base=$EXPECT_BASE commits=$NCOMMITS worktree_changes=$DIRTY os=$("$PY" -c 'import os;print(os.name)') flag=${BK_RESEARCH_CANDIDATE_ENABLED:-<unset>}"
[ "$DIRTY" = "0" ] || { echo "GATE FAIL: worktree has $DIRTY uncommitted change(s)"; FAILED=1; }
[ "$BASE_SHA" = "$EXPECT_BASE" ] && echo "GATE OK: release sits on the recorded master base" || { echo "GATE FAIL: HEAD~1 ($BASE_SHA) != recorded base ($EXPECT_BASE)"; FAILED=1; }
[ "$NCOMMITS" = "1" ] && echo "GATE OK: exactly one commit on the base" || { echo "GATE FAIL: $NCOMMITS commits on base (expected 1)"; FAILED=1; }
EXPECT_SCOPE=$(printf '%s\n' app.py \
  docs/research_candidate_2d1_identity_feasibility.md docs/research_candidate_2d1_offstate_deploy_plan.md \
  docs/research_candidate_2d1_preprod_acceptance.md docs/research_candidate_2d_integration_audit.md \
  docs/research_candidate_contract.md docs/research_candidate_idempotency_registry_design.md \
  docs/research_candidate_identity_event_adapter_design.md docs/research_candidate_player_milestone_usage.md \
  docs/research_candidate_store_contract.md qc_nfl_identity_event_adapter.py qc_nfl_season_contract.py \
  qc_research_candidate_backup.py qc_research_candidate_contract.py qc_research_candidate_idempotency.py \
  qc_research_candidate_route.py qc_research_candidate_store.py services/nfl_identity_event_adapter.py \
  services/nfl_season_contract.py services/research_candidate.py services/research_candidate_boundary.py \
  services/research_candidate_store.py | sort)
ACTUAL_SCOPE=$(git diff --name-only "$BASE_SHA" "$HEAD_SHA" | sort)
if [ "$ACTUAL_SCOPE" = "$EXPECT_SCOPE" ]; then echo "GATE OK: release scope is exactly the 22 2D1 paths"; else
  echo "GATE FAIL: release scope differs from the 22 2D1 paths"; echo "--- unexpected/missing ---"; diff <(echo "$EXPECT_SCOPE") <(echo "$ACTUAL_SCOPE"); FAILED=1; fi
EXPECT_PY=$(printf '%s\n' app.py qc_nfl_identity_event_adapter.py qc_nfl_season_contract.py \
  qc_research_candidate_backup.py qc_research_candidate_contract.py qc_research_candidate_idempotency.py \
  qc_research_candidate_route.py qc_research_candidate_store.py services/nfl_identity_event_adapter.py \
  services/nfl_season_contract.py services/research_candidate.py services/research_candidate_boundary.py \
  services/research_candidate_store.py | sort)
ACTUAL_PY=$(git diff --name-only "$BASE_SHA" "$HEAD_SHA" | grep '\.py$' | sort)
[ "$ACTUAL_PY" = "$EXPECT_PY" ] && echo "GATE OK: only app.py + 5 services + 7 QCs changed (.py)" || { echo "GATE FAIL: unexpected .py changes"; diff <(echo "$EXPECT_PY") <(echo "$ACTUAL_PY"); FAILED=1; }

# (3) scratch + TMPDIR on a VERIFIED deployment-like fs (ext4/xfs allow-list); set ACCEPT_BASE if /var/tmp isn't it
BASE=${ACCEPT_BASE:-/var/tmp}
FSTYPE=$(findmnt -nro FSTYPE -T "$BASE" 2>/dev/null || echo unknown)
echo "scratch_base=$BASE fstype=$FSTYPE"
case "$FSTYPE" in ext4|xfs) ;; *) echo "FATAL: $BASE is '$FSTYPE' — acceptance requires ext4 or xfs (set ACCEPT_BASE)"; exit 2 ;; esac
SCRATCH=$(mktemp -d "$BASE/rc2d1.XXXXXX") || { echo "FATAL: mktemp failed"; exit 2; }
trap 'rm -rf "$SCRATCH"' EXIT
export TMPDIR="$SCRATCH"; OUT="$SCRATCH/out"; mkdir -p "$OUT"

# (2) each suite must exit 0, have no [FAIL], AND match its expected [ok] total (a lost test fails the gate)
declare -A EXP=( [qc_research_candidate_contract]=128 [qc_research_candidate_store]=80 \
                 [qc_research_candidate_backup]=50 [qc_research_candidate_idempotency]=56 \
                 [qc_nfl_identity_event_adapter]=48 [qc_research_candidate_route]=54 \
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

# (5) assert every required [P]/[Q]/[R] POSIX line individually; echo GATE OK on success so it is auditable
RT="$OUT/qc_research_candidate_route.out"
if grep -q 'POSIX-only.*skipped' "$RT"; then echo "GATE FAIL: [Q] skipped (not a POSIX fs)"; FAILED=1; else echo "GATE OK: [Q] POSIX assertions ran (not skipped)"; fi
while IFS= read -r line; do
  if grep -qF "$line" "$RT"; then echo "GATE OK: $line"; else echo "GATE FAIL: missing POSIX line: $line"; FAILED=1; fi
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

1. Header: `base=<sha>` equal to the recorded `expect_base`, `commits=1`, `worktree_changes=0`, `os=posix`,
   `flag=<unset>`, and `scratch_base=… fstype=ext4` or `xfs` (any other fstype is FATAL). A `GATE OK:` line
   for release-sits-on-base, one-commit, the 22-path scope, and the `.py`-subset checks.
2. Every suite `exit=0 FAIL=0` and `ok=<n>/<n>` matching its expected total (contract 128, store 80,
   backup 50, idempotency 56, adapter 48, **route 54** on Linux, season 49). Note: a local **Windows** run
   shows **route 51** — the `[Q]`/`[I]`/`[P]` POSIX branches each run one more assertion on ext4/xfs than
   their Windows skip/best-effort branch (+3), which is exactly what this gate is for.
3. A `GATE OK:` line for each required `[P]/[Q]/[R]` assertion (incl. `[Q] … ran (not skipped)`), and
   **no** `GATE FAIL:` line.
4. Final line `PREPROD ACCEPTANCE: PASS` with **exit status 0** (the script exits 1 on FAIL).

The run is read-only w.r.t. production (scratch tree only) and leaves the deployed flag OFF.

## Appendix: running the receipt on EC2 via SSM (disposable clone of the release branch)

A **standalone read-only scratch clone** of `origin` on the Linux EC2 host, using the production venv. It
leaves `/opt/bankrollkings` **entirely untouched** — only `git remote get-url` (read-only) is run against it;
the clone, checkout, and all temp output live under one scratch tree on a verified ext4/xfs filesystem and
are removed by a cleanup trap. The flag stays unset. A fresh clone carries code only (data is gitignored);
the QC uses its own temp dirs under `TMPDIR`, and `app` import writes only the clone's own `data/cache`. If
`import app` fails for a genuinely missing data file (only the `route`/`season` suites import `app`), capture
the exact error and we'll expose just that path read-only. Edit `BASE` if `/var/tmp` is not a deployment-like
ext4/xfs volume on the host:

```bash
sudo -u ubuntu -H bash <<'ACCEPT'
set -u
BRANCH=release/research-candidate-2d1
EXPECT_BASE=d09668c6fd9db7b9e264397b6070103d2d054b66
PY=/opt/bankrollkings/venv/bin/python
BASE=${ACCEPT_BASE:-/var/tmp}
FSTYPE=$(findmnt -nro FSTYPE -T "$BASE" 2>/dev/null || echo unknown)
echo "scratch_base=$BASE fstype=$FSTYPE"
case "$FSTYPE" in ext4|xfs) ;; *) echo "FATAL: $BASE is '$FSTYPE' — acceptance requires ext4 or xfs (set ACCEPT_BASE)"; exit 2 ;; esac
SCRATCH=$(mktemp -d "$BASE/rc2d1.XXXXXX") || { echo "FATAL: mktemp failed"; exit 2; }
trap 'rm -rf "$SCRATCH"' EXIT
export TMPDIR="$SCRATCH"; WT="$SCRATCH/wt"; OUT="$SCRATCH/out"; mkdir -p "$OUT"
# standalone read-only clone of origin — /opt/bankrollkings is NOT fetched into or otherwise modified.
# NOTE: --single-branch still fetches enough history for HEAD~1 (the base commit) to resolve.
REMOTE=$(git -C /opt/bankrollkings remote get-url origin) || { echo "FATAL: cannot read origin url"; exit 2; }
git clone --quiet --single-branch --branch "$BRANCH" "$REMOTE" "$WT" || { echo "FATAL: clone failed"; exit 2; }
cd "$WT" || { echo "FATAL: cd clone"; exit 2; }
unset BK_RESEARCH_CANDIDATE_ENABLED
export SECRET_KEY="preprod-acceptance-dummy"
FAILED=0
HEAD_SHA=$(git rev-parse HEAD); BASE_SHA=$(git rev-parse HEAD~1); DIRTY=$(git status --porcelain | wc -l | tr -d ' ')
NCOMMITS=$(git rev-list --count "$BASE_SHA".."$HEAD_SHA")
echo "head=$HEAD_SHA base=$BASE_SHA expect_base=$EXPECT_BASE commits=$NCOMMITS worktree_changes=$DIRTY os=$("$PY" -c 'import os;print(os.name)') flag=${BK_RESEARCH_CANDIDATE_ENABLED:-<unset>}"
[ "$DIRTY" = "0" ] || { echo "GATE FAIL: clone not clean ($DIRTY)"; FAILED=1; }
[ "$BASE_SHA" = "$EXPECT_BASE" ] && echo "GATE OK: release sits on the recorded master base" || { echo "GATE FAIL: HEAD~1 ($BASE_SHA) != recorded base ($EXPECT_BASE)"; FAILED=1; }
[ "$NCOMMITS" = "1" ] && echo "GATE OK: exactly one commit on the base" || { echo "GATE FAIL: $NCOMMITS commits on base (expected 1)"; FAILED=1; }
EXPECT_SCOPE=$(printf '%s\n' app.py \
  docs/research_candidate_2d1_identity_feasibility.md docs/research_candidate_2d1_offstate_deploy_plan.md \
  docs/research_candidate_2d1_preprod_acceptance.md docs/research_candidate_2d_integration_audit.md \
  docs/research_candidate_contract.md docs/research_candidate_idempotency_registry_design.md \
  docs/research_candidate_identity_event_adapter_design.md docs/research_candidate_player_milestone_usage.md \
  docs/research_candidate_store_contract.md qc_nfl_identity_event_adapter.py qc_nfl_season_contract.py \
  qc_research_candidate_backup.py qc_research_candidate_contract.py qc_research_candidate_idempotency.py \
  qc_research_candidate_route.py qc_research_candidate_store.py services/nfl_identity_event_adapter.py \
  services/nfl_season_contract.py services/research_candidate.py services/research_candidate_boundary.py \
  services/research_candidate_store.py | sort)
ACTUAL_SCOPE=$(git diff --name-only "$BASE_SHA" "$HEAD_SHA" | sort)
[ "$ACTUAL_SCOPE" = "$EXPECT_SCOPE" ] && echo "GATE OK: release scope is exactly the 22 2D1 paths" || { echo "GATE FAIL: release scope differs"; diff <(echo "$EXPECT_SCOPE") <(echo "$ACTUAL_SCOPE"); FAILED=1; }
declare -A EXP=( [qc_research_candidate_contract]=128 [qc_research_candidate_store]=80 \
                 [qc_research_candidate_backup]=50 [qc_research_candidate_idempotency]=56 \
                 [qc_nfl_identity_event_adapter]=48 [qc_research_candidate_route]=54 \
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
if grep -q 'POSIX-only.*skipped' "$RT"; then echo "GATE FAIL: [Q] skipped"; FAILED=1; else echo "GATE OK: [Q] POSIX assertions ran (not skipped)"; fi
while IFS= read -r line; do
  if grep -qF "$line" "$RT"; then echo "GATE OK: $line"; else echo "GATE FAIL: missing POSIX line: $line"; FAILED=1; fi
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
ACCEPT
```

Paste the full console output (ending `PREPROD ACCEPTANCE: PASS`, exit 0) as the release receipt below.

## Release acceptance receipt — PENDING

_To be filled when the owner runs the gate against `release/research-candidate-2d1`:_

| Field | Value |
|---|---|
| SSM command id | _pending_ |
| Instance | _pending_ |
| Tested HEAD | _pending (release/research-candidate-2d1 HEAD)_ |
| Base (`HEAD~1`) | `d09668c6fd9db7b9e264397b6070103d2d054b66` (expected) |
| Commits on base | `1` (expected) |
| Scope | exactly the 22 2D1 paths (expected) |
| Clean checkout | _pending_ |
| Filesystem | _pending (ext4/xfs)_ |
| Flag `BK_RESEARCH_CANDIDATE_ENABLED` | unset before AND after (expected) |
| Suites | contract 128, store 80, backup 50, idempotency 56, adapter 48, route 54, season 49, zero `[FAIL]` (expected) |
| Final result | _pending_ `PREPROD ACCEPTANCE: PASS` |

## Historical receipt — feature-branch implementation (does NOT authorize the scoped release)

The Rev 1.3 gate was run on the EC2 Linux host against the **feature branch** and passed. Retained for the
record; it certifies the feature-branch implementation, not this scoped release:

| Field | Value |
|---|---|
| SSM command id | `327c6548-2a1a-4729-bafa-c9a85863d48e` |
| Instance | `i-08d2fd818875381dd` |
| Tested HEAD | `5282f6e23217a401ecb6cdbb1f1a746da6831baf` (branch `claude/jolly-ishizaka-c6519a`) |
| Clean checkout | yes (`worktree_changes=0`) |
| Filesystem | ext4 |
| OS | POSIX |
| Flag `BK_RESEARCH_CANDIDATE_ENABLED` | unset before AND after |
| Suites | all seven at exact counts (contract 128, store 80, backup 50, idempotency 56, adapter 48, **route 54**, season 49), zero `[FAIL]` |
| POSIX `[P]/[Q]/[R]` | all DB/WAL/SHM permission + fail-closed assertions passed (`GATE OK` each) |
| Final result | **`PREPROD ACCEPTANCE: PASS`** |

The 13 `.py` files in the scoped release are **byte-identical** to this gate-tested feature HEAD, so the same
code is exercised; the release gate re-confirms that on the release's exact tree and proves the scope.
