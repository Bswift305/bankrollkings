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

from datetime import datetime, timezone

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


def parse_feed_timestamp_utc(value):
    """Feed ``LastUpdated``-style stamp -> aware UTC datetime, or None if blank/unparseable.

    The convention is explicit, never the process's ambient zone:
      * an offset-bearing stamp (``...Z`` / ``+00:00`` -- e.g. fetch_ncaaf_slate_cfbd.py) keeps its
        own offset;
      * a NAIVE stamp (``YYYY-MM-DD HH:MM`` -- fetch_game_lines.py writes the provider's UTC
        ``last_update`` through ``to_eastern_datetime_str``) is US Eastern wall-clock time.
    Reading a naive Eastern stamp against a naive ``now()`` mis-ages it by the process's offset from
    Eastern (+4/5h on the UTC prod box, -3h on a Pacific dev box). Ambiguous fall-back hours resolve
    to the first occurrence (fold=0) rather than raising.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in ("nan", "nat", "none"):
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if parsed.tzinfo is None:
        if DISPLAY_TZ is None:  # pragma: no cover - missing tzdata
            return None
        parsed = parsed.replace(tzinfo=DISPLAY_TZ)
    return parsed.astimezone(timezone.utc)


def to_eastern_date_str(value, fmt: str = "%Y-%m-%d") -> str:
    """UTC ISO commence time -> 'YYYY-MM-DD' in US Eastern. '' on failure/empty."""
    try:
        dt = _to_eastern(value)
    except (ValueError, TypeError):
        return ""
    return dt.strftime(fmt) if dt else ""
