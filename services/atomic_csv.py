"""Atomic, validated CSV publish.

Write to a temp file in the SAME directory, validate it, then os.replace() onto the authoritative path.
os.replace is atomic on one filesystem, so a reader never sees a partial/half-written file and a crash
mid-write leaves the previous authoritative artifact intact. Validation (required columns / min rows /
non-zero) runs on the TEMP before the replace, so a failed validation **preserves last-known-good** and
raises instead of publishing a bad file.

Incident 2026-10-23: the Odds fetchers published with a direct `df.to_csv(authoritative_path)`, which is
neither atomic (a crash leaves a truncated file) nor validated. Route every authoritative artifact write
through here. Stdlib + pandas only; no app import.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path


class CsvValidationError(Exception):
    """Raised when the about-to-publish CSV fails validation; the authoritative file is left untouched."""


def _check_frame(df, path, min_rows=0, required_cols=None):
    if df is None:
        raise CsvValidationError(f"refusing to publish None to {path.name}")
    cols = list(df.columns) if hasattr(df, "columns") else []
    if required_cols:
        missing = [c for c in required_cols if c not in cols]
        if missing:
            raise CsvValidationError(f"{path.name}: missing required columns {missing}")
    if min_rows and len(df) < min_rows:
        raise CsvValidationError(f"{path.name}: {len(df)} rows < required minimum {min_rows}")


def atomic_write_csv_set(items):
    """Publish SEVERAL related CSVs (e.g. a feed + its mirrors) as one unit, as far as a filesystem allows.

    items: iterable of (df, path, opts) where opts may carry index / min_rows / required_cols plus any
    to_csv kwargs. EVERY frame is validated and staged to a same-directory temp file FIRST; only when all
    temps are staged and non-zero is each os.replace'd onto its target. Any validation/staging failure
    raises CsvValidationError with EVERY target left byte-identical (no partial set). Returns the paths."""
    staged = []
    try:
        for df, path, opts in items:
            path = Path(path)
            kw = dict(opts or {})
            index = kw.pop("index", False)
            _check_frame(df, path, kw.pop("min_rows", 0), kw.pop("required_cols", None))
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=path.stem + ".", suffix=".tmp", dir=str(path.parent))
            os.close(fd)
            staged.append([tmp, path])
            df.to_csv(tmp, index=index, **kw)
            if os.path.getsize(tmp) == 0:
                raise CsvValidationError(f"{path.name}: wrote a zero-byte temp file; not replacing")
        for entry in staged:
            os.replace(entry[0], entry[1])   # atomic per file on the same filesystem
            entry[0] = None
        return [entry[1] for entry in staged]
    finally:
        for entry in staged:
            if entry[0] and os.path.exists(entry[0]):
                try:
                    os.remove(entry[0])
                except OSError:
                    pass


def atomic_write_csv(df, path, index=False, min_rows=0, required_cols=None, **to_csv_kwargs):
    """Publish `df` to `path` atomically after validation. Returns the Path on success; raises
    CsvValidationError (leaving any existing `path` intact) on a validation failure.

    - required_cols: every name must be present (schema guard).
    - min_rows: refuse to publish fewer than this many rows (0 = empty allowed, e.g. a no-games slate).
    - the temp file must be non-zero on disk before the replace.
    """
    path = Path(path)
    if df is None:
        raise CsvValidationError(f"refusing to publish None to {path.name}")
    cols = list(df.columns) if hasattr(df, "columns") else []
    if required_cols:
        missing = [c for c in required_cols if c not in cols]
        if missing:
            raise CsvValidationError(f"{path.name}: missing required columns {missing}")
    if min_rows and len(df) < min_rows:
        raise CsvValidationError(f"{path.name}: {len(df)} rows < required minimum {min_rows}")

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.stem + ".", suffix=".tmp", dir=str(path.parent))
    try:
        os.close(fd)
        df.to_csv(tmp, index=index, **to_csv_kwargs)
        if os.path.getsize(tmp) == 0:
            raise CsvValidationError(f"{path.name}: wrote a zero-byte temp file; not replacing")
        os.replace(tmp, path)   # atomic on the same filesystem
        tmp = None
        return path
    finally:
        if tmp and os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
