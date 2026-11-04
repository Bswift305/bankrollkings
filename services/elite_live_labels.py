"""Elite live line-movement scanner: FACTUAL row labels (D14 / P1, 2026-11). Contract: docs/elite_live_labels_d14.md.

The scanner used to stamp each move with a directive -- ACT / HOLD / WINDOW CLOSING / PASS -- and a "sharp side".
None of those had a governed decision contract behind them (WINDOW CLOSING was not even time-based), so they
are replaced by facts:

  * each move has a factual state -- LINE_MOVED / PRICE_MOVED / LINE_AND_PRICE_MOVED / NO_QUALIFYING_MOVE /
    INSUFFICIENT_DATA -- with its actual line delta (points) and price deltas (American-odds cents), each unit
    with its own threshold, never combined (classify_move);
  * the side the price/line moved toward is the "line-move side" (never "sharp");
  * model-vs-move is stated as a comparison ("Model side matches / differs from the line-move side");
  * the only time-related label is a countdown to the event's VERIFIED start, e.g. "Starts in 24 minutes",
    shown ONLY when every input is present and valid; otherwise NO label and a neutral note says why.

Countdown predicate (all required; each missing input independently suppresses the label):
  START_UNVERIFIED   EventCommenceAtUTC parses as an explicit-UTC instant (provider kickoff; naive/offset != 0 rejected)
  EVENT_STARTED      now (aware UTC) is strictly before that instant
  QUOTE_TIME_MISSING SourceUpdatedAtUTC parses as an explicit-UTC instant, not in the future beyond 5 min skew
  QUOTE_STALE        ... and is no older than LIVE_MARKET_MAX_AGE_HOURS (CLOCK A, 6h)
  SOURCE_MISSING     recorded props-feed source + provider EventId + book are all present
  NO_EXECUTABLE_QUOTE a finite current line AND a valid American price (|odds| >= 100) on the line-move side

Pure (stdlib only); `now` is always an aware UTC instant (services.timeutils.utc_now by default) -- never the
process's ambient zone, so a UTC prod server after 8pm ET counts down correctly. Computed at RENDER time (the
Elite page context is snapshot-cached for 12h; a countdown frozen into a snapshot would lie).
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from services.freshness_contract import LIVE_MARKET_MAX_AGE_HOURS
from services.timeutils import format_eastern_display, utc_now

SOURCE_PREFIX = "props_feed:"
FUTURE_SKEW = timedelta(minutes=5)

START_UNVERIFIED = "START_UNVERIFIED"
EVENT_STARTED = "EVENT_STARTED"
QUOTE_TIME_MISSING = "QUOTE_TIME_MISSING"
QUOTE_STALE = "QUOTE_STALE"
SOURCE_MISSING = "SOURCE_MISSING"
NO_EXECUTABLE_QUOTE = "NO_EXECUTABLE_QUOTE"

REASON_TEXT = {
    START_UNVERIFIED: "event start time not verified",
    EVENT_STARTED: "event start time has passed",
    QUOTE_TIME_MISSING: "quote update time not recorded",
    QUOTE_STALE: f"quote older than {LIVE_MARKET_MAX_AGE_HOURS:g}h",
    SOURCE_MISSING: "quote source not recorded",
    NO_EXECUTABLE_QUOTE: "no complete price on the line-move side",
}

ALIGNMENT_TEXT = {
    "ALIGNED": "Model side matches the line-move side",
    "CONFLICT": "Model side differs from the line-move side",
    "UNKNOWN": "No model side on record",
}

_MISSING = {"", "nan", "nat", "none", "null", "<na>"}


def strict_utc(value):
    """Aware UTC datetime only for an explicit-UTC ISO instant ('...Z' or '+00:00'); None otherwise."""
    text = str(value if value is not None else "").strip()
    if text.lower() in _MISSING:
        return None
    try:
        dt = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
    except ValueError:
        return None
    if dt.tzinfo is None or dt.utcoffset() != timedelta(0):
        return None
    return dt.astimezone(timezone.utc)


def _finite(value):
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _text(value):
    t = str(value if value is not None else "").strip()
    return "" if t.lower() in _MISSING else t


# ------------------------------------------------------------------------------------------------ move state
# Owner decision (D14, 2026-11-04): line movement and price movement are DIFFERENT UNITS and are never combined
# into one threshold or score. Each has its own actual delta and its own qualifying threshold (a fact about what
# the scanner lists, not a claim that a move matters):
LINE_MOVE_MIN_POINTS = 0.5          # |current line - open line| in points
PRICE_MOVE_MIN_CENTS = 10           # |current price - open price| in American-odds cents, either side

LINE_MOVED = "LINE_MOVED"
PRICE_MOVED = "PRICE_MOVED"
LINE_AND_PRICE_MOVED = "LINE_AND_PRICE_MOVED"
NO_QUALIFYING_MOVE = "NO_QUALIFYING_MOVE"
INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
MOVE_STATES = (LINE_MOVED, PRICE_MOVED, LINE_AND_PRICE_MOVED, NO_QUALIFYING_MOVE, INSUFFICIENT_DATA)
LISTED_STATES = (LINE_MOVED, PRICE_MOVED, LINE_AND_PRICE_MOVED)
MOVE_STATE_TEXT = {
    LINE_MOVED: "Line moved",
    PRICE_MOVED: "Price moved",
    LINE_AND_PRICE_MOVED: "Line and price moved",
    NO_QUALIFYING_MOVE: "No qualifying move",
    INSUFFICIENT_DATA: "Insufficient data",
}


def american_odds(value):
    """A valid American price (|odds| >= 100) as float, else None."""
    f = _finite(value)
    return f if f is not None and abs(f) >= 100 else None


def american_cents(value):
    """American odds on the continuous 'cents' scale used for price moves: -110 -> -10, +105 -> +5, so
    -105 -> +105 is 10 cents and -110 -> -150 is -40 cents (more negative = more expensive)."""
    a = american_odds(value)
    if a is None:
        return None
    return a + 100.0 if a < 0 else a - 100.0


def price_delta_cents(open_price, current_price):
    o, c = american_cents(open_price), american_cents(current_price)
    return None if o is None or c is None else round(c - o, 1)


def classify_move(open_line, current_line, open_over, over, open_under, under) -> dict:
    """Factual move state with each actual delta in its own unit. `move_side` = the side the market moved
    toward: from the line when the line qualifies (line up -> OVER), else the side whose price became more
    expensive by more cents (tie / neither -> None)."""
    ol, cl = _finite(open_line), _finite(current_line)
    line_delta = round(cl - ol, 2) if ol is not None and cl is not None else None
    over_c = price_delta_cents(open_over, over)
    under_c = price_delta_cents(open_under, under)
    if line_delta is None and over_c is None and under_c is None:
        state = INSUFFICIENT_DATA
    else:
        line_q = line_delta is not None and abs(line_delta) >= LINE_MOVE_MIN_POINTS
        price_q = any(d is not None and abs(d) >= PRICE_MOVE_MIN_CENTS for d in (over_c, under_c))
        state = (LINE_AND_PRICE_MOVED if line_q and price_q else LINE_MOVED if line_q
                 else PRICE_MOVED if price_q else NO_QUALIFYING_MOVE)
    side = None
    if state in (LINE_MOVED, LINE_AND_PRICE_MOVED):
        side = "OVER" if line_delta > 0 else "UNDER"
    elif state == PRICE_MOVED:
        o, u = (over_c or 0.0), (under_c or 0.0)
        side = "OVER" if o < u else "UNDER" if u < o else None
    return {"move_state": state, "line_delta": line_delta, "over_price_delta_cents": over_c,
            "under_price_delta_cents": under_c, "move_side": side}


def line_move_size(row):
    v = _finite(row.get("line_delta"))
    return abs(v) if v is not None else None


def price_move_size(row):
    vals = [abs(v) for v in (_finite(row.get("over_price_delta_cents")), _finite(row.get("under_price_delta_cents")))
            if v is not None]
    return max(vals) if vals else None


def side_price(row):
    side = str(row.get("move_side") or "").upper()
    price = _finite(row.get("over_price") if side == "OVER" else row.get("under_price") if side == "UNDER" else None)
    return price if price is not None and abs(price) >= 100 else None


def countdown_text(seconds: float) -> str:
    minutes = int(seconds // 60)
    if minutes < 1:
        return "Starts in under 1 minute"
    if minutes < 60:
        return f"Starts in {minutes} minute{'s' if minutes != 1 else ''}"
    hours, mins = divmod(minutes, 60)
    if hours < 48:
        return f"Starts in {hours} h {mins} min"
    days, hours = divmod(hours, 24)
    return f"Starts in {days} days {hours} h"


def start_facts(row, now=None):
    """(label | None, start_display_et | None, reasons[]). label only when reasons is empty."""
    now = now or utc_now()
    reasons = []
    commence = strict_utc(row.get("event_commence_utc"))
    if commence is None:
        reasons.append(START_UNVERIFIED)
    elif now >= commence:
        reasons.append(EVENT_STARTED)
    quoted = strict_utc(row.get("quote_updated_utc"))
    if quoted is None or quoted - now > FUTURE_SKEW:
        reasons.append(QUOTE_TIME_MISSING)
    elif (now - quoted).total_seconds() / 3600.0 > LIVE_MARKET_MAX_AGE_HOURS:
        reasons.append(QUOTE_STALE)
    src = _text(row.get("source_provenance"))
    if not (src.startswith(SOURCE_PREFIX) and _text(row.get("event_id")) and _text(row.get("book"))):
        reasons.append(SOURCE_MISSING)
    if _finite(row.get("current_line")) is None or side_price(row) is None:
        reasons.append(NO_EXECUTABLE_QUOTE)
    display = format_eastern_display(commence, "%a %b %d, %I:%M %p ET") if commence is not None else None
    if reasons:
        return None, display, reasons
    return countdown_text((commence - now).total_seconds()), display, []


SORT_OPTIONS = ("start", "line", "price")   # "start" is the default; line/price only when the user asks


def neutral_sort_key(row, now=None):
    """DEFAULT order (owner decision 4): upcoming verified starts first (soonest first), then unverified, then
    started (most recent first); within a group the most recent quote update first, then player name. No score,
    no move size, no model alignment."""
    now = now or utc_now()
    commence = strict_utc(row.get("event_commence_utc"))
    if commence is not None and commence > now:
        group, t = 0, commence.timestamp()
    elif commence is None:
        group, t = 1, 0.0
    else:
        group, t = 2, -commence.timestamp()
    quoted = strict_utc(row.get("quote_updated_utc"))
    return (group, t, -(quoted.timestamp() if quoted is not None else 0.0), str(row.get("player") or "").upper())


def _size_key(size_fn, now):
    def key(row):
        size = size_fn(row)
        return (size is None, -(size or 0.0), neutral_sort_key(row, now))
    return key


def annotate(rows, now=None, sort=None, state=None):
    """Render-time copy of the live scanner rows with factual start labels. Default order = neutral_sort_key.
    `sort` = "line" / "price" (explicit user choice) orders by THAT unit's own actual delta only -- the two are
    never combined. `state` (one of LISTED_STATES) filters to that move state."""
    now = now or utc_now()
    out = []
    for row in rows or []:
        r = dict(row)
        if state in MOVE_STATES and r.get("move_state") != state:
            continue
        label, display, reasons = start_facts(r, now)
        r["start_label"] = label
        r["start_display_et"] = display
        r["start_reasons"] = reasons
        r["start_note"] = None if label else "No countdown: " + "; ".join(REASON_TEXT[c] for c in reasons) + "."
        r["alignment_text"] = ALIGNMENT_TEXT.get(str(r.get("alignment") or "UNKNOWN"), ALIGNMENT_TEXT["UNKNOWN"])
        r["move_state_text"] = MOVE_STATE_TEXT.get(str(r.get("move_state") or ""), MOVE_STATE_TEXT[INSUFFICIENT_DATA])
        out.append(r)
    if sort == "line":
        out.sort(key=_size_key(line_move_size, now))
    elif sort == "price":
        out.sort(key=_size_key(price_move_size, now))
    else:
        out.sort(key=lambda r: neutral_sort_key(r, now))
    return out
