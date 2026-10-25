"""QC: entity-link P0 -- schedule team links are gate-aware (not raw /team/<name>), and the WNBA
dashboard sim-reads player is an entity_anchor (2026-10-25).

- schedule.html (NBA schedule) must route team cells through team_url('nba', ...) so they are sport-scoped
  and gate-aware (NBA gated -> /tools/nba-team cleared market page; unknown team -> plain text), NEVER a
  raw sport-less /team/<name> link that bypasses the gate.
- wnba_dashboard "Top Simulation Reads" player renders via entity_anchor('player','wnba',...).
Both templates must parse.
"""
from __future__ import annotations

import re

import app
from services.qc_auth import isolated_owner_client


def run_qc() -> dict:
    failures, checks = [], []

    # 1) both templates parse (catches {% set %} / syntax errors)
    for t in ("schedule.html", "wnba_dashboard.html"):
        try:
            app.app.jinja_env.get_template(t)
            checks.append(f"{t} parses")
        except Exception as exc:
            failures.append(f"{t} parse error: {type(exc).__name__}: {exc}")

    # 2) source contract: schedule.html uses team_url + has no raw sport-less /team/<name> link
    sched = app.app.jinja_env.loader.get_source(app.app.jinja_env, "schedule.html")[0]
    if "team_url('nba'" in sched:
        checks.append("schedule.html routes team cells through team_url('nba', ...)")
    else:
        failures.append("schedule.html does not use team_url('nba', ...)")
    raw_src = re.findall(r'href="/team/\{\{', sched)
    if raw_src:
        failures.append(f"schedule.html still has raw sport-less /team/ link(s): {len(raw_src)}")
    else:
        checks.append("schedule.html has no raw sport-less /team/<name> link")

    wnba = app.app.jinja_env.loader.get_source(app.app.jinja_env, "wnba_dashboard.html")[0]
    if "entity_anchor('player', 'wnba', row.player" in wnba:
        checks.append("wnba_dashboard sim-reads player uses entity_anchor('player','wnba',...)")
    else:
        failures.append("wnba_dashboard sim-reads player is not an entity_anchor")

    # 3) render smoke: /schedule returns 200 and the RENDERED html carries no raw sport-less /team/ link
    with isolated_owner_client() as c:
        r = c.get("/schedule", follow_redirects=True)
        if r.status_code != 200:
            failures.append(f"/schedule returned {r.status_code}")
        else:
            checks.append("/schedule renders 200 (owner)")
            html = r.get_data(as_text=True)
            raw = re.findall(r'href="/team/[^"?]+"', html)   # sport-less /team/<name> with no ?sport=
            if raw:
                failures.append(f"/schedule rendered {len(raw)} raw sport-less /team/ link(s): {raw[:3]}")
            else:
                checks.append("/schedule rendered html has no raw sport-less /team/ link")

    return {"clean": not failures, "checks": checks, "failures": failures}


def main() -> int:
    r = run_qc()
    print("=" * 64)
    print("ENTITY-LINK QC -- schedule team links + WNBA sim-reads player")
    print("=" * 64)
    for c in r["checks"]:
        print(f"  [ok] {c}")
    for f in r["failures"]:
        print(f"  [FAIL] {f}")
    print(f"Clean: {r['clean']}")
    return 0 if r["clean"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
