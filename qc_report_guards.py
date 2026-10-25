"""QC: guards for the report-only CI runner (Phase 2B, Slice 3).

Proves the three report truth-model corrections:
  1. execution is anchored to the repo root — running from another working directory
     yields a BYTE-IDENTICAL report;
  2. the production-import scan is AST/syntax-aware (detects every allowed import form)
     and FAILS CLOSED on unreadable/unparsable files;
  3. the runner is strictly informational (always exit 0; no --strict / blocking mode).

Uses throwaway temp directories for the scan fixtures (never the repo tree); the report
module itself remains pure.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

import qc_decision_integrity_report as rep

SCRIPT = Path(rep.__file__).resolve()
REPO_ROOT = rep.REPO_ROOT


def run_qc() -> dict:
    checks, failures = [], []

    def ok(cond, label):
        (checks if cond else failures).append(label)

    # 1) AST detection — every allowed import FORM is detected (positive).
    forms = [
        "import services.decision_receipts",
        "import services.decision_receipts as receipts",
        "from services.decision_receipts import Receipt",
        "from services import decision_receipts",
        "from services.decision_validators import validate_envelope",
        "from services import nfl_ats_fixtures as fx",
    ]
    for src in forms:
        ok(rep.imports_receipt_package(src), f"detects import form: {src!r}")
    # negatives — unrelated imports are NOT flagged.
    for src in ("import os", "from services import something_else",
                "import services.other_module", "from services.other import x"):
        ok(not rep.imports_receipt_package(src), f"ignores unrelated import: {src!r}")

    # 2) scan fails closed + is syntax-aware, on throwaway temp trees.
    with tempfile.TemporaryDirectory() as d:
        p = Path(d)
        (p / "clean.py").write_text("import os\nfrom services import something_else\n", encoding="utf-8")
        r = rep._prohibited_production_imports(p)
        ok(r["pass"] and not r["offending"] and not r["scan_errors"], "clean temp tree passes")

    with tempfile.TemporaryDirectory() as d:
        p = Path(d)
        (p / "leak.py").write_text("from services import decision_receipts\n", encoding="utf-8")
        r = rep._prohibited_production_imports(p)
        ok((not r["pass"]) and "leak.py" in r["offending"],
           "an offending import (from-services form) is reported and fails the guard")

    with tempfile.TemporaryDirectory() as d:
        p = Path(d)
        (p / "broken.py").write_text("def (this is not valid python\n", encoding="utf-8")
        r = rep._prohibited_production_imports(p)
        ok((not r["pass"]) and any("broken.py" in e for e in r["scan_errors"]),
           "an UNPARSABLE file becomes a scan_error and fails the guard (never silent pass)")

    # 3) cross-directory byte identity: report from the repo root vs an unrelated cwd.
    out_root = subprocess.run([sys.executable, str(SCRIPT)], cwd=str(REPO_ROOT),
                              capture_output=True, text=True)
    with tempfile.TemporaryDirectory() as d:
        out_other = subprocess.run([sys.executable, str(SCRIPT)], cwd=d,
                                   capture_output=True, text=True)
    ok(out_root.returncode == 0 and out_other.returncode == 0,
       "runner exits 0 from both the repo root and an unrelated cwd (non-blocking)")
    ok(out_root.stdout == out_other.stdout and out_root.stdout.strip() != "",
       "report is BYTE-IDENTICAL regardless of the working directory")

    # 4) the live report is green and its guards pass.
    report = rep.build_report()
    ok(report["status"] == "pass" and report["totals"] == {"passed": 163, "failed": 0,
       "total": 163, "clean": True}, "live report: status pass, 163/163")
    ok(report["purity"]["pass"] and report["production_imports"]["pass"]
       and not report["production_imports"]["scan_errors"],
       "live report: import-purity + prohibited-import guards pass (no scan errors)")
    ok("--strict" not in Path(SCRIPT).read_text(encoding="utf-8"),
       "runner has no --strict / blocking mode in this slice")

    return {"clean": not failures, "checks": checks, "failures": failures}


def main() -> int:
    r = run_qc()
    print("=" * 72)
    print("DECISION INTEGRITY REPORT-RUNNER GUARDS QC (Phase 2B, Slice 3)")
    print("=" * 72)
    for c in r["checks"]:
        print(f"  [ok] {c}")
    for f in r["failures"]:
        print(f"  [FAIL] {f}")
    print(f"\n{len(r['checks'])} passed, {len(r['failures'])} failed")
    print(f"Clean: {r['clean']}")
    return 0 if r["clean"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
