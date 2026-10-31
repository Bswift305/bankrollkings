# Research Candidate 2D1 — OFF-State Deployment Plan (scoped release, flag stays unset) — Rev 2

**Status: PLAN. Deploy + verify are owner-run on prod. SUPERSEDES Rev 1.** Rev 1 proposed merging the whole
feature branch `claude/jolly-ishizaka-c6519a` into `master`. That was **unsafe**: the feature branch carries
~14.9k lines of unrelated work (Decision Integrity, entity-links, NBA acceptance, streak/template, NFL ATS
shadow). The earlier integrity check (`git diff 5282f6e..HEAD`) only proved *no Python changed since the
gate-tested HEAD* — it said **nothing** about what the branch adds over production. This revision ships a
**scoped release branch** that contains only the Research Candidate 2D1 code, built on current
`origin/master`.

This phase ships the approved code **with `BK_RESEARCH_CANDIDATE_ENABLED` still unset**, then verifies the
feature is inert. **Observation capture is NOT enabled** — enabling the flag remains a separate, explicit,
still-unauthorized decision.

## The release branch

`release/research-candidate-2d1`, cut from `origin/master` with **one commit** adding exactly the 2D1 set:

- **5 service modules** — `services/research_candidate.py`, `services/research_candidate_store.py`,
  `services/research_candidate_boundary.py`, `services/nfl_identity_event_adapter.py`,
  `services/nfl_season_contract.py`.
- **`app.py` — two RC hunks only:** (1) the `_nfl_expected_completed_week` delegation to the pure
  `services/nfl_season_contract` (replacing the inline `NFL_SEASON_WEEK1_THURSDAY` dict + week math), and
  (2) the dark, flag-gated, owner-only `POST /research-candidate/observe` route + `RESEARCH_CANDIDATE_ENABLED`
  flag + `_research_candidate_is_owner` predicate appended before `if __name__ == '__main__':`. **No**
  entity-link server helpers, ATS-shadow hooks, or streak/heatmap changes are included.
- **7 QC suites** — `qc_research_candidate_contract.py`, `qc_research_candidate_store.py`,
  `qc_research_candidate_backup.py`, `qc_research_candidate_idempotency.py`, `qc_research_candidate_route.py`,
  `qc_nfl_identity_event_adapter.py`, `qc_nfl_season_contract.py`.
- **9 design/acceptance docs** — the `docs/research_candidate_*.md` set (this plan + the acceptance runbook
  among them).

The 19 code/QC/design files are **byte-identical** to the gate-tested feature HEAD; only this deploy plan and
the acceptance runbook are release-specific revisions. Nothing from the excluded families ships.

## 0. Pre-deploy integrity (scope proof — the Rev-1 check was insufficient)

Run on the release branch. The release is **one commit on `origin/master`**, so `HEAD~1` is the master base.

1. Clean tree and single-commit-on-master shape:
   ```bash
   git -C . status --porcelain        # MUST be empty
   git rev-parse HEAD~1               # MUST equal the origin/master base recorded in the acceptance runbook
   ```
2. The release changes **exactly** the 2D1 paths — nothing from the excluded families:
   ```bash
   git diff --name-only HEAD~1 HEAD | sort    # MUST be exactly the 22 paths below
   ```
   Expected (22): `app.py`; `services/{research_candidate,research_candidate_store,research_candidate_boundary,nfl_identity_event_adapter,nfl_season_contract}.py`;
   `qc_{research_candidate_contract,research_candidate_store,research_candidate_backup,research_candidate_idempotency,research_candidate_route,nfl_identity_event_adapter,nfl_season_contract}.py`;
   `docs/research_candidate_*.md` (9). **No** `services/decision_*`, `services/nfl_ats_*`,
   `services/streak_explainer.py`, `templates/*`, `qc_*_entity_links.py`, `qc_decision_*`, `qc_nfl_ats_*`,
   `qc_streak_render.py`, `docs/nba_p0_*`, `docs/entity_link_*`, `docs/hot_hand_*`,
   `docs/decision_integrity_*`.
3. The only `.py` touched are `app.py` + the 5 services + the 7 QCs:
   ```bash
   git diff --name-only HEAD~1 HEAD | grep '\.py$' | sort
   ```
4. Prod unit/.env carries none of the feature envs (expect no output):
   ```bash
   systemctl show bankrollkings -p Environment | tr ' ' '\n' | grep -i BK_RESEARCH_CANDIDATE || echo "none in unit"
   grep -i BK_RESEARCH_CANDIDATE /opt/bankrollkings/.env 2>/dev/null || echo "none in .env"
   ```

## 0a. Gate dependency (BLOCKING)

The Linux pre-production acceptance gate must be **re-run against the release HEAD** and pass
(`docs/research_candidate_2d1_preprod_acceptance.md`, Rev 2). The existing feature-branch receipt
(HEAD `5282f6e`) remains valid for the feature-branch implementation but **does not authorize this scoped
release** — the release is a different commit on a different base and must carry its own PASS. Do not deploy
until the release receipt is recorded.

## 1. Deploy (fast-forward; flag stays unset)

Because the release is cut from `origin/master` with one commit, `master` **fast-forwards** to it — so the
deploy ships *exactly* the 22 scoped files and nothing else. **Do not** merge the feature branch. Per
`CLAUDE.md` §3, advancing `master` triggers `bk-deploy.timer` (ff-only pull + `systemctl restart`) within
~2 min (do **not** touch the unit environment):

```bash
git checkout master && git pull --ff-only
git merge --ff-only release/research-candidate-2d1    # refuses if master moved past the base -> re-verify scope
git push origin master
```

If `--ff-only` is refused because `master` advanced past the recorded base, **stop** and rebuild/re-verify
the release on the new base (re-run §0 + the Linux gate) rather than forcing a non-ff merge.

Watch it land and confirm the service came back:
```bash
journalctl -u bk-deploy.service -n 30 --no-pager      # pull -> restart -> health probe
systemctl is-active bankrollkings
curl -s -o /dev/null -w '%{http_code}\n' https://bankrollkings.com/   # app healthy (200/redirect)
```

## 2. OFF-state production verification

**A. Import proof (authoritative darkness).** With the flag unset, importing the deployed app must load
NO research-candidate module (mirrors the gate's OFF proof, on the real box + prod data):
```bash
cd /opt/bankrollkings && sudo -u ubuntu env -u BK_RESEARCH_CANDIDATE_ENABLED \
  "$([ -x venv/bin/python ] && echo venv/bin/python || echo python3)" - <<'PY'
import os, sys
assert os.environ.get('BK_RESEARCH_CANDIDATE_ENABLED') in (None, ''), 'flag must be unset'
import app
mods = [m for m in ('services.research_candidate_store', 'services.nfl_identity_event_adapter',
                    'services.research_candidate_boundary') if m in sys.modules]
print('rc_modules_imported =', mods)          # MUST be []
PY
```
(`SECRET_KEY` is already in the prod `.env`/unit env for the service user; if this one-off import complains
it is unset, run it with the same `SECRET_KEY` the unit uses — do not print it.)

**B. No DB / no writes.** The feature has no configured path, so nothing is created. Confirm the envs are
unset (§0.4) and that no store artifact exists under any plausible path (expect none):
```bash
ls -la /var/lib/bankrollkings/research_candidate/ 2>/dev/null || echo "no research_candidate store dir"
```

**C. HTTP behavior (expected, honest).** The route is POST-only and CSRF-protected, so:
- `GET /research-candidate/observe` → **405** (method not allowed). Identical whether the flag is on or off —
  it only reveals a POST path is registered, nothing about the feature state.
- An anonymous `POST` (no CSRF) → **400** from the global CSRF hook, before the view runs.
- A CSRF-valid owner `POST` → **404** (the flag-off `abort(404)`), i.e. no capture.
  ```bash
  curl -s -o /dev/null -w 'GET=%{http_code}\n' https://bankrollkings.com/research-candidate/observe
  curl -s -o /dev/null -w 'POST_no_csrf=%{http_code}\n' -X POST https://bankrollkings.com/research-candidate/observe
  ```
  The authoritative "no capture / nothing loaded" evidence is **A** (import proof) + the unset envs, not the
  HTTP code of an anonymous probe.

## 3. Rollback

The feature is dark, so risk is low. If anything regresses, revert on `master` and let the timer redeploy:
```bash
git checkout master && git revert --no-edit <release-commit-sha> && git push origin master
```
(The release is one commit, so a plain `git revert` of it removes exactly the 2D1 set.) The runtime store DB
(if one ever existed — it does not in this phase) lives outside the checkout and is untouched by deploys.

## Explicitly NOT in this phase

Setting `BK_RESEARCH_CANDIDATE_ENABLED`, provisioning any `BK_RESEARCH_CANDIDATE_*` path, creating the store
DB, adding a backup systemd unit, any UI, and any candidate-freeze / outcome / evaluation / thesis-generation
/ deletion / promotion. Shipping any file outside the 22 scoped paths. Enabling observation capture is a
separate explicit decision after this OFF-state deploy is verified.
