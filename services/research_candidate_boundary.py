"""Research Candidate — 2D1 observation-only application boundary (DARK / LOCAL).

The ONLY module `app.py` imports for the dark owner-only capture route. It is deliberately tiny and
dependency-free at import: it imports ONLY `os` at module top, so when the flag is OFF (the default) the
store, the adapter, pandas and sqlite are NEVER imported and nothing is read, opened, or written. The
store + adapter are imported LAZILY inside `capture()`, which the route reaches only when the flag is ON.

Boundaries (design: docs/research_candidate_2d_integration_audit.md Rev 3 + the adapter design): the DB
path is explicit + absolute + contained under an explicit approved root (realpath + commonpath, symlink
escape rejected); the store connection is request-scoped and closed in `finally`; the observer id + clocks
come from the server/store, never the payload; the adapter output is the only identity/event source;
failures map to tiers (invalid/abstain -> 422, conflict -> 409, misconfig/unhealthy -> 503). It performs
observation capture ONLY — no candidate freezing, outcomes, evaluation, thesis generation, deletion,
promotion, backup unit, UI, or production enablement.
"""
from __future__ import annotations

import os
from typing import Optional

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
    return db


def capture(*, observer_id: str, player_ref: str, event_id: str, thesis: str, sources, acted: bool,
            idempotency_key: str) -> dict:
    """ON-path capture. Lazily imports the adapter + store (so OFF imports nothing). Resolves the board
    selection through the governed adapter (abstain -> InvalidInput/422), then captures through a
    REQUEST-SCOPED store connection closed in `finally`. The observer id is the caller's server-derived
    account id; the store owns the clocks, sequence, season gate, and evidence serialization."""
    # lazy imports — ONLY reached when the flag is ON
    from services.research_candidate_store import (
        ResearchCandidateStore, IdempotencyConflict, SchemaVersionError, StoreIntegrityError,
        ResearchStoreError,
    )
    from services import nfl_identity_event_adapter as adapter

    db_path = _resolved_db_path()
    props = (os.environ.get(PROPS_ENV, "") or "").strip()
    roster = (os.environ.get(ROSTER_ENV, "") or "").strip()
    if not props or not roster:
        raise ConfigError("props/roster path env is missing")

    resolved = adapter.NflIdentityEventAdapter(props, roster).resolve(player_ref, event_id)
    if isinstance(resolved, adapter.Abstention):
        raise InvalidInput(f"abstain:{resolved.reason_code}")   # governed reason code (no PII)

    store = None
    try:
        store = ResearchCandidateStore(db_path)       # request-scoped connection
        res = store.capture_observation(
            observer_id=observer_id, entity=resolved.entity, event=resolved.event, thesis=thesis,
            sources=tuple(sources), acted=acted, evidence=resolved.evidence,
            idempotency_key=idempotency_key)
        return {"status": res["status"], "id": res["id"]}
    except IdempotencyConflict:
        raise Conflict("idempotency conflict")
    except (SchemaVersionError, StoreIntegrityError):
        raise Unavailable("store unhealthy")
    except ResearchStoreError:                        # input/eligibility rejection (e.g. non-future event)
        raise InvalidInput("rejected")
    finally:
        if store is not None:
            try:
                store.close()
            except Exception:
                pass


__all__ = ["FLAG", "DB_PATH_ENV", "ROOT_ENV", "PROPS_ENV", "ROSTER_ENV", "enabled", "capture",
           "BoundaryError", "ConfigError", "Unavailable", "InvalidInput", "Conflict"]
