"""QC runtime isolation (Linux gate defect 1, 2026-11-04).

A QC that can reach an NBA publisher / lock / run receipt must never resolve the production runtime
(`/opt/bankrollkings-runtime` on POSIX, the in-repo runtime dir on Windows). `isolate_runtime()` gives the QC
process -- and every child it starts, which inherit the environment -- a per-run 0700 temp runtime under a
`qc_runtime_*` directory, restores the previous value and removes the directory at exit.

Idempotent across processes: when BK_RUNTIME_DIR already points inside a `qc_*` temp directory (a parent QC
set it, or a QC deliberately set its own per-child runtime) it is kept; any other value -- including the
production default -- is replaced.

The matching hard guard lives in services/nba_lines_publisher.runtime_root(): a QC process (run under
qc_offline.py, or whose main script is a qc_*.py) whose runtime is not inside a qc_* temp dir is REFUSED.
`qc_runtime_isolation.py` statically proves every QC that can reach these paths calls isolate_runtime().
"""
from __future__ import annotations

import atexit
import os
import shutil
import tempfile
from pathlib import Path

ENV = "BK_RUNTIME_DIR"


def _in_qc_temp(value: str) -> bool:
    if not value:
        return False
    try:
        from services.nba_lines_publisher import _qc_temp_root
        return _qc_temp_root(Path(value)) is not None
    except Exception:
        return False


def isolate_runtime() -> Path:
    current = os.environ.get(ENV, "")
    if _in_qc_temp(current):
        return Path(current)
    d = tempfile.mkdtemp(prefix="qc_runtime_")
    try:
        os.chmod(d, 0o700)
    except OSError:
        pass
    os.environ[ENV] = d

    def _restore():
        if current:
            os.environ[ENV] = current
        else:
            os.environ.pop(ENV, None)
        shutil.rmtree(d, ignore_errors=True)
    atexit.register(_restore)
    return Path(d)
