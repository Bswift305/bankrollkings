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


def eastern_today():
    """Today's calendar date on the Eastern league clock (never the process's ambient zone).

    Dependency-free twin of app.sports_today_date() for batch scripts that must not import app.py.
    On the UTC prod box a bare datetime.now().date() rolls to tomorrow at ~8pm ET."""
    now = datetime.now(DISPLAY_TZ) if DISPLAY_TZ else datetime.now()
    return now.date()


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


def event_eastern_date(value):
    """Event date/time cell -> Eastern calendar ``date``, or None when it cannot be parsed.

    - Timezone-aware ISO values (``...Z`` / ``+00:00``, e.g. provider ``commence_time``) are
      CONVERTED to Eastern, so a 01:00 UTC tip lands on the previous Eastern date.
    - Naive values ('YYYY-MM-DD' or 'YYYY-MM-DD HH:MM') are taken as already-Eastern: that is
      how the fetchers write schedule ``Date`` columns (via to_eastern_date_str).
    - 'MM/DD/YYYY' is accepted as a naive Eastern date.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in ("nan", "nat", "none"):
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        parsed = None
        for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
            try:
                parsed = datetime.strptime(text[:10], fmt)
                break
            except ValueError:
                continue
        if parsed is None:
            return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(DISPLAY_TZ) if DISPLAY_TZ else parsed.astimezone()
    return parsed.date()


def to_eastern_date_str(value, fmt: str = "%Y-%m-%d") -> str:
    """UTC ISO commence time -> 'YYYY-MM-DD' in US Eastern. '' on failure/empty."""
    try:
        dt = _to_eastern(value)
    except (ValueError, TypeError):
        return ""
    return dt.strftime(fmt) if dt else ""
