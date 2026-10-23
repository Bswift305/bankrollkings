"""QC: services/atomic_csv.atomic_write_csv -- atomic + validated artifact publish (Oct 23 recovery gate).

Proves: a successful publish replaces atomically and leaves no temp; a validation failure (missing column
/ below min_rows) RAISES and leaves the existing authoritative file byte-for-byte intact (last-known-good
preserved); empty is allowed only when min_rows=0; no .tmp files are ever left behind. No network/app.
"""
from __future__ import annotations

import glob
import os
import tempfile
from pathlib import Path

import pandas as pd

from services.atomic_csv import CsvValidationError, atomic_write_csv


def run_qc():
    issues, notes = [], []
    d = Path(tempfile.mkdtemp(prefix="qc_atomic_"))
    target = d / "feed.csv"

    # (1) first publish writes
    atomic_write_csv(pd.DataFrame([{"Away": "A", "Home": "B", "Line": 1}]), target,
                     required_cols=["Away", "Home"], min_rows=1)
    good = target.read_text(encoding="utf-8")
    if "A" not in good:
        issues.append("first atomic publish did not write expected content")
    else:
        notes.append("atomic publish wrote the file")

    # (2) validation failure preserves last-known-good + raises (missing column)
    try:
        atomic_write_csv(pd.DataFrame([{"Wrong": "x"}]), target, required_cols=["Away", "Home"])
        issues.append("missing-column write did NOT raise")
    except CsvValidationError:
        if target.read_text(encoding="utf-8") != good:
            issues.append("missing-column write CORRUPTED the authoritative file (not preserved)")
        else:
            notes.append("missing-column write raised + preserved last-known-good")

    # (3) below-min_rows preserves + raises
    try:
        atomic_write_csv(pd.DataFrame(columns=["Away", "Home"]), target, required_cols=["Away", "Home"], min_rows=1)
        issues.append("below-min_rows write did NOT raise")
    except CsvValidationError:
        if target.read_text(encoding="utf-8") != good:
            issues.append("below-min_rows write corrupted the authoritative file")
        else:
            notes.append("below-min_rows write raised + preserved last-known-good")

    # (4) None refuses
    try:
        atomic_write_csv(None, target)
        issues.append("None write did NOT raise")
    except CsvValidationError:
        notes.append("None write refused")

    # (5) empty allowed when min_rows=0
    atomic_write_csv(pd.DataFrame(columns=["Away", "Home"]), d / "empty.csv", min_rows=0)
    if not (d / "empty.csv").exists():
        issues.append("empty publish (min_rows=0) did not write")
    else:
        notes.append("empty publish allowed when min_rows=0")

    # (6) no temp files left anywhere
    leftovers = glob.glob(str(d / "*.tmp"))
    if leftovers:
        issues.append(f"temp files leaked: {leftovers}")
    else:
        notes.append("no .tmp files left behind")

    for f in d.glob("*"):
        try:
            f.unlink()
        except OSError:
            pass
    try:
        os.rmdir(d)
    except OSError:
        pass

    if not issues:
        notes.append("atomic_write_csv verified (atomic replace, validated, last-known-good preserved)")
    return {"issues": issues, "notes": notes}


def main() -> int:
    report = run_qc()
    print("=" * 60)
    print("BANKROLL KINGS ATOMIC CSV PUBLISH QC")
    print("=" * 60)
    for n in report["notes"]:
        print(f"[NOTE] {n}")
    if report["notes"]:
        print()
    if not report["issues"]:
        print("Atomic CSV publish verified.")
        return 0
    for m in report["issues"]:
        print(f"[FAIL] {m}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
