"""QC for the governed model-registry firewall and Lookup research metadata."""
from __future__ import annotations

from copy import deepcopy

from services import model_registry as registry


def qc_discovery_has_no_authority():
    entries = registry.research_for_market("nfl", "rushing_yards", "QB")
    ok = len(entries) == 1 and entries[0]["status"] == "Discovery" and not entries[0]["has_authority"]
    return ok, str([(e["model_id"], e["status"], e["has_authority"]) for e in entries])


def qc_market_and_position_isolation():
    rb = registry.research_for_market("nfl", "rushing_yards", "RB")
    passing = registry.research_for_market("nfl", "passing_yards", "QB")
    nba = registry.research_for_market("nba", "rushing_yards", "QB")
    ok = rb == [] and passing == [] and nba == []
    return ok, f"rb={len(rb)} passing={len(passing)} nba={len(nba)}"


def qc_qualified_requires_all_validation():
    base = deepcopy(registry.registry_entries()[0])
    base["status"] = "Qualified"
    incomplete = registry.has_authority(base)
    base["validation"] = {"historical": "passed", "holdout": "passed", "prospective": "passed"}
    complete = registry.has_authority(base)
    ok = not incomplete and complete
    return ok, f"incomplete={incomplete} complete={complete}"


def qc_no_scoring_contract():
    entry = registry.registry_entries()[0]
    forbidden = {"score", "confidence", "weight", "rank", "boost"}
    ok = forbidden.isdisjoint(entry.keys()) and entry["output"] == "contextual alignment only"
    return ok, f"keys={sorted(entry)}"


CHECKS = [
    ("Discovery has no authority", qc_discovery_has_no_authority),
    ("sport × market × position isolation", qc_market_and_position_isolation),
    ("Qualified requires validation", qc_qualified_requires_all_validation),
    ("no hidden scoring contract", qc_no_scoring_contract),
]


def main():
    failures = 0
    for label, fn in CHECKS:
        try:
            ok, detail = fn()
        except Exception as exc:
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        print(f"[{'PASS' if ok else 'FAIL'}] {label}: {detail}")
        failures += int(not ok)
    print(f"Model Registry QC: {len(CHECKS) - failures}/{len(CHECKS)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
