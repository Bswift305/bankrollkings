from __future__ import annotations

import os
from pathlib import Path


def load_local_env(base_dir: Path | str) -> dict[str, str]:
    """
    Lightweight .env loader.

    Loads `.env` first, then `.env.local` so local overrides win.
    `.env` behaves like a default source, while `.env.local` is treated as
    the machine-specific override and will replace an existing environment
    variable when present.
    """
    root = Path(base_dir).resolve()
    loaded: dict[str, str] = {}

    for name in (".env", ".env.local"):
        path = root / name
        if not path.exists():
            continue
        force_override = name == ".env.local"
        for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if not key:
                continue
            if force_override or not os.environ.get(key):
                os.environ[key] = value
            loaded[key] = value
    return loaded
