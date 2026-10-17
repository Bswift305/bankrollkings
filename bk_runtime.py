"""Runtime-data resolver for regenerable outputs that must live OUTSIDE the git checkout.

Why: prod refresh jobs write regenerable JSON; when those files are git-tracked, the deploy's pre-pull
clean reverts them to the committed snapshot and silently un-freshes prod (the CFB `cfb_line_moves.json`
Sept-27 regression). Runtime outputs therefore write to a private runtime directory, never into the
tracked `data/scenarios/` (see docs/cfb_runtime_data_corrective.md).

Rules (frozen):
  * Production writes ONLY under `BK_RUNTIME_DIR`. Local dev defaults to the gitignored
    `.runtime/generated/` -- never `data/scenarios/`.
  * A committed `data/scenarios/` copy is read ONLY for names NOT classified live-authoritative
    (i.e. genuine seeds/research artifacts). A live-authoritative runtime dataset returns None when its
    runtime copy is absent, so the consumer FAILS CLOSED (shows unavailable/stale) rather than silently
    serving a bundled stale seed.
  * Publishing is atomic (temp file in the same dir + os.replace, fsynced) so a partial write is never
    readable and a failed write preserves the prior runtime version.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
_TRACKED_SCENARIOS = BASE_DIR / "data" / "scenarios"   # committed SEEDS only -- never a write target

# Exactly-classified CFB runtime-authoritative outputs (daily refresh_cfb_data.py lane). These are
# LIVE: no committed-seed fallback -- absent runtime copy -> None -> consumer fails closed. Keep this
# set exact; the NFL runtime files are a SEPARATE later migration and are not listed here.
CFB_RUNTIME_FILES = frozenset({
    "cfb_line_moves.json", "cfb_2026_results.json", "cfb_2026_ats.json", "cfb_ats_streaks.json",
    "cfb_rankings.json", "cfb_coaches_2026.json", "cfb_key_numbers.json", "cfb_pace.json",
    "cfb_weather.json",
})


def runtime_dir() -> Path:
    """The private runtime base. `BK_RUNTIME_DIR` on prod (outside the checkout); the gitignored
    `.runtime/generated/` locally. NEVER `data/scenarios/`."""
    env = (os.environ.get("BK_RUNTIME_DIR") or "").strip()
    return Path(env) if env else (BASE_DIR / ".runtime" / "generated")


def scenario_write_dir() -> Path:
    d = runtime_dir() / "scenarios"
    d.mkdir(parents=True, exist_ok=True)
    return d


def scenario_write_path(name: str) -> Path:
    """Where a runtime refresh WRITES `name`. Always the runtime dir; never the tracked tree."""
    return scenario_write_dir() / name


def scenario_read_path(name: str) -> Path:
    """Resolve `name` for READING. ALWAYS returns a Path (callers test `.exists()` / catch open errors):
      * the runtime copy if it exists (wins);
      * else, for a live-authoritative CFB runtime file, the (non-existent) runtime path -- so the caller
        fails closed and NEVER falls back to a stale committed seed;
      * else the committed `data/scenarios/` seed path (for genuine seeds/research artifacts)."""
    rp = runtime_dir() / "scenarios" / name
    if rp.exists():
        return rp
    if name in CFB_RUNTIME_FILES:
        return rp                       # non-existent -> fail closed, no stale-seed fallback
    return _TRACKED_SCENARIOS / name    # seed (may or may not exist)


def read_json(name: str, default=None):
    """Parsed JSON for `name` via scenario_read_path, or `default` when missing/unreadable."""
    try:
        with open(scenario_read_path(name), "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError, TypeError):
        return default


def scenario_source_mtime(name: str) -> float:
    """mtime of the resolved read path (0 when absent). For cache-key/signature use."""
    try:
        return os.path.getmtime(scenario_read_path(name))
    except OSError:
        return 0.0


def write_csv_atomic(df, path):
    """Write a DataFrame to `path` atomically: temp file in the same directory, fsync, os.replace -- so a
    partial write is never observed and a failure leaves the prior file intact."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="." + path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            df.to_csv(fh, index=False)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def cfb_game_id(value):
    """Canonical CFBD game-id serialization -- the ONE parser used by the manifest, history, grader, sync
    and diagnostics so CSV type inference (123 vs '123' vs 123.0 vs '00123') never splits an identity.

    CFBD ids are POSITIVE DECIMAL INTEGERS. Emits one canonical string (leading zeros stripped):
        123, 123.0, '123', '00123', '123.0'  ->  '123'
    REJECTS (returns None): zero/negative, fractional, scientific notation, overflow (>= 2**63), null,
    empty, 'nan'/'none'/'null', Boolean, and any malformed/non-numeric value. A rejected id is ineligible
    for authoritative synchronization."""
    import math
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        iv = value
    elif isinstance(value, float):
        if math.isnan(value) or math.isinf(value) or value != int(value) or abs(value) >= (1 << 53):
            return None
        iv = int(value)
    else:
        s = str(value).strip()
        if not s or s.lower() in ('nan', 'none', 'null') or 'e' in s.lower():
            return None                       # empty / sentinel / scientific notation -> reject
        if s.isdigit():                       # unsigned integer (strips leading zeros via int())
            iv = int(s)
        else:
            try:                              # tolerate a trailing '.0' from a float-typed CSV column
                f = float(s)
            except ValueError:
                return None
            if math.isnan(f) or f != int(f) or abs(f) >= (1 << 53):
                return None
            iv = int(f)
    if iv <= 0 or iv >= (1 << 63):            # positive, non-overflow
        return None
    return str(iv)


def publish_json(name: str, obj) -> Path:
    """Atomically publish `obj` (a dict/list, or a pre-serialized str) to the runtime dir. Temp file in
    the same directory + fsync + os.replace, so a partial write is never visible and a failed write
    leaves the prior runtime version intact."""
    dest = scenario_write_path(name)
    fd, tmp = tempfile.mkstemp(prefix="." + name + ".", suffix=".tmp", dir=str(dest.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            if isinstance(obj, str):
                fh.write(obj)
            else:
                json.dump(obj, fh)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, dest)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
    return dest
