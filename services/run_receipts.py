"""Per-run publisher receipts -- the ONLY source of a governed NBA stage outcome (owner receipt-identity contract,
2026-11-04).

Contract:
  * Every NBA publisher invocation has a run token: the caller's (services/nba_market.ensure_stage passes it in
    STAGE_RUN_ENV) or, for a standalone/manual/batch invocation, one the publisher generates itself
    (ensure_run_token). A token must be SAFE: exactly 32 lowercase hex chars (uuid4().hex); an unsafe value in
    the environment is REJECTED (the publisher refuses to run -- it never falls back to a fresh token, which
    would hide a caller bug).
  * The publisher writes its receipt to <receipt dir>/<token>.<kind>.json: temp file in the same directory
    (O_CREAT|O_EXCL|O_NOFOLLOW, 0600) + fsync + os.replace (bounded retry on a Windows sharing violation only).
    A token's receipt is written once; an existing file for the token is refused (token reuse).
  * The receipt dir is <runtime root>/receipts/nba_stage_runs (BK_RUNTIME_DIR; prod /opt/bankrollkings-runtime),
    created/verified with the v4 lock-location enforcement (0700 on POSIX, no symlink, contained in the runtime
    root). QC may point BK_NBA_RUN_RECEIPT_DIR at a dir inside the runtime root or a qc_* temp dir; anything
    else is refused.
  * A caller that needs the result reads ONLY its own receipt (read_own): missing/unreadable ->
    RUN_RECEIPT_MISSING; a receipt whose stage_run_id is not this token -> RUN_RECEIPT_MISMATCH. The shared
    `_last_nba_*_publish.json` files remain operational history only and never determine a stage outcome.
  * Retention (prune): files older than RETAIN_DAYS are removed, then the oldest beyond RETAIN_MAX_FILES; the
    tokens passed in `protect` (the current run) are never removed.
Pure stdlib; no app import.
"""
from __future__ import annotations

import json
import os
import stat
import time
import uuid
from pathlib import Path

STAGE_RUN_ENV = "BK_NBA_STAGE_RUN_ID"
RECEIPT_DIR_OVERRIDE_ENV = "BK_NBA_RUN_RECEIPT_DIR"     # QC only; contained like the lock overrides
RECEIPT_SUBDIR = Path("receipts") / "nba_stage_runs"
KINDS = ("lines", "props")
RETAIN_DAYS = 14
RETAIN_MAX_FILES = 2000          # ~6 stage runs/day x 2 kinds x 14 days = 168; generous, still bounded
FILE_MODE = 0o600
TMP_ORPHAN_SECONDS = 3600        # a writer's temp file older than this is an orphan (killed writer)

RUN_RECEIPT_MISSING = "RUN_RECEIPT_MISSING"
RUN_RECEIPT_MISMATCH = "RUN_RECEIPT_MISMATCH"
RECEIPT_OK = "OK"


class UnsafeRunToken(ValueError):
    """A run token that is not exactly 32 lowercase hex characters."""


def is_safe_token(token) -> bool:
    return isinstance(token, str) and len(token) == 32 and all(c in "0123456789abcdef" for c in token)


def new_token() -> str:
    return uuid.uuid4().hex


def env_token():
    """(token | None, raw). Raises UnsafeRunToken when the env var is SET but unsafe."""
    raw = os.environ.get(STAGE_RUN_ENV)
    if raw is None or raw == "":
        return None
    if not is_safe_token(raw):
        raise UnsafeRunToken(f"{STAGE_RUN_ENV} is set but is not a safe run token (32 lowercase hex)")
    return raw


def ensure_run_token() -> tuple[str, str]:
    """(token, source): the caller's token ('caller') or a freshly generated one ('standalone'). Raises
    UnsafeRunToken for an unsafe caller token (never silently replaced)."""
    tok = env_token()
    if tok:
        return tok, "caller"
    return new_token(), "standalone"


def _kind(kind: str) -> str:
    if kind not in KINDS:
        raise ValueError(f"unknown receipt kind {kind!r}")
    return kind


def receipt_dir_spec() -> tuple[Path, Path]:
    """(receipt dir, containment root). Canonical = <runtime root>/receipts/nba_stage_runs."""
    from services.nba_lines_publisher import _qc_temp_root, runtime_root
    from services.process_lock import LockPathRejected, is_within, real
    root = runtime_root()
    env = (os.environ.get(RECEIPT_DIR_OVERRIDE_ENV) or "").strip()
    if not env:
        return root / RECEIPT_SUBDIR, root
    p = Path(env)
    if is_within(p.parent, root):
        return p, root
    qc_root = _qc_temp_root(p.parent)
    if qc_root is not None:
        return p, qc_root
    raise LockPathRejected(f"{RECEIPT_DIR_OVERRIDE_ENV}={env} is outside the runtime root {real(root)} and is "
                           "not inside a qc_* temp directory (refused)")


def _validated_dir() -> Path:
    from services.process_lock import _validated_lock_dir
    d, root = receipt_dir_spec()
    return Path(_validated_lock_dir(Path(d), Path(root)))


def receipt_path(token: str, kind: str) -> Path:
    if not is_safe_token(token):
        raise UnsafeRunToken("unsafe run token")
    d, _root = receipt_dir_spec()
    return Path(d) / f"{token}.{_kind(kind)}.json"


def write(token: str, kind: str, payload: dict) -> Path:
    """Atomically write this run's receipt (stamped with stage_run_id). Raises on any failure (callers report it;
    the reader then fails closed with RUN_RECEIPT_MISSING)."""
    from services.receipt_io import replace_with_retry
    if not is_safe_token(token):
        raise UnsafeRunToken("unsafe run token")
    d = _validated_dir()
    final = d / f"{token}.{_kind(kind)}.json"
    if os.path.lexists(str(final)):
        raise FileExistsError(f"run receipt for token {token[:8]} ({kind}) already exists (token reuse refused)")
    tmp = d / f".{token}.{kind}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp"
    data = json.dumps({**payload, "stage_run_id": token, "receipt_kind": kind}, indent=2, default=str)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    fd = os.open(str(tmp), flags, FILE_MODE)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        if os.name != "nt":
            os.chmod(str(tmp), FILE_MODE)
        replace_with_retry(tmp, final)
    except BaseException:
        try:
            os.unlink(str(tmp))
        except OSError:
            pass
        raise
    return final


def read_own(token: str, kind: str) -> tuple[str, dict | None, str]:
    """(status, receipt, detail) for THIS run's receipt. status in {OK, RUN_RECEIPT_MISSING,
    RUN_RECEIPT_MISMATCH}. Never reads any other file."""
    if not is_safe_token(token):
        return RUN_RECEIPT_MISSING, None, "no safe run token for this stage"
    try:
        path = receipt_path(token, kind)
        d, root = receipt_dir_spec()
    except Exception as exc:   # containment refusal etc.
        return RUN_RECEIPT_MISSING, None, f"run receipt location refused: {exc}"
    from services.process_lock import is_within
    try:
        st = os.lstat(str(path))
    except FileNotFoundError:
        return RUN_RECEIPT_MISSING, None, f"no run receipt for this stage ({path.name})"
    except OSError as exc:
        return RUN_RECEIPT_MISSING, None, f"run receipt unreadable: {exc}"
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode) or not is_within(path, root):
        return RUN_RECEIPT_MISSING, None, f"run receipt {path.name} is not a contained regular file (refused)"
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return RUN_RECEIPT_MISSING, None, f"run receipt unreadable/torn: {exc}"
    if not isinstance(receipt, dict):
        return RUN_RECEIPT_MISSING, None, "run receipt is not an object"
    if receipt.get("stage_run_id") != token or receipt.get("receipt_kind", kind) != kind:
        return RUN_RECEIPT_MISMATCH, None, (f"run receipt {path.name} carries token "
                                            f"{str(receipt.get('stage_run_id'))[:8]!r}, not this stage's")
    return RECEIPT_OK, receipt, str(path)


def prune(protect=(), retain_days: float = RETAIN_DAYS, max_files: int = RETAIN_MAX_FILES,
          now: float | None = None) -> int:
    """Bounded retention: remove receipts older than retain_days, then the oldest beyond max_files. Tokens in
    `protect` are never removed. Returns the number removed. Best-effort (never raises)."""
    try:
        d, _root = receipt_dir_spec()
        entries = []
        for p in Path(d).glob("*.json"):
            tok = p.name.split(".", 1)[0]
            if tok in protect:
                continue
            try:
                entries.append((os.lstat(str(p)).st_mtime, p))
            except OSError:
                pass
    except Exception:
        return 0
    now = time.time() if now is None else now
    cutoff = now - retain_days * 86400
    removed = 0
    # Orphan temp files from a killed writer (never adopted: read_own only reads <token>.<kind>.json).
    try:
        for p in Path(d).glob(".*.tmp"):
            tok = p.name[1:].split(".", 1)[0]
            try:
                if tok not in protect and os.lstat(str(p)).st_mtime < now - TMP_ORPHAN_SECONDS:
                    p.unlink()
                    removed += 1
            except OSError:
                pass
    except OSError:
        pass
    keep = []
    for mtime, p in sorted(entries):
        if mtime < cutoff:
            try:
                p.unlink()
                removed += 1
            except OSError:
                pass
        else:
            keep.append(p)
    excess = len(keep) - max(0, int(max_files) - len(tuple(protect)))
    for p in keep[:max(0, excess)]:
        try:
            p.unlink()
            removed += 1
        except OSError:
            pass
    return removed


# ------------------------------------------------------------------------------------------------ publisher side
def begin(label: str, caller: str):
    """Publisher entry: the run token for this invocation, or None after printing a refusal (an unsafe caller
    token -> the publisher must exit before any lock or request)."""
    try:
        token, source = ensure_run_token()
    except UnsafeRunToken as exc:
        print(f"[RUN_TOKEN_REJECTED] {label} ({caller}): {exc}. No paid request made, nothing written.", flush=True)
        return None
    if source == "standalone":
        print(f"[RUN] {label} ({caller}): standalone invocation, own run token {token}", flush=True)
    return token


def record(token: str, kind: str, payload: dict, label: str) -> bool:
    """Write this run's receipt; on failure say so loudly (the caller will read RUN_RECEIPT_MISSING)."""
    try:
        write(token, kind, payload)
        return True
    except Exception as exc:
        print(f"[ERROR] {label}: this run's receipt could not be written ({exc!r}); the stage will read "
              f"{RUN_RECEIPT_MISSING} (fail closed).", flush=True)
        return False
