# CFB Matchup Total-Render Fix — Receipt (`da2c3c2`)

**Date:** 2026-10-23
**Scope:** page-local template correction only — no data, logic, ranking, or governance change.

## The defect and the fix

`templates/cfb_matchup.html`, the "This Week's Matchups" header line (`.mu-wk-ln`), rendered the raw
Python object behind `g.total` whenever it was not a number. `build_cfb_matchup_context()`
(`app.py`) sets `wg['total'] = cfb_current_form.total_read(...)`, which returns a **mapping**
(`{proj_total, line, lean, edge, league_pts, skill_note, away_qb_out}`) or `None` — so the old
`{{ '%g'|format(g.total) if g.total is number else g.total }}` dumped the whole dict into the header.
This is the same class of defect fixed for NFL in `24273df`.

The fix shows the posted over/under (`g.total.line`), handling mapping / bare-number / empty:

```jinja
{% set _ou = (('%g'|format(g.total.line) if (g.total is mapping and g.total.line is number)
   else ('%g'|format(g.total) if g.total is number else '')) if g.total else '') %}
{% if _ou %} &middot; O/U {{ _ou }}{% endif %}
```

## Permanent regression guard

**`qc_cfb_matchup_total.py`** — registered in `run_all_scorecards.py` as **"CFB Matchup Total QC"**.
It renders the **real route + real template** (`GET /tools/cfb-matchup`) with `build_cfb_matchup_context`
monkeypatched to a fixed `mu_week`, exercising all five shapes `g.total` can take and asserting the
rendered button carries no dict/`None`/malformed-object text, and that the numeric cases show
`O/U <number>`:

| case | `g.total` | expected header |
|------|-----------|-----------------|
| mapping with numeric line | `{proj_total, line:48.5, lean:OVER, …}` | `O/U 48.5` |
| mapping with `line = None` | `{…, line:None, …}` | no O/U, no leak |
| missing total | `None` | no O/U, no leak |
| legacy scalar total | `47.5` | `O/U 47.5` |
| malformed mapping | `{line:'n/a', junk:[…], …}` | no O/U, no leak |

- **Positive control:** green on current `master` (exit 0) — contract holds across all five shapes.
- **Negative control:** with the pre-fix template line restored, the QC fails loudly, catching the
  literal dict dump (`O/U {'proj_total': 54.2, 'line': 48.5, …}`) on every mapping case while the
  scalar/missing cases still pass. The guard genuinely detects the regression.
- The test is deterministic and self-contained: it depends on no live CFB data and no users-store
  row (the owner access gate is satisfied by patching the identity boundary, not the template).

## Production server-side receipt

| check | result |
|-------|--------|
| Deploy source-of-truth | `git ls-remote origin master` → `da2c3c2…` — the exact ref the prod `bk-deploy` timer pulls. Local HEAD == `da2c3c2`, and `da2c3c2` is an ancestor of `origin/master`. |
| Service active | `GET https://bankrollkings.com/healthz` → **200** |
| Probe healthy | `/healthz` body: `{"data_present":true,"status":"ok","time":"2026-10-23T16:36Z"}` |
| Regression QC green | `python qc_cfb_matchup_total.py` → exit 0; runner entry "CFB Matchup Total QC" → PASS |
| Authenticated Flask test-client render | `GET /tools/cfb-matchup` → **200**; `.mu-wk-ln` emits `… · O/U 48.5 · …` and `… · O/U 47.5 · …` for the numeric cases; **zero** dict/`None` leak across all five shapes |

### One server-side line this session could not self-verify

Confirming the **prod working-copy HEAD** has advanced to `da2c3c2` (vs. the GitHub ref the timer
pulls) requires a shell on the instance. This session has no SSH (source-restricted to a stale /32),
no AWS CLI, and the gated page returns 401 to an anonymous HTTP client, so prod's checked-out SHA
cannot be read over HTTP. Confirm via AWS Session Manager (us-east-1 → Systems Manager → Session
Manager; `ssm-user`, passwordless sudo):

```bash
sudo -u ubuntu git -C /opt/bankrollkings log --oneline -1    # expect da2c3c2 at or after HEAD
systemctl is-active bankrollkings                            # expect: active
```

The `bk-deploy` timer pulls `origin/master` (now `da2c3c2`) and restarts within ~2 minutes of the
push, so this is expected to already be satisfied; the command above is the authoritative confirmation.

## Remaining external check (Step 4)

The **only** remaining verification for this correction is a human, authenticated, visual pass on the
live page — it cannot be produced from this session (auth-gated page + local-preview-only browser;
credentials are never entered here):

- Sign in and open **`https://bankrollkings.com/tools/cfb-matchup`**.
- **Desktop and 375px (mobile)**: each "This Week's Matchups" row reads `TEAM @ TEAM`, then
  `· O/U <number>` where a total is posted (and simply no O/U where none is), with **no**
  `{'proj_total': …}` / `None` / brace text anywhere in the line.

Everything else in this correction is verified server-side above.
