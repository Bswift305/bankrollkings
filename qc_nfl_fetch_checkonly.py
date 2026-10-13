"""QC: fetch_nfl_player_week --check-only distinguishes missing vs unreadable data.

Regression guard for the diagnostic-hardening fix. Before it, --check-only swallowed ANY read
failure into "week 0", so a healthy production parquet an operator merely lacked permission to read
(e.g. running as ssm-user instead of its owner ubuntu) looked identical to missing data -- inviting
a false "production data is gone" diagnosis. Now:

  missing file   -> status 'missing', exit 2 (legitimately behind / no data yet)
  readable file  -> status 'ok',      exit 0 when it holds the completed week, 2 when behind
  unreadable file-> status 'unreadable', exit 3 with an explicit "cannot read / run as owner" message

A corrupt (non-parquet) file at the expected path reproduces the unreadable branch portably (the
same code path a permission error takes), without needing OS-specific chmod. Exits 0 when the
exit-code contract holds, 1 otherwise.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pandas as pd

import fetch_nfl_player_week as f

SEASON = 2026


def _parquet(tmp: Path, weeks):
    pd.DataFrame({'week': weeks, 'player_display_name': ['x'] * len(weeks)}).to_parquet(
        tmp / f'_nflverse_stats_{SEASON}.parquet', index=False)


def run_qc():
    issues, notes = [], []
    saved_out = f.OUT_DIR
    try:
        # --- missing file: legitimately behind, never 'unreadable' -------------------------
        with tempfile.TemporaryDirectory() as td:
            f.OUT_DIR = Path(td)
            status, info = f._on_disk_week(SEASON)
            if status != 'missing' or info != 0:
                issues.append(f"missing: _on_disk_week -> ({status},{info}) (want ('missing',0))")
            code, msg = f._check_only_result(SEASON, 4)
            if code != 2:
                issues.append(f"missing: exit {code} (want 2) -- {msg}")
            elif 'week 0' not in msg:
                issues.append(f"missing: message should name week 0 -- {msg!r}")
            else:
                notes.append("missing file -> exit 2, reported as week 0 (behind)")

        # --- readable file: correct week, correct comparison -------------------------------
        with tempfile.TemporaryDirectory() as td:
            f.OUT_DIR = Path(td)
            _parquet(f.OUT_DIR, [1, 2, 3, 4, 5])
            status, info = f._on_disk_week(SEASON)
            if status != 'ok' or info != 5:
                issues.append(f"ok: _on_disk_week -> ({status},{info}) (want ('ok',5))")
            c_ok, _ = f._check_only_result(SEASON, 4)
            c_behind, _ = f._check_only_result(SEASON, 6)
            c_noanchor, m_na = f._check_only_result(SEASON, None)
            if c_ok != 0:
                issues.append(f"ok: week5 vs completed4 -> exit {c_ok} (want 0)")
            if c_behind != 2:
                issues.append(f"ok: week5 vs completed6 -> exit {c_behind} (want 2)")
            if c_noanchor != 0:
                issues.append(f"ok: no anchor -> exit {c_noanchor} (want 0) -- {m_na}")
            if not issues:
                notes.append("readable file -> exit 0 when current, 2 when behind, 0 with no anchor")

        # --- unreadable file: DISTINCT error, not a false week 0 --------------------------
        with tempfile.TemporaryDirectory() as td:
            f.OUT_DIR = Path(td)
            # A non-parquet file at the expected path: exists, but pd.read_parquet raises --
            # the same branch a permission error takes.
            (f.OUT_DIR / f'_nflverse_stats_{SEASON}.parquet').write_bytes(b'not a parquet file')
            status, info = f._on_disk_week(SEASON)
            if status != 'unreadable':
                issues.append(f"unreadable: _on_disk_week status {status!r} (want 'unreadable')")
            code, msg = f._check_only_result(SEASON, 4)
            if code != 3:
                issues.append(f"unreadable: exit {code} (want 3) -- the old code returned 2 via a fake week 0")
            elif 'week 0' in msg.lower():
                issues.append(f"unreadable: must NOT claim week 0 -- {msg!r}")
            elif 'cannot read' not in msg.lower():
                issues.append(f"unreadable: message should be explicit about the read failure -- {msg!r}")
            else:
                notes.append("unreadable file -> exit 3, explicit error, never a false week 0")
    finally:
        f.OUT_DIR = saved_out
    return {'issues': issues, 'notes': notes}


def main() -> int:
    report = run_qc()
    print("=" * 60)
    print("BANKROLL KINGS NFL FETCH --check-only QC")
    print("=" * 60)
    for note in report["notes"]:
        print(f"[NOTE] {note}")
    if report["notes"]:
        print()
    if not report["issues"]:
        print("No --check-only diagnostic issues detected.")
        return 0
    for msg in report["issues"]:
        print(f"[FAIL] {msg}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
