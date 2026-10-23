"""One-command recovery receipt for a single narrow Odds fetch (incident 2026-10-23).

Wraps ONE narrow fetch so the operator never assembles the receipt by hand. It records the authoritative
artifact BEFORE and AFTER the fetch (content-free: hashes, sizes, row counts, schema fingerprint,
data-through), runs the fetch command, surfaces the fetcher's own quota receipt, and verifies the
atomic-publish + last-known-good-on-failure outcome.

Usage:
  python recover_odds_fetch.py --artifact data/odds/NFL_Odds.csv -- \
      python fetch_game_lines.py --sport americanfootball_nfl --days 2 --expected-cost 12

Everything after `--` is the fetch command, run verbatim. Exits with the fetch's own exit code.
Prints NO row content, no keys, no URLs.
"""
from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def _stat(path: Path):
    """Content-free fingerprint of an artifact: exists, sha256, size, rows, schema fingerprint, data-through."""
    out = {"exists": path.exists(), "sha256": None, "size": None, "rows": None,
           "schema_fp": None, "data_through": None}
    if not path.exists():
        return out
    data = path.read_bytes()
    out["size"] = len(data)
    out["sha256"] = hashlib.sha256(data).hexdigest()[:16]
    try:
        import pandas as pd
        df = pd.read_csv(path)
        out["rows"] = int(len(df))
        cols = list(df.columns)
        out["schema_fp"] = hashlib.sha256(",".join(map(str, cols)).encode()).hexdigest()[:12]
        for tc in ("LastUpdated", "last_update", "SnapshotAt"):
            if tc in cols:
                ts = pd.to_datetime(df[tc], errors="coerce", utc=True, format="mixed").max()
                out["data_through"] = None if ts is None or ts is pd.NaT else str(ts)
                break
    except Exception:
        pass
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="One-command recovery receipt for a narrow Odds fetch.")
    ap.add_argument("--artifact", required=True, help="Authoritative CSV the fetch publishes.")
    ap.add_argument("cmd", nargs=argparse.REMAINDER, help="-- then the fetch command to run verbatim.")
    args = ap.parse_args()
    cmd = args.cmd[1:] if args.cmd and args.cmd[0] == "--" else args.cmd
    if not cmd:
        print("No fetch command given (expected: ... -- python fetch_game_lines.py ...)")
        return 2

    artifact = Path(args.artifact)
    if not artifact.is_absolute():
        artifact = BASE_DIR / artifact

    print("=" * 78)
    print("ODDS NARROW-FETCH RECOVERY RECEIPT")
    print("=" * 78)
    pre = _stat(artifact)
    print(f"artifact: {artifact.relative_to(BASE_DIR) if str(artifact).startswith(str(BASE_DIR)) else artifact}")
    print(f"PRE : exists={pre['exists']} sha={pre['sha256']} size={pre['size']} rows={pre['rows']} "
          f"schema={pre['schema_fp']} data_through={pre['data_through']}")
    print(f"command: {' '.join(cmd)}")

    proc = subprocess.run(cmd, cwd=str(BASE_DIR))
    exit_code = proc.returncode   # the fetcher prints its own QUOTA RECEIPT to stdout above

    post = _stat(artifact)
    print(f"POST: exists={post['exists']} sha={post['sha256']} size={post['size']} rows={post['rows']} "
          f"schema={post['schema_fp']} data_through={post['data_through']}")
    print(f"fetch exit code: {exit_code}")

    changed = pre["sha256"] != post["sha256"]
    if exit_code == 0:
        if changed:
            print("atomic publish  : PUBLISHED (artifact advanced)")
        else:
            print("atomic publish  : no change (exit 0 but artifact unchanged -- e.g. no new lines)")
        if post["data_through"] and pre["data_through"] and post["data_through"] < pre["data_through"]:
            print("WARNING: data_through REGRESSED despite exit 0 -- investigate before accepting.")
    else:
        if changed:
            print("last-known-good : *** VIOLATED *** artifact changed on a FAILED fetch -- investigate.")
        else:
            print("last-known-good : PRESERVED (failed fetch left the prior artifact byte-for-byte)")
    print("=" * 78)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
