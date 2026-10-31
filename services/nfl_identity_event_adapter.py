"""Governed NFL identity + event adapter (DARK / LOCAL — adapter Step 3).

Resolves an owner's CURRENT-BOARD selection — a `(player display name, EventId)` pair — into the
authoritative, governed inputs `capture_observation` requires (a RESOLVED `EntityIdentity`, a UTC
`EventIdentity`, and a `ResolutionEvidence`), or returns EXACTLY ONE governed `Abstention`. It is
RESEARCH_ONLY, carries zero authority, and NEVER fabricates identity:

  * exact, unique normalized-name -> roster `player_id` only — no fuzzy, short-form, or inferred identity;
  * the event id + kickoff come from the SAME persisted board snapshot, never user input;
  * player and event are bound through ONE board row `(normalized Player, EventId)`.

Boundaries (design: docs/research_candidate_identity_event_adapter_design.md, Rev 2.2):
  * each artifact is read ONCE — bytes, SHA-256, and the descriptor's mtime come from the same open fd
    (no TOCTOU), and the rows are parsed from those exact bytes;
  * the current NFL season comes from the pure `nfl_season_contract` (unsupported season abstains);
  * props staleness uses the ONE declared `freshness_contract` (CLOCK B), and the bound row's
    `SourceUpdatedAtUTC` must be present + parseable;
  * the roster's embedded `season` must equal the current season, and its name index is collision-audited
    on every (re)build;
  * built indexes are cached ONLY by `(props_sha256, roster_sha256, season, resolver_version)`, so any
    artifact-fingerprint change invalidates the cache.

NO route, feature flag, UI, unit file, production path, deployment, or schema change. Reads persisted
artifacts only (no paid fetch). The store validates this resolver's id against its registered allow-list.
"""
from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from io import BytesIO

import pandas as pd

from services.research_candidate import EntityIdentity, EventIdentity, Resolution, ResolutionEvidence
from services.nfl_season_contract import expected_completed_week
from services.freshness_contract import refresh_cadence_hours
from services.timeutils import DISPLAY_TZ

RESOLVER_ID = "nfl_identity_event_adapter"   # must be in the store's REGISTERED_RESOLVER_IDS
RESOLVER_VERSION = "v1"

PROPS_COLUMNS = ("Player", "EventId", "EventCommenceAtUTC", "SourceUpdatedAtUTC")
ROSTER_COLUMNS = ("player_id", "player_display_name", "season")

# Closed, mutually-exclusive abstention reason codes (one governed reason per unresolved request).
REASONS = frozenset({
    "SEASON_UNAVAILABLE", "PROPS_UNAVAILABLE", "PROPS_STALE", "PROPS_SCHEMA_INVALID",
    "ROSTER_UNAVAILABLE", "ROSTER_SCHEMA_INVALID", "ROSTER_SEASON_MISMATCH",
    "EVENT_NOT_FOUND", "PLAYER_EVENT_MISMATCH", "KICKOFF_MISSING", "KICKOFF_CONFLICT", "EVENT_PAST",
    "NAME_UNRESOLVED", "NAME_AMBIGUOUS", "PLAYER_ID_ALIAS_CONFLICT",
})


@dataclass(frozen=True)
class Abstention:
    reason_code: str
    dimension: str      # "artifact" | "event" | "binding" | "player"
    detail: str = ""

    def __post_init__(self) -> None:
        if self.reason_code not in REASONS:
            raise ValueError(f"unknown abstention reason {self.reason_code!r}")


@dataclass(frozen=True)
class ResolvedObservationInput:
    entity: EntityIdentity
    event: EventIdentity
    evidence: ResolutionEvidence


def _norm(s) -> str:
    """Casefold + whitespace-collapse ONLY — no fuzzy distance, no short-form/nickname expansion."""
    return re.sub(r"\s+", " ", str(s).strip()).casefold()


def _read_artifact(path: str):
    """Read one artifact ONCE: bytes, SHA-256, and the descriptor's mtime from the SAME open fd (no
    TOCTOU — a file swapped after the open cannot split the hash from the mtime or the parsed rows)."""
    fd = os.open(path, os.O_RDONLY)
    try:
        st = os.fstat(fd)
        chunks = []
        while True:
            b = os.read(fd, 1 << 20)
            if not b:
                break
            chunks.append(b)
    finally:
        os.close(fd)
    data = b"".join(chunks)
    return data, hashlib.sha256(data).hexdigest(), st.st_mtime


class NflIdentityEventAdapter:
    """Local resolver over a persisted props board + nflverse roster. Construct with explicit paths and an
    optional `clock` (a callable returning tz-aware UTC now) for deterministic tests."""

    def __init__(self, props_path: str, roster_path: str, *, clock=None) -> None:
        self._props_path = props_path
        self._roster_path = roster_path
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._cache: dict = {}
        self.build_count = 0   # increments on each index (re)build — lets tests observe cache invalidation

    # ---- resolution --------------------------------------------------------
    def resolve(self, player_ref: str, event_id: str):
        now = self._clock()

        # 1. current season (pure calendar; unsupported -> abstain)
        if DISPLAY_TZ is None:
            return Abstention("SEASON_UNAVAILABLE", "artifact", "governed Eastern zone unavailable")
        week, season = expected_completed_week(now.astimezone(DISPLAY_TZ).date())
        if week is None:
            return Abstention("SEASON_UNAVAILABLE", "artifact", f"no Week-1 anchor for season {season}")

        # 2a. props artifact (single snapshot) + declared staleness contract
        try:
            pdata, psha, pmtime = _read_artifact(self._props_path)
        except OSError:
            return Abstention("PROPS_UNAVAILABLE", "artifact")
        max_age_h = refresh_cadence_hours("props", "NFL")
        if (now.timestamp() - pmtime) > max_age_h * 3600.0:
            return Abstention("PROPS_STALE", "artifact", f"file age exceeds {max_age_h}h (CLOCK B)")
        try:
            props = pd.read_csv(BytesIO(pdata), dtype=str, keep_default_na=False)
        except Exception:
            return Abstention("PROPS_SCHEMA_INVALID", "artifact", "props unreadable")
        if not set(PROPS_COLUMNS).issubset(props.columns):
            return Abstention("PROPS_SCHEMA_INVALID", "artifact", "props missing required columns")

        # 2b. roster artifact (single snapshot) + embedded-season contract
        try:
            rdata, rsha, _rmtime = _read_artifact(self._roster_path)
        except OSError:
            return Abstention("ROSTER_UNAVAILABLE", "artifact")
        try:
            roster = pd.read_parquet(BytesIO(rdata))
        except Exception:
            return Abstention("ROSTER_SCHEMA_INVALID", "artifact", "roster unreadable")
        if not set(ROSTER_COLUMNS).issubset(roster.columns):
            return Abstention("ROSTER_SCHEMA_INVALID", "artifact", "roster missing required columns")
        try:
            seasons = {int(x) for x in roster["season"].dropna().unique()}
        except (TypeError, ValueError):
            return Abstention("ROSTER_SCHEMA_INVALID", "artifact", "roster season column not integer")
        if seasons != {season}:
            return Abstention("ROSTER_SEASON_MISMATCH", "artifact",
                              f"roster seasons {sorted(seasons)} != current {season}")

        idx = self._index(psha, rsha, season, props, roster)

        # 3. event presence on the current board
        if event_id not in idx["event_ids"]:
            return Abstention("EVENT_NOT_FOUND", "event")
        nm = _norm(player_ref)
        # 4. player<->event binding through ONE board row
        if (nm, event_id) not in idx["pairs"]:
            return Abstention("PLAYER_EVENT_MISMATCH", "binding")
        # 5a. bound-row freshness metadata (SourceUpdatedAtUTC present + parseable)
        if not idx["source_updated_ok"].get((nm, event_id), False):
            return Abstention("PROPS_SCHEMA_INVALID", "artifact",
                              "bound-row SourceUpdatedAtUTC missing/unparseable")
        # 5b. kickoff from the SAME snapshot
        kc = idx["kickoffs"][event_id]
        if kc["missing"]:
            return Abstention("KICKOFF_MISSING", "event")
        if kc["conflict"]:
            return Abstention("KICKOFF_CONFLICT", "event")
        kickoff = kc["value"]
        if kickoff <= now:
            return Abstention("EVENT_PAST", "event")
        # 6. exact unique identity (collision-audited)
        ids = idx["name_to_ids"].get(nm)
        if not ids:
            return Abstention("NAME_UNRESOLVED", "player")
        if len(ids) > 1:
            return Abstention("NAME_AMBIGUOUS", "player")
        pid = next(iter(ids))
        displays = idx["id_to_displays"].get(pid, set())
        if len(displays) > 1:
            return Abstention("PLAYER_ID_ALIAS_CONFLICT", "player")
        display = next(iter(displays))

        entity = EntityIdentity(canonical_id=pid, display=display, resolution=Resolution.RESOLVED)
        event = EventIdentity(canonical_id=event_id, event_effective=kickoff)
        evidence = ResolutionEvidence(
            resolver_id=RESOLVER_ID, resolver_version=RESOLVER_VERSION, props_sha256=psha,
            roster_sha256=rsha, roster_season=season, event_id=event_id, player_id=pid, resolved_at=now)
        return ResolvedObservationInput(entity=entity, event=event, evidence=evidence)

    # ---- index (cached ONLY by artifact fingerprints + season + resolver version) ----
    def _index(self, psha: str, rsha: str, season: int, props: pd.DataFrame, roster: pd.DataFrame):
        key = (psha, rsha, season, RESOLVER_VERSION)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        self.build_count += 1

        p = props.copy()
        p["_nm"] = p["Player"].map(_norm)
        p["_eid"] = p["EventId"].astype(str).str.strip()
        valid = p[(p["_nm"] != "") & (p["_eid"] != "")]
        event_ids = set(p.loc[p["_eid"] != "", "_eid"])
        pairs = set(zip(valid["_nm"], valid["_eid"]))

        kt = pd.to_datetime(p["EventCommenceAtUTC"], errors="coerce", utc=True)
        p = p.assign(_k=kt)
        kickoffs = {}
        for eid, grp in p[p["_eid"] != ""].groupby("_eid"):
            ks = grp["_k"]
            missing = bool(ks.isna().any())
            distinct = list(ks.dropna().unique())
            conflict = len(distinct) > 1
            value = (pd.Timestamp(distinct[0]).to_pydatetime()
                     if (not missing and len(distinct) == 1) else None)
            kickoffs[eid] = {"missing": missing, "conflict": conflict, "value": value}

        su = pd.to_datetime(p["SourceUpdatedAtUTC"], errors="coerce", utc=True)
        p = p.assign(_su_ok=((p["SourceUpdatedAtUTC"].astype(str).str.strip() != "") & su.notna()))
        source_updated_ok = {}
        for (nm, eid), grp in p[(p["_nm"] != "") & (p["_eid"] != "")].groupby(["_nm", "_eid"]):
            source_updated_ok[(nm, eid)] = bool(grp["_su_ok"].all())

        # roster is already verified to be exactly the current season; build + collision-audit the index
        r = roster[["player_id", "player_display_name"]].copy()
        r["player_id"] = r["player_id"].astype(str).str.strip()
        r["player_display_name"] = r["player_display_name"].astype(str)
        r = r[(r["player_id"] != "") & (r["player_display_name"].str.strip() != "")]
        r["_nm"] = r["player_display_name"].map(_norm)
        name_to_ids: dict = {}
        id_to_displays: dict = {}
        for pid, disp, nm in zip(r["player_id"], r["player_display_name"], r["_nm"]):
            name_to_ids.setdefault(nm, set()).add(pid)
            id_to_displays.setdefault(pid, set()).add(disp)

        built = {"event_ids": event_ids, "pairs": pairs, "kickoffs": kickoffs,
                 "source_updated_ok": source_updated_ok, "name_to_ids": name_to_ids,
                 "id_to_displays": id_to_displays}
        self._cache[key] = built
        return built


__all__ = ["NflIdentityEventAdapter", "ResolvedObservationInput", "Abstention", "REASONS",
           "RESOLVER_ID", "RESOLVER_VERSION"]
