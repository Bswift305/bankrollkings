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
