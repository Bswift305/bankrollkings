# Research Candidate 2D1 — Linux Pre-Production Acceptance Gate (flag OFF)

**Status: MANDATORY GATE before the dark 2D1 route may ever be enabled.** 2D1 local integration is approved
and closed (`fd63b10`), but the POSIX permission guarantees — `[P]` live-sidecar 0600, `[Q]` sidecar
chmod/verify fail-closed, `[R]` post-commit relock → 503 — are **skipped on the Windows dev box** (chmod
cannot set NTFS ACLs). They must be exercised on a **Linux, deployment-like filesystem** (ext4/xfs, not a
network/again-mounted share) **before enabling**. Production enablement remains unauthorized.

**Invariants this gate does NOT change:** the feature flag `BK_RESEARCH_CANDIDATE_ENABLED` stays **OFF by
default** (unset on the systemd unit / `.env`); no UI, candidate-freeze, outcome, evaluation, thesis
generation, backup unit, deletion, or promotion. The QC runs in an isolated process against **temp
directories only** — it never touches prod data or the live DB, and running it does NOT enable the feature
(it sets the flag in its own test process, not on the deployed service).

## What to run

On a **Linux** checkout of the feature branch `claude/jolly-ishizaka-c6519a` (a staging host or container
with the project venv), with the flag unset:

```bash
cd /path/to/bankrollkings-branch-checkout && \
unset BK_RESEARCH_CANDIDATE_ENABLED && \
export SECRET_KEY="preprod-acceptance-dummy" && \
PY=$( [ -x venv/bin/python ] && echo venv/bin/python || { [ -x .venv/bin/python ] && echo .venv/bin/python || echo python3; } ) && \
echo "python: $PY  |  os: $("$PY" -c 'import os;print(os.name)')  |  flag: ${BK_RESEARCH_CANDIDATE_ENABLED:-<unset>}" && \
for f in qc_research_candidate_contract qc_research_candidate_store qc_research_candidate_backup \
         qc_research_candidate_idempotency qc_nfl_identity_event_adapter qc_research_candidate_route \
         qc_nfl_season_contract; do \
  "$PY" "$f.py" > "/tmp/rc_$f.out" 2>&1; rc=$?; \
  printf '%-38s exit=%s ok=%s FAIL=%s\n' "$f" "$rc" \
    "$(grep -c '\[ok\]' "/tmp/rc_$f.out")" "$(grep -c '\[FAIL\]' "/tmp/rc_$f.out")"; \
done; \
echo "--- [P]/[Q]/[R] POSIX assertions actually executed (must NOT say 'skipped'): ---"; \
grep -E "DB file is 0600|approved directory is 0700|every present DB/WAL/SHM|sidecar chmod failure raises|not 0600|POSIX-only.*skipped|post-commit relock failure returns 503|exactly one observation was committed" \
    "/tmp/rc_qc_research_candidate_route.out" || echo "(route QC produced no matching lines — INVESTIGATE)"
```

## Receipt must show (to pass the gate)

1. `os: posix` and `flag: <unset>` on the header line.
2. Every suite `exit=0` with `FAIL=0` — notably `qc_research_candidate_route` (51 checks).
3. In the `[P]/[Q]/[R]` grep: the real POSIX lines present — `DB file is 0600`, `approved directory is
   0700`, `every present DB/WAL/SHM file is 0600`, `a sidecar chmod failure raises ConfigError`, `a sidecar
   whose mode is not 0600 fails verification`, `the post-commit relock failure returns 503`, `exactly one
   observation was committed` — and **no** `POSIX-only … skipped` line for `[Q]`.

Return the full console output as the acceptance receipt. It is read-only w.r.t. production (temp dirs
only) and leaves the deployed flag OFF.
