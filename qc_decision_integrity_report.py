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

Determinism: the report contains no wall-clock time; all lists are sorted; execution
is anchored to the repository root (resolved from this file), so the commit and the
scanned tree are identical no matter which working directory the command is launched
from. This slice is strictly INFORMATIONAL: the runner ALWAYS exits 0 and records
`status: fail` when a check fails. A blocking mode is intentionally NOT implemented
here (it belongs to a separately-authorized slice).

Usage:
    python qc_decision_integrity_report.py            # prints JSON, always exit 0
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import qc_decision_receipts
import qc_decision_validators
import services.decision_receipts as dr
import services.decision_validators as dv
import services.nfl_ats_fixtures as fx

REPORT_SCHEMA_VERSION = "1.0"

# Anchor every path to the repository root (this file's directory), NOT the caller's
# working directory — so commit and scan are identical from any cwd.
REPO_ROOT = Path(__file__).resolve().parent

# The only modules permitted to import the receipt package (pre-production boundary),
# as repo-relative forward-slash paths.
_RECEIPT_MODULES = frozenset({"decision_receipts", "decision_validators", "nfl_ats_fixtures"})
_ALLOWED_IMPORTERS = frozenset({
    "services/decision_receipts.py",
    "services/decision_validators.py",
    "services/nfl_ats_fixtures.py",
    "qc_decision_receipts.py",
    "qc_decision_validators.py",
    "qc_decision_integrity_report.py",
})
_HEAVY = {"pandas", "numpy", "flask", "app", "requests", "openpyxl", "nba_api", "pybaseball"}


def _git_commit() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                             timeout=10, cwd=str(REPO_ROOT))
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def imports_receipt_package(source: str) -> bool:
    """AST-based (syntax-aware) detection of an import of the receipt package, covering
    every form: `import services.decision_receipts[ as x]`, `from services.X import y`,
    and `from services import decision_receipts`. Raises SyntaxError on unparsable
    source (callers treat that as a scan error, never a silent pass)."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                parts = a.name.split(".")
                if len(parts) >= 2 and parts[0] == "services" and parts[1] in _RECEIPT_MODULES:
                    return True
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            parts = mod.split(".")
            if parts and parts[0] == "services":
                if len(parts) >= 2 and parts[1] in _RECEIPT_MODULES:
                    return True
                if mod == "services" and any(a.name in _RECEIPT_MODULES for a in node.names):
                    return True
    return False


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


def _prohibited_production_imports(root=None) -> dict:
    """Fail-closed, AST-based scan. A .py file that imports the receipt package and is
    not allowlisted is `offending`; a .py file that cannot be read or parsed is a
    `scan_error` (never silently skipped). The guard passes only when BOTH are empty."""
    root = REPO_ROOT if root is None else Path(root)
    offending, scan_errors = [], []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in
                       (".git", "__pycache__", "node_modules", ".claude", "venv", "_attic")]
        for fn in filenames:
            if not fn.endswith(".py"):
                continue
            path = Path(dirpath) / fn
            rel = path.relative_to(root).as_posix()
            if rel in _ALLOWED_IMPORTERS:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except Exception as exc:
                scan_errors.append(f"{rel}: unreadable ({type(exc).__name__})")
                continue
            try:
                hit = imports_receipt_package(text)
            except SyntaxError as exc:
                scan_errors.append(f"{rel}: unparsable ({exc.__class__.__name__})")
                continue
            if hit:
                offending.append(rel)
    offending.sort()
    scan_errors.sort()
    return {"offending": offending, "scan_errors": scan_errors,
            "pass": not offending and not scan_errors}


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
    report = build_report()
    print(json.dumps(report, sort_keys=True, indent=2))
    # This slice is strictly informational: ALWAYS exit 0. `status` carries pass/fail.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
