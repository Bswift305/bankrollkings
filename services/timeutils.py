"""Shared time helpers for Bankroll Kings fetchers.

Game commence times arrive from the odds/stat providers in UTC. The board
displays everything in US Eastern (the canonical league clock). Converting with
a bare ``datetime.astimezone()`` is non-deterministic: it uses whatever timezone
the running *process* happens to be in. A fetch run interactively (Eastern) and
the same fetch run from a Windows scheduled task / service (UTC context) then
disagree -- an 8:40pm ET tip written from a UTC process lands as ``00:40`` on the
*following* calendar day, which mislabels the schedule date and the TODAY/TMR
badge on the board. Always convert game times to a fixed Eastern zone.
"""

from __future__ import annotations

from datetime import datetime

try:
    from zoneinfo import ZoneInfo

    DISPLAY_TZ = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover - missing tzdata; fall back to ambient zone
    DISPLAY_TZ = None


def _to_eastern(value):
    """Parse a UTC ISO timestamp and return it as an aware Eastern datetime."""
    if value in (None, ""):
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.astimezone(DISPLAY_TZ) if DISPLAY_TZ else parsed.astimezone()


def to_eastern_datetime_str(value, fmt: str = "%Y-%m-%d %H:%M") -> str:
    """UTC ISO commence time -> 'YYYY-MM-DD HH:MM' in US Eastern.

    Returns '' for empty input and echoes the raw value back on parse failure
    (preserving the historical ``to_iso_local`` contract).
    """
    try:
        dt = _to_eastern(value)
    except (ValueError, TypeError):
        return str(value) if value else ""
    return dt.strftime(fmt) if dt else ""


def to_eastern_date_str(value, fmt: str = "%Y-%m-%d") -> str:
    """UTC ISO commence time -> 'YYYY-MM-DD' in US Eastern. '' on failure/empty."""
    try:
        dt = _to_eastern(value)
    except (ValueError, TypeError):
        return ""
    return dt.strftime(fmt) if dt else ""


# ---------------------------------------------------------------------------------------------------
# UTC instants (2026-11 NBA game-lines correction). Two different needs, two different helpers:
#
#   * PROVENANCE (strict): an authoritative provider kickoff is canonical zero-offset UTC
#     'YYYY-MM-DDTHH:MM:SSZ' (to_utc_z_str). A legacy Eastern wall-clock Date+Time may be converted to a
#     COMPARISON instant only through eastern_wall_to_utc_strict, which FAILS CLOSED on a missing,
#     unparseable, ambiguous (DST fall-back fold) or nonexistent (DST spring-forward gap) wall time.
#
#   * AGE (display/freshness): instant_to_utc never fails closed -- a timezone-aware value is converted to
#     UTC; a NAIVE value is the fetchers' Eastern wall clock (to_eastern_datetime_str output), so it is
#     interpreted in America/New_York, NOT in the server's ambient zone (prod is UTC: comparing a naive
#     Eastern stamp with a naive server 'now' overstated every age by 4-5h). An ambiguous or nonexistent
#     wall time resolves to the EARLIEST plausible instant, so a computed age is never understated.
# ---------------------------------------------------------------------------------------------------
from datetime import timezone as _tz

UTC = _tz.utc
_MISSING_TOKENS = {"", "nan", "none", "nat", "<na>", "null"}

LEGACY_KICKOFF_OK = "OK"
LEGACY_KICKOFF_MISSING = "MISSING"
LEGACY_KICKOFF_UNPARSEABLE = "UNPARSEABLE"
LEGACY_KICKOFF_AMBIGUOUS = "AMBIGUOUS"        # DST fall-back fold: the wall time happens twice
LEGACY_KICKOFF_NONEXISTENT = "NONEXISTENT"    # DST spring-forward gap: the wall time never happens
LEGACY_KICKOFF_NO_TZDATA = "NO_TZDATA"


def utc_now() -> datetime:
    """The current instant, timezone-aware UTC. Never use a naive datetime.now() for an age."""
    return datetime.now(UTC)


def format_utc_z(dt) -> str:
    """Aware datetime -> canonical 'YYYY-MM-DDTHH:MM:SSZ'. '' for None/naive."""
    if dt is None or getattr(dt, "tzinfo", None) is None:
        return ""
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def to_utc_z_str(value) -> str:
    """Provider timestamp (ISO-8601 WITH an offset, e.g. Odds API commence_time '...Z') -> canonical
    'YYYY-MM-DDTHH:MM:SSZ'. A missing, unparseable or timezone-NAIVE value returns '' -- an unknown zone
    stays unknown and is never assumed UTC. Same contract as fetch_player_props.to_utc_iso."""
    if value is None:
        return ""
    s = str(value).strip()
    if s.lower() in _MISSING_TOKENS:
        return ""
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return ""
    return format_utc_z(dt)


def _zone(tz_name):
    if tz_name in (None, "", "America/New_York"):
        return DISPLAY_TZ
    try:
        return ZoneInfo(tz_name)
    except Exception:  # pragma: no cover
        return None


def eastern_wall_to_utc_strict(date_str, time_str, fmt: str = "%Y-%m-%d %H:%M",
                               tz_name: str = "America/New_York"):
    """LEGACY BRIDGE ONLY. Convert an explicit Eastern wall-clock Date + Time (the fetcher's display
    columns) to an aware UTC instant, DST-aware via zoneinfo. Returns (utc_datetime | None, code).

    Fails closed (None + code) on MISSING / UNPARSEABLE / AMBIGUOUS (fold) / NONEXISTENT (gap) /
    NO_TZDATA. The result is a DERIVED comparison instant -- callers must label it DERIVED_LEGACY_KICKOFF
    and must never publish it as provider-supplied provenance."""
    zone = _zone(tz_name)
    if zone is None:
        return None, LEGACY_KICKOFF_NO_TZDATA
    d = "" if date_str is None else str(date_str).strip()
    t = "" if time_str is None else str(time_str).strip()
    if d.lower() in _MISSING_TOKENS or t.lower() in _MISSING_TOKENS:
        return None, LEGACY_KICKOFF_MISSING
    try:
        naive = datetime.strptime(f"{d} {t}", fmt)
    except ValueError:
        return None, LEGACY_KICKOFF_UNPARSEABLE
    a0 = naive.replace(tzinfo=zone, fold=0)
    a1 = naive.replace(tzinfo=zone, fold=1)
    if a0.utcoffset() != a1.utcoffset():
        round_trip = a0.astimezone(UTC).astimezone(zone).replace(tzinfo=None)
        if round_trip != naive:
            return None, LEGACY_KICKOFF_NONEXISTENT
        return None, LEGACY_KICKOFF_AMBIGUOUS
    return a0.astimezone(UTC), LEGACY_KICKOFF_OK


def instant_to_utc(value, naive_tz: str = "America/New_York"):
    """AGE/FRESHNESS helper. Any timestamp-like value -> aware UTC datetime, or None if unparseable.
    Aware values are converted; NAIVE values are interpreted as `naive_tz` wall clock (Eastern: what the
    fetchers write). Ambiguous/nonexistent wall times resolve to the EARLIEST plausible instant so an age
    is never understated (errs toward stale)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        s = str(value).strip()
        if s.lower() in _MISSING_TOKENS:
            return None
        iso = s[:-1] + "+00:00" if s.endswith("Z") else s
        try:
            dt = datetime.fromisoformat(iso)
        except ValueError:
            try:
                import pandas as _pd
                ts = _pd.to_datetime(s, errors="coerce")
            except Exception:
                return None
            if ts is None or ts is getattr(_pd, "NaT", None) or str(ts) == "NaT":
                return None
            dt = ts.to_pydatetime()
    if hasattr(dt, "to_pydatetime"):
        dt = dt.to_pydatetime()
    if dt.tzinfo is not None:
        return dt.astimezone(UTC)
    zone = _zone(naive_tz)
    if zone is None:  # pragma: no cover - no tzdata: treat as UTC rather than ambient zone
        return dt.replace(tzinfo=UTC)
    c0 = dt.replace(tzinfo=zone, fold=0).astimezone(UTC)
    c1 = dt.replace(tzinfo=zone, fold=1).astimezone(UTC)
    return min(c0, c1)


def age_hours(value, now=None, naive_tz: str = "America/New_York"):
    """Hours between `value` (see instant_to_utc) and `now` (aware; default utc_now()). None if the value
    cannot be parsed. Both sides are UTC instants, so DST and the server zone cannot skew the result."""
    inst = instant_to_utc(value, naive_tz=naive_tz)
    if inst is None:
        return None
    ref = instant_to_utc(now, naive_tz="UTC") if now is not None else utc_now()
    if ref is None:
        ref = utc_now()
    return (ref - inst).total_seconds() / 3600.0


def format_eastern_display(dt, fmt: str = "%b %d, %Y %I:%M %p ET") -> str:
    """Aware instant -> Eastern display string (labelled ET). '' for None."""
    if dt is None:
        return ""
    if getattr(dt, "tzinfo", None) is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(DISPLAY_TZ).strftime(fmt) if DISPLAY_TZ else dt.strftime(fmt)
