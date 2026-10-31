# Research Candidate 2D1 — OFF-State Deployment Plan (flag stays unset)

**Status: PLAN (step 1 of the authorized next phase). Deploy + verify are owner-run on prod.** The Linux
pre-production gate is CLOSED/PASS for HEAD `5282f6e`
(`docs/research_candidate_2d1_preprod_acceptance.md`). This phase ships the approved code to production
**with `BK_RESEARCH_CANDIDATE_ENABLED` still unset**, then verifies the feature is inert. **Observation
capture is NOT enabled in this phase** — enabling the flag remains a separate, explicit, still-unauthorized
decision.

## Invariant (must hold throughout)

- `BK_RESEARCH_CANDIDATE_ENABLED` and the path envs (`BK_RESEARCH_CANDIDATE_DB_PATH`/`_ROOT`/`_PROPS`/
  `_ROSTER`) are **never set** on the prod unit or `.env`.
- No store DB/dir is created; no research-candidate module is imported by the running app.
- No systemd unit, backup unit, UI, candidate/outcome/evaluation path is added or enabled.
- With the flag unset the dark route `POST /research-candidate/observe` is reached only inside the view,
  where its first statement is `abort(404)` — so it imports nothing and writes nothing.

## 0. Pre-deploy integrity checks

1. The code being shipped is byte-identical (in Python) to the gate-tested HEAD — later commits are
   docs-only. On the feature branch:
   ```bash
   git diff --stat 5282f6e..HEAD -- '*.py'    # MUST be empty (no .py changed since the gate-tested HEAD)
   ```
2. Confirm the prod unit/.env carries none of the feature envs (expect no output):
   ```bash
   systemctl show bankrollkings -p Environment | tr ' ' '\n' | grep -i BK_RESEARCH_CANDIDATE || echo "none in unit"
   grep -i BK_RESEARCH_CANDIDATE /opt/bankrollkings/.env 2>/dev/null || echo "none in .env"
   ```

## 1. Deploy (standard path; flag stays unset)

Per `CLAUDE.md` §3, deploy = advance `master`; the `bk-deploy.timer` pulls `origin/master` (ff-only) and
`systemctl restart bankrollkings` within ~2 min. So merge the approved branch into `master` and push it
(no SSH needed; **do not** touch the unit's environment):

```bash
git checkout master && git pull --ff-only && git merge --no-ff claude/jolly-ishizaka-c6519a && git push origin master
```

Watch it land and confirm the service came back:
```bash
journalctl -u bk-deploy.service -n 30 --no-pager      # shows pull -> restart -> health probe
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
unset (§0.2) and that no store artifact exists under any plausible path (expect none):
```bash
ls -la /var/lib/bankrollkings/research_candidate/ 2>/dev/null || echo "no research_candidate store dir"
```

**C. HTTP behavior (expected, honest).** The route is POST-only and CSRF-protected, so:
- `GET /research-candidate/observe` → **405** (method not allowed). This is identical whether the flag is
  on or off — it only reveals a POST path is registered, nothing about the feature state.
- An anonymous `POST` (no CSRF) → **400** from the global CSRF hook, before the view runs.
- A CSRF-valid owner `POST` → **404** (the flag-off `abort(404)`), i.e. no capture.
  ```bash
  curl -s -o /dev/null -w 'GET=%{http_code}\n' https://bankrollkings.com/research-candidate/observe
  curl -s -o /dev/null -w 'POST_no_csrf=%{http_code}\n' -X POST https://bankrollkings.com/research-candidate/observe
  ```
  The authoritative "no capture / nothing loaded" evidence is **A** (import proof) + the unset envs, not the
  HTTP code of an anonymous probe.

## 3. Rollback

The feature is dark, so risk is low. If anything regresses, revert the merge on `master` and let the timer
redeploy:
```bash
git checkout master && git revert --no-edit -m 1 <merge-sha> && git push origin master
```
The runtime store DB (if one ever existed — it does not in this phase) lives outside the checkout and is
untouched by deploys.

## Explicitly NOT in this phase

Setting `BK_RESEARCH_CANDIDATE_ENABLED`, provisioning any `BK_RESEARCH_CANDIDATE_*` path, creating the store
DB, adding a backup systemd unit, any UI, and any candidate-freeze / outcome / evaluation / thesis-generation
/ deletion / promotion. Enabling observation capture is a separate explicit decision after this OFF-state
deploy is verified.
