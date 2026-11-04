"""Run an offline QC with Python networking blocked.

    py -3 qc_offline.py qc_something.py [args...]

The QC runs in a Python child process with services.qc_no_network installed, and so does any
PYTHON process it starts that inherits the environment: a non-loopback connection or DNS lookup
made through Python's socket module raises NetworkBlocked and the QC fails loudly. Non-Python
subprocesses (curl, aws, git, ...) are NOT blocked -- see services/qc_no_network.py. A QC that
declares `REQUIRES_NETWORK = True` at module level is refused up front (exit 3, NOT RUN) rather
than started -- it is not an offline QC. Exit code is otherwise the QC's own.

Use this for every QC run during development/review: the 2026-11-01 class of accident (a Python QC
reaching the live Odds API while run as if offline) then fails closed instead of making the call.
"""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

from services.qc_no_network import child_env

NOT_RUN = 3


def requires_network(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == 'REQUIRES_NETWORK' for t in node.targets):
            return isinstance(node.value, ast.Constant) and node.value.value is True
    return False


def main(argv) -> int:
    if not argv:
        print(__doc__)
        return 2
    script = Path(argv[0])
    if not script.is_file():
        print(f'qc_offline: no such script {script}')
        return 2
    if requires_network(script):
        print(f'NOT RUN: {script.name} declares REQUIRES_NETWORK = True (not an offline QC)')
        return NOT_RUN
    return subprocess.call([sys.executable, str(script), *argv[1:]], env=child_env())


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
