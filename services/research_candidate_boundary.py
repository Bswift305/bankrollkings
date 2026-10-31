"""Research Candidate — 2D1 observation-only application boundary (DARK / LOCAL).

The ONLY module `app.py` imports for the dark owner-only capture route. Its import is tiny and uses the
STANDARD LIBRARY ONLY (os, stat, logging, typing) — the meaningful invariant is that NO store/adapter/
pandas/sqlite is imported while OFF. The route reaches this module lazily, and the store + adapter are
imported LAZILY (and guarded) inside `capture()`, which runs only when the flag is ON — so with the flag
OFF (the default) nothing research-candidate is imported and nothing is read, opened, or written.

Boundaries (design: docs/research_candidate_2d_integration_audit.md Rev 3 + the adapter design): the DB
path is explicit + absolute + contained under an explicit approved root (realpath + commonpath, symlink
escape rejected); the store connection is request-scoped and closed in `finally`; the observer id + clocks
come from the server/store, never the payload; the adapter output is the only identity/event source;
failures map to tiers (invalid/abstain -> 422, conflict -> 409, misconfig/unhealthy -> 503). It performs
observation capture ONLY — no candidate freezing, outcomes, evaluation, thesis generation, deletion,
promotion, backup unit, UI, or production enablement.
"""
from __future__ import annotations

import logging
import os
import stat as _stat
from typing import Optional

_log = logging.getLogger("research_candidate.boundary")

FLAG = "BK_RESEARCH_CANDIDATE_ENABLED"
DB_PATH_ENV = "BK_RESEARCH_CANDIDATE_DB_PATH"       # explicit absolute path
ROOT_ENV = "BK_RESEARCH_CANDIDATE_ROOT"             # explicit absolute approved root (own env var)
PROPS_ENV = "BK_RESEARCH_CANDIDATE_PROPS"           # persisted props board path
ROSTER_ENV = "BK_RESEARCH_CANDIDATE_ROSTER"         # persisted roster artifact path
_TRUTHY = {"1", "true", "on", "yes"}


# tiered boundary errors (the route maps each to an HTTP status; messages are sanitized — no PII)
class BoundaryError(Exception):
    http = 503


class ConfigError(BoundaryError):          # misconfigured/contained-path failure -> calm 503
    http = 503


class Unavailable(BoundaryError):          # unhealthy store -> calm 503
    http = 503


class InvalidInput(BoundaryError):         # bad input or a governed adapter abstention -> 422
    http = 422


class Conflict(BoundaryError):             # idempotency conflict -> 409
    http = 409


def enabled(env: Optional[dict] = None) -> bool:
    """True only when the flag is explicitly truthy. Default (unset) => OFF (route 404s, zero import)."""
    src = os.environ if env is None else env
    return str(src.get(FLAG, "0")).strip().lower() in _TRUTHY


def _resolved_db_path() -> str:
    """The explicit absolute DB path, REQUIRED to resolve under the explicit approved root. Uses realpath
    + commonpath so a relative/missing/out-of-root/symlinked-out path fails closed; a symlink whose target
    escapes the root is rejected because realpath resolves it before the containment check."""
    db = (os.environ.get(DB_PATH_ENV, "") or "").strip()
    root = (os.environ.get(ROOT_ENV, "") or "").strip()
    if not db or not os.path.isabs(db):
        raise ConfigError("DB path env is missing or not absolute")
    if not root or not os.path.isabs(root):
        raise ConfigError("approved-root env is missing or not absolute")
    rdb, rroot = os.path.realpath(db), os.path.realpath(root)
    try:
        contained = os.path.commonpath([rdb, rroot]) == rroot
    except ValueError:      # different drives / mixed absolute+relative
        contained = False
    if not contained:
        raise ConfigError("DB path is not contained under the approved root")
    return rdb              # the CANONICAL validated path — never reopen the unchecked original spelling


def _ensure_secure_dir(path: str) -> None:
    """Create/verify the DB's containing directory as 0700. POSIX ENFORCES + verifies (failure -> 503);
    Windows is best-effort (chmod cannot set NTFS ACLs)."""
    try:
        os.makedirs(path, exist_ok=True)
    except OSError as exc:
        raise ConfigError("cannot create the approved directory") from exc
    try:
        os.chmod(path, 0o700)
    except OSError:
        if os.name != "nt":
            raise ConfigError("cannot set the approved directory to 0700")
    if os.name != "nt":
        mode = _stat.S_IMODE(os.stat(path).st_mode)
        if mode != 0o700:
            raise ConfigError(f"approved directory is not 0700 (got {oct(mode)})")


def _lock_down_db(path: str) -> None:
    """Set/verify the DB file AND every present WAL sidecar (-wal/-shm) to 0600. On POSIX EVERY present
    target must chmod successfully AND individually verify as 0600 — a chmod failure or a wrong mode on any
    one (incl. a sidecar, which holds governed observation data) fails closed with ConfigError. Windows is
    best-effort (chmod cannot set NTFS ACLs). Error labels name the suffix only (db/wal/shm) — never a
    path."""
    labels = {path: "db", path + "-wal": "wal", path + "-shm": "shm"}
    targets = [path] + [path + s for s in ("-wal", "-shm") if os.path.exists(path + s)]
    for p in targets:
        label = labels[p]
        try:
            os.chmod(p, 0o600)
        except OSError as exc:
            if os.name != "nt":
                raise ConfigError(f"cannot set {label} file to 0600") from exc
        if os.name != "nt":
            mode = _stat.S_IMODE(os.stat(p).st_mode)
            if mode != 0o600:
                raise ConfigError(f"{label} file is not 0600 (got {oct(mode)})")


def capture(*, observer_id: str, player_ref: str, event_id: str, thesis: str, sources, acted: bool,
            idempotency_key: str, correlation_id: Optional[str] = None) -> dict:
    """ON-path capture. Lazily imports the adapter + store (so OFF imports nothing), GUARDED so an import
    failure becomes a calm 503 rather than a 500. Resolves the board selection through the governed adapter
    (abstain -> 422 for user-selection / 503 for artifact-health), then captures through a REQUEST-SCOPED
    store connection closed in `finally`. The observer id is the caller's server-derived account id; the
    store owns the clocks, sequence, season gate, and evidence serialization. `correlation_id` is used ONLY
    for sanitized operational logging (close/relock failures) — never content."""
    # lazy imports — ONLY reached when the flag is ON; guarded so a dependency ImportError -> 503
    try:
        from services.research_candidate_store import (
            ResearchCandidateStore, IdempotencyConflict, SchemaVersionError, StoreIntegrityError,
            ResearchStoreError,
        )
        from services import nfl_identity_event_adapter as adapter
    except Exception as exc:
        raise Unavailable("dependency import failed") from exc

    db_path = _resolved_db_path()                     # canonical, containment-validated path
    props = (os.environ.get(PROPS_ENV, "") or "").strip()
    roster = (os.environ.get(ROSTER_ENV, "") or "").strip()
    if not props or not roster:
        raise ConfigError("props/roster path env is missing")

    # Resolution runs OUTSIDE the store block, so guard it: the adapter normally returns an Abstention,
    # but any UNEXPECTED error (pandas/filesystem/etc.) becomes a calm 503 rather than escaping as a 500.
    try:
        resolved = adapter.NflIdentityEventAdapter(props, roster).resolve(player_ref, event_id)
    except Exception as exc:
        raise Unavailable("resolver error") from exc
    if isinstance(resolved, adapter.Abstention):
        # Artifact-health abstentions (dimension 'artifact': SEASON_UNAVAILABLE, PROPS_*/ROSTER_*) are
        # PLATFORM availability failures -> 503. User-selection abstentions (event/binding/player) -> 422.
        if resolved.dimension == "artifact":
            raise Unavailable(f"availability:{resolved.reason_code}")
        raise InvalidInput(f"abstain:{resolved.reason_code}")

    # Secure the approved directory (0700) BEFORE opening; the DB file is locked to 0600 right after the
    # store creates it. POSIX enforces + verifies; failure -> 503.
    _ensure_secure_dir(os.path.dirname(db_path))

    store = None
    try:
        store = ResearchCandidateStore(db_path)       # request-scoped connection (creates the DB first use)
        _lock_down_db(db_path)                         # lock the main file (POSIX failure -> 503)
        res = store.capture_observation(
            observer_id=observer_id, entity=resolved.entity, event=resolved.event, thesis=thesis,
            sources=tuple(sources), acted=acted, evidence=resolved.evidence,
            idempotency_key=idempotency_key)
        # Re-lock AFTER the write so WAL -wal/-shm sidecars created during capture are 0600 too. The record
        # may already be committed, but reporting success while sensitive sidecars could be exposed is
        # dishonest: a post-commit permission failure is LOGGED (corr) and then raised as a sanitized 503.
        # Idempotency makes a retry safe — it returns the original record once permissions are healthy.
        try:
            _lock_down_db(db_path)
        except Exception as exc:
            _log.warning("research_candidate op=observe corr=%s status=relock_failed code=%s",
                         correlation_id, type(exc).__name__)
            raise Unavailable("post-commit relock failed") from exc
        return {"status": res["status"], "id": res["id"]}
    except IdempotencyConflict:
        raise Conflict("idempotency conflict")
    except (SchemaVersionError, StoreIntegrityError):
        raise Unavailable("store unhealthy")
    except ResearchStoreError:                        # input/eligibility rejection (e.g. non-future event)
        raise InvalidInput("rejected")
    except BoundaryError:                             # a ConfigError from _lock_down_db -> 503 as-is
        raise
    except Exception as exc:                          # any other store/filesystem/sqlite failure -> 503
        raise Unavailable("store error") from exc
    finally:
        if store is not None:
            try:
                store.close()
            except Exception as exc:
                # surfaced honestly with the request correlation id + op + coarse status + error TYPE
                # (never content); never swallowed; the primary result/exception above is preserved (a
                # close failure does not fabricate or discard a committed capture).
                _log.warning("research_candidate op=observe corr=%s status=close_failed code=%s",
                             correlation_id, type(exc).__name__)


__all__ = ["FLAG", "DB_PATH_ENV", "ROOT_ENV", "PROPS_ENV", "ROSTER_ENV", "enabled", "capture",
           "BoundaryError", "ConfigError", "Unavailable", "InvalidInput", "Conflict"]
