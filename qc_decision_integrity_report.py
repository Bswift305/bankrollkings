"""Decision Integrity — report-only CI evidence (Phase 2B, Slice 3).

Produces a DETERMINISTIC, machine-readable (JSON) report by RUNNING THE EXISTING
Slice-1 and Slice-2 suites unchanged. It adds NO validation logic of its own — it
calls each suite's `run_qc()` and summarizes the results, then adds two static
guardrail checks (import purity + prohibited production imports).

Boundaries (Slice 3): informational / NON-BLOCKING (exit 0 by default). It reads
only source files for the prohibited-import scan; it does NOT touch live NFL ATS
data or builders, does not enforce anything at runtime, defines no feature flag,
persists nothing, exposes no route/template, and performs no production execution.
`decision_time`, transitions, and the fail-closed runtime assertion are out of scope.

Determinism: the report contains no wall-clock time; all lists are sorted; the only
environment-derived value is the git commit (fixed for a given checkout). Pass
`--strict` to exit non-zero on failure (reserved for a FUTURE blocking slice; the
default stays non-blocking this slice).

Usage:
    python qc_decision_integrity_report.py            # prints JSON, exit 0
    python qc_decision_integrity_report.py --strict    # exit 1 if any check failed
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys

import qc_decision_receipts
import qc_decision_validators
import services.decision_receipts as dr
import services.decision_validators as dv
import services.nfl_ats_fixtures as fx

REPORT_SCHEMA_VERSION = "1.0"

# The only modules permitted to import the receipt package (pre-production boundary).
_RECEIPT_MODULES = ("decision_receipts", "decision_validators", "nfl_ats_fixtures")
_ALLOWED_IMPORTERS = frozenset({
    os.path.join("services", "decision_receipts.py"),
    os.path.join("services", "decision_validators.py"),
    os.path.join("services", "nfl_ats_fixtures.py"),
    "qc_decision_receipts.py",
    "qc_decision_validators.py",
    "qc_decision_integrity_report.py",
})
_HEAVY = {"pandas", "numpy", "flask", "app", "requests", "openpyxl", "nba_api", "pybaseball"}
_IMPORT_RE = re.compile(
    r"^\s*(?:from\s+services\.(decision_receipts|decision_validators|nfl_ats_fixtures)\b"
    r"|import\s+services\.(decision_receipts|decision_validators|nfl_ats_fixtures)\b)", re.M)


def _git_commit() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                             timeout=10)
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _suite(name: str, module) -> dict:
    r = module.run_qc()
    passed, failed = len(r["checks"]), len(r["failures"])
    return {
        "name": name, "module": module.__name__,
        "passed": passed, "failed": failed, "total": passed + failed,
        "clean": bool(r["clean"]), "failures": sorted(r["failures"]),
    }


def _import_purity() -> dict:
    # What heavy deps are pulled in by importing the receipt package?
    heavy = sorted(m for m in sys.modules if m.split(".")[0] in _HEAVY)
    return {"heavy_imports": heavy, "pass": not heavy}


def _prohibited_production_imports(root: str = ".") -> dict:
    offending = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in
                       (".git", "__pycache__", "node_modules", ".claude", "venv", "_attic")]
        for fn in filenames:
            if not fn.endswith(".py"):
                continue
            path = os.path.normpath(os.path.join(dirpath, fn))
            rel = os.path.relpath(path, root)
            if rel.replace("\\", "/") in {p.replace("\\", "/") for p in _ALLOWED_IMPORTERS}:
                continue
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as fh:
                    text = fh.read()
            except Exception:
                continue
            if _IMPORT_RE.search(text):
                offending.append(rel.replace("\\", "/"))
    offending.sort()
    return {"offending": offending, "pass": not offending}


def build_report() -> dict:
    suites = [
        _suite("slice1_contract_library", qc_decision_receipts),
        _suite("slice2_validator_suite", qc_decision_validators),
    ]
    totals = {
        "passed": sum(s["passed"] for s in suites),
        "failed": sum(s["failed"] for s in suites),
        "total": sum(s["total"] for s in suites),
        "clean": all(s["clean"] for s in suites),
    }
    purity = _import_purity()
    prod = _prohibited_production_imports()
    all_pass = totals["clean"] and purity["pass"] and prod["pass"]
    return {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "commit": _git_commit(),
        "blocking": False,
        "status": "pass" if all_pass else "fail",
        "contract": {"major": dr.CONTRACT_MAJOR, "minor": dr.CONTRACT_MINOR},
        "fixtures": {
            "version": fx.FIXTURES_VERSION,
            "surface": fx.SURFACE,
            "universes": {"board": [fx.UNI_BOARD.grain, fx.UNI_BOARD.id, fx.UNI_BOARD.version],
                          "decision": [fx.UNI_DEC.grain, fx.UNI_DEC.id, fx.UNI_DEC.version]},
            "scenario_receipt_ids": {
                "batch": fx.BATCH_ID, "board": fx.BOARD_ID, "source_health": fx.SH_ID,
                "render": fx.RENDER_ID, "decision": fx.DEC_ID, "correction": fx.CORR_ID,
                "user_safe": fx.USERSAFE_ID},
        },
        "registries": {
            "reason_codes": sorted(dv.REASON_REGISTRY),
            "claim_codes": sorted(dv.CLAIM_REGISTRY),
            "projection_types": sorted(dv.PROJECTION_CLAIMS),
            "health_states": sorted(s.value for s in dr.HealthState),
            "receipt_kinds_supported": sorted(k.value for k in dr.SUPPORTED_RECEIPT_KINDS),
            "receipt_kinds_not_yet_constructed": sorted(k.value for k in dr.NOT_YET_CONSTRUCTED_KINDS),
        },
        "suites": suites,
        "totals": totals,
        "purity": purity,
        "production_imports": prod,
    }


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    strict = "--strict" in argv
    report = build_report()
    print(json.dumps(report, sort_keys=True, indent=2))
    if strict and report["status"] != "pass":
        return 1
    return 0  # informational / non-blocking this slice


if __name__ == "__main__":
    raise SystemExit(main())
