"""Daily backup of Bankroll Kings' irreplaceable data.

What it protects: data/tracking/ -- users, subscriptions, parlay/bet logs,
Elite alert tracker, etc. (Everything else is either code (in git) or
regenerable from the daily refresh.)

Where it writes: a backup dir on a DIFFERENT volume than the data. The app +
data live on the 50 GB volume mounted at /opt/bankrollkings; this writes to
/home/ubuntu/bk-backups, which is on the separate OS root volume. So if the
data volume fails (or a file gets corrupted/deleted), the backup survives and
restore is instant.

This is the FAST, fine-grained layer. Full-disk, off-instance disaster recovery
is covered separately by AWS Data Lifecycle Manager EBS snapshots.

Rotation: keeps the most recent BACKUP_KEEP archives (default 14).
Stdlib-only. Exits non-zero on a real failure so a timer OnFailure hook (or the
health watchdog) can surface it.

Usage:
  python backup_data.py            # create today's backup + rotate
  python backup_data.py --list     # list existing backups
"""

from __future__ import annotations

import os
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
SOURCE = BASE_DIR / "data" / "tracking"
BACKUP_DIR = Path(os.environ.get("BACKUP_DIR", str(Path.home() / "bk-backups")))
KEEP = int(os.environ.get("BACKUP_KEEP", "14"))
PREFIX = "bk-tracking-"


def _list_backups() -> list[Path]:
    if not BACKUP_DIR.exists():
        return []
    return sorted(BACKUP_DIR.glob(f"{PREFIX}*.tar.gz"))


def _rotate() -> None:
    backups = _list_backups()
    excess = len(backups) - KEEP
    for old in backups[:max(0, excess)]:
        try:
            old.unlink()
            print(f"[backup] rotated out {old.name}")
        except Exception as exc:
            print(f"[backup] could not remove {old.name}: {exc}")


def _verify(archive: Path) -> int:
    """Open the archive and count members to confirm it is a valid tarball."""
    with tarfile.open(archive, "r:gz") as tf:
        return len(tf.getnames())


def main() -> int:
    if "--list" in sys.argv[1:]:
        for b in _list_backups():
            size = b.stat().st_size / 1024.0
            print(f"  {b.name}\t{size:,.0f} KB")
        return 0

    if not SOURCE.exists():
        print(f"[backup] FAIL: source {SOURCE} does not exist")
        return 1

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    archive = BACKUP_DIR / f"{PREFIX}{stamp}.tar.gz"
    tmp = archive.with_suffix(".tar.gz.partial")

    try:
        with tarfile.open(tmp, "w:gz") as tf:
            tf.add(SOURCE, arcname="tracking")
        # Atomic-ish: only promote the partial once it is fully written.
        tmp.replace(archive)
    except Exception as exc:
        print(f"[backup] FAIL: could not create archive: {exc}")
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        return 1

    try:
        count = _verify(archive)
    except Exception as exc:
        print(f"[backup] FAIL: archive verification failed: {exc}")
        return 1

    size_kb = archive.stat().st_size / 1024.0
    print(f"[backup] OK {archive.name} ({size_kb:,.0f} KB, {count} entries) -> {BACKUP_DIR}")
    _rotate()
    print(f"[backup] {len(_list_backups())} backups retained (keep={KEEP})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
