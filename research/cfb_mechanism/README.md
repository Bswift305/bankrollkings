# CFB Mechanism Audits — permanent record, reproduction & defect policy

This directory is the **permanent audit record** for the CFB sides/totals mechanism audits.
Per the standing directive: **archive means preserve — not "stop thinking about it," and not
"quietly change."** Read this before touching anything here.

## Status

| Audit | Candidate | Status | Verdict |
|---|---|---|---|
| #1 | Opponent-Adjusted Team Strength (cumulative SRS) | **Closed / Final** | Baseline / No demonstrated edge (51.8% ATS) |
| #2 | Team Form v1 (exp-weighted SRS, H=3) | **Closed / Final** | Failed / No demonstrated incremental edge |
| #3 | — | **Not started, not authorized** | — |

Audit #1 is the benchmark every future CFB sides mechanism must beat on the same paired
population. No CFB development, product, or deployment is authorized.

## The record is these artifacts — do not rewrite them

The frozen test, the executed test, the observed result, and the approved interpretation are
**distinct records** and must stay distinct:

- Pre-registration (frozen before results): `../../docs/cfb_mechanism_audit_02_preregistration.md`
- Frozen population + fingerprint: `audit2_frozen_population.json` (n=4,653,
  sha256 `ffb7c73f53d45e9c44249981714f3e6d3664ef78b92cbe46517d9bcc7ebbc6cd`)
- Population builder: `freeze_audit2_population.py`
- Execution code: `audit_opponent_adjusted_strength.py` (#1), `audit_team_form_w1.py` (#2)
- Results + bounded interpretation: `../../docs/cfb_mechanism_audit_01_*.md`,
  `../../docs/cfb_mechanism_audit_02_result.md`
- Evidence-base audit (why CFB is sides/totals): `../../docs/cfb_research_audit.md`

## Reproduction (verified 2026-10-09; read-only)

```bash
# Audit #1 -- expect: n=4653, ALL picks 51.8% [50.4, 53.3]
py -3 research/cfb_mechanism/audit_opponent_adjusted_strength.py

# Re-freeze / verify the population fingerprint -- expect n=4653, sha256 ffb7c73f...
py -3 research/cfb_mechanism/freeze_audit2_population.py

# Audit #2 -- expect: "fingerprint OK", disagreement flips 48.1%, VERDICT = no incremental edge
py -3 research/cfb_mechanism/audit_team_form_w1.py
```

The game-line history is a rolling CFBD fetch. Audit #2 recomputes the fingerprint and
**aborts** if the eligible population no longer matches the manifest — that abort is a
feature, not a failure. If it ever fires, the population drifted; follow the defect policy
below rather than editing the manifest.

## Defect policy

**Operational defects** (capture/grading/identity/integrity-monitoring) — fix normally.

**Closed-audit defects** (wrong population, wrong weighting, fingerprint failure, calculation
error, eligibility mistake) — a closed audit may **not** be quietly patched. The only path is:

```
documented defect -> result INVALIDATED -> governed review -> possible reauthorization -> possible rerun
```

Never `fix -> quiet rerun -> keep conclusion`. A closed audit reopens only through the
governance process.

## Starting Audit #3

No candidate is authorized. Coaching Continuity, Situational (rest/travel), Line-value, and
any Team Form v2 variant each require the full gate:

```
new mechanism statement -> preregistration -> adversarial review -> freeze -> authorization -> execution
```

Until a gate opens: **stop, archive, operate, wait.**
