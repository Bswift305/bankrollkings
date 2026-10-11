"""Shared NFL inclusion predicates + reason codes (single source of truth).

Pure module -- NO app import, operates only on primitives -- so the board builders
(build_nfl_floor_board, _card_pools/The Menu, build_green_light) AND the Player Check
evaluator decide inclusion with the exact same logic and can never drift. Per the frozen
Player Check spec (docs/nfl_player_check_spec.md §5): a reason code is produced only by a
predicate here; a surface's include/exclude decision is only ever this predicate's verdict.

Nothing in this module re-reads data or re-implements a board; it encodes the thresholds and the
gate conditions the builders already use, extracted verbatim.
"""

# --- threshold constants (the only place these numbers live) -----------------------------
MIN_GAMES_DEFAULT = 8          # build_nfl_floor_board default min sample

FLOOR_PAGE_MIN_HIT = 78        # /tools/nfl-floor default
FLOOR_PAGE_LIMIT = 24
CARD_POOL_MIN_HIT = 52         # _card_pools raw board (Menu / Daily Card)
CARD_POOL_LIMIT = 90

MENU_FLOOR_MIN_HIT = 80        # Menu "floor" candidate rule
MENU_FLOOR_PRICE_LO = -185     # configured floor price band (mechanical product rule,
MENU_FLOOR_PRICE_HI = 115      #   NOT a fairness/value judgment)
MENU_SWING_MIN_PRICE = 120     # Menu "swing" candidate rule
MENU_SWING_MIN_HIT = 55

MIN_AMERICAN_ODDS = 100        # a usable American price has |odds| >= 100


class Reason:
    """Centralized reason-code catalog (spec §7). String values are stable identifiers."""
    INCLUDED = "INCLUDED"
    # eligibility gates
    NO_SUPPORTED_MARKET = "NO_SUPPORTED_MARKET"
    NO_PRIMARY_PROP = "NO_PRIMARY_PROP"
    STAT_NOT_SUPPORTED = "STAT_NOT_SUPPORTED"
    NO_VALID_LINE = "NO_VALID_LINE"
    NO_GAMELOG = "NO_GAMELOG"
    AMBIGUOUS_NAME = "AMBIGUOUS_NAME"
    STAT_COLUMNS_MISSING = "STAT_COLUMNS_MISSING"
    INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"
    BELOW_HIT_THRESHOLD = "BELOW_HIT_THRESHOLD"
    INVALID_PRICE = "INVALID_PRICE"
    NOT_FLOOR_OR_SWING = "NOT_FLOOR_OR_SWING"
    NOT_FEATURED_USAGE = "NOT_FEATURED_USAGE"
    NO_LENS_SUPPORT = "NO_LENS_SUPPORT"
    # view / display state (clearable or scope-only, not an eligibility failure)
    BELOW_DISPLAY_CUTOFF = "BELOW_DISPLAY_CUTOFF"
    POSITION_FILTERED = "POSITION_FILTERED"
    ROSTER_POSITION_UNKNOWN = "ROSTER_POSITION_UNKNOWN"
    TIMEFRAME_EXCLUDED = "TIMEFRAME_EXCLUDED"
    SPORT_OR_SOURCE_EXCLUDED = "SPORT_OR_SOURCE_EXCLUDED"


ELIGIBILITY_CODES = frozenset({
    Reason.NO_SUPPORTED_MARKET, Reason.NO_PRIMARY_PROP, Reason.STAT_NOT_SUPPORTED,
    Reason.NO_VALID_LINE, Reason.NO_GAMELOG, Reason.AMBIGUOUS_NAME,
    Reason.STAT_COLUMNS_MISSING, Reason.INSUFFICIENT_SAMPLE, Reason.BELOW_HIT_THRESHOLD,
    Reason.INVALID_PRICE, Reason.NOT_FLOOR_OR_SWING, Reason.NOT_FEATURED_USAGE,
    Reason.NO_LENS_SUPPORT,
})
VIEW_CODES = frozenset({
    Reason.BELOW_DISPLAY_CUTOFF, Reason.POSITION_FILTERED, Reason.ROSTER_POSITION_UNKNOWN,
    Reason.TIMEFRAME_EXCLUDED, Reason.SPORT_OR_SOURCE_EXCLUDED,
})


def reason_class(code):
    """'ELIGIBILITY', 'VIEW', or 'INCLUDED' -- drives the honest VIEW-vs-ELIGIBILITY UI split."""
    if code == Reason.INCLUDED:
        return "INCLUDED"
    if code in VIEW_CODES:
        return "VIEW"
    return "ELIGIBILITY"


def price_is_valid_american(price):
    """A usable American price has |odds| >= 100; smaller values are feed artifacts."""
    return price is not None and abs(price) >= MIN_AMERICAN_ODDS


def floor_market_verdict(hit, sample_n, *, min_hit, min_games=MIN_GAMES_DEFAULT):
    """Floor-board eligibility for ONE canonical market. Reliability only -- price is NOT a gate
    here (an otherwise-qualified row with no usable price is still INCLUDED). Mirrors the
    build_nfl_floor_board gates exactly.

    Returns (included: bool, reason_code). `hit` is the integer hit-rate percentage over the
    chosen window; `sample_n` is that window's game count.
    """
    if sample_n < min_games:
        return False, Reason.INSUFFICIENT_SAMPLE
    if hit < min_hit:
        return False, Reason.BELOW_HIT_THRESHOLD
    return True, Reason.INCLUDED


def menu_candidate_tier(hit, price):
    """The Menu candidate gate for ONE canonical market (mirrors _card_pools). Unlike the floor
    board, the Menu requires a usable American price. Returns (tier, reason_code) where tier is
    'floor', 'swing', or None. When tier is None the code says why (INVALID_PRICE or
    NOT_FLOOR_OR_SWING); when a tier is returned the code is INCLUDED.
    """
    if not price_is_valid_american(price):
        return None, Reason.INVALID_PRICE
    if hit >= MENU_FLOOR_MIN_HIT and MENU_FLOOR_PRICE_LO <= price <= MENU_FLOOR_PRICE_HI:
        return "floor", Reason.INCLUDED
    if price >= MENU_SWING_MIN_PRICE and hit >= MENU_SWING_MIN_HIT:
        return "swing", Reason.INCLUDED
    return None, Reason.NOT_FLOOR_OR_SWING


def green_light_lens_verdict(convergence, has_td_angle):
    """Green Light's lens gate: a featured player's primary market needs >=1 configured lens or
    a TD angle (mirrors build_green_light). Returns (included, reason_code)."""
    if convergence == 0 and not has_td_angle:
        return False, Reason.NO_LENS_SUPPORT
    return True, Reason.INCLUDED
