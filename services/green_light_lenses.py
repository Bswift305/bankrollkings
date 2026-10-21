"""Green Light preference workspace — lens registry + PURE preference logic (data-only, no app import).

Single source of truth for which lenses exist, their classification and default order, plus the pure
functions that validate a user's stored preferences and apply them to an already-built set of lens outputs.
It re-derives NOTHING: each lens' factual content is produced by its existing builder; this module only
orders / shows / hides for presentation and reports *why*. See docs/green_light_preferences_contract.md.

Two registers of hiding, both VIEW-class (a user action), never a factual or model judgement:
- HIDDEN_BY_USER  — the user hid this lens.
- OUT_OF_SPORT    — the lens does not serve a sport the user selected.
Nothing here removes a lens for a factual/eligibility/model reason (that stays in the builders + the existing
services.nfl_inclusion ELIGIBILITY codes). A governed-model lens is ordered/hidden exactly like any other and
never gains authority.
"""
from __future__ import annotations

import re

FACT = 'fact'
GOVERNED_MODEL = 'governed-model'

# (key, label, classification, scope-tuple, default_order). `key` is stored in prefs; labels are display-only.
LENSES = (
    ('whats_changed',       "What's Changed",            FACT,           ('nfl',),                               10),
    ('heat_map',            'Heat Map',                  FACT,           ('nfl',),                               20),
    ('riding_the_wave',     'Riding the Wave',           FACT,           ('nfl',),                               30),
    ('milestone_streaks',   'Milestone Streaks',         FACT,           ('nfl',),                               40),
    ('market_line_streaks', 'Market-Line Streaks',       FACT,           ('nfl',),                               50),
    ('ats_waves',           'ATS Waves',                 FACT,           ('nfl', 'cfb'),                         60),
    ('matchup_context',     'Matchup Context',           FACT,           ('nfl',),                               70),
    ('injuries_return',     'Injuries / Return Status',  FACT,           ('nfl',),                               80),
    ('weather',             'Weather',                   FACT,           ('nfl',),                               90),
    ('line_movement',       'Line Movement',             FACT,           ('nfl',),                               100),
    ('contradictions',      'Contradictions',            FACT,           ('nfl', 'cfb', 'mlb', 'nba', 'wnba'),   110),
    ('governed_models',     'Governed Research Models',  GOVERNED_MODEL, ('nfl', 'cfb', 'mlb', 'nba', 'wnba'),   120),
)
LENS_KEYS = tuple(l[0] for l in LENSES)
_BY_KEY = {l[0]: l for l in LENSES}
SPORTS = tuple(sorted({s for l in LENSES for s in l[3]}))

# VIEW-class reason codes (a user action), aligned with the VIEW split in services.nfl_inclusion.Reason.
HIDDEN_BY_USER = 'HIDDEN_BY_USER'
OUT_OF_SPORT = 'OUT_OF_SPORT'
VIEW_REASONS = (HIDDEN_BY_USER, OUT_OF_SPORT)

_DENSITIES = ('comfortable', 'compact')
_MARKET_RE = re.compile(r'^[a-z0-9_]{1,40}$')
_MAX_MARKETS = 50


def default_lens_order():
    """The house default order (by declared default_order)."""
    return [l[0] for l in sorted(LENSES, key=lambda x: x[4])]


def lens_label(key):
    row = _BY_KEY.get(key)
    return row[1] if row else key


def lens_classification(key):
    row = _BY_KEY.get(key)
    return row[2] if row else FACT


def lens_scope(key):
    row = _BY_KEY.get(key)
    return row[3] if row else ()


def is_governed_model(key):
    return lens_classification(key) == GOVERNED_MODEL


def _clean_key_list(v):
    """Keep only known lens keys, de-duplicated, preserving first-seen order."""
    if not isinstance(v, (list, tuple)):
        return []
    out, seen = [], set()
    for k in v:
        if isinstance(k, str) and k in _BY_KEY and k not in seen:
            out.append(k)
            seen.add(k)
    return out


def validate_greenlight_prefs(raw):
    """Coerce a stored/submitted prefs dict to a safe canonical form. Unknown lens keys are dropped, unknown
    sports/markets dropped, display validated. NEVER raises — fails safe to an empty dict (= 'use defaults').
    Only validated, provided fields are kept (a missing field means 'default')."""
    if not isinstance(raw, dict):
        return {}
    out = {}
    order = _clean_key_list(raw.get('lens_order'))
    if order:
        out['lens_order'] = order
    hidden = _clean_key_list(raw.get('lens_hidden'))
    if hidden:
        out['lens_hidden'] = hidden
    sports = raw.get('sports')
    if isinstance(sports, (list, tuple)):
        clean = [s for s in dict.fromkeys(sports) if isinstance(s, str) and s in SPORTS]
        if clean:
            out['sports'] = clean
    markets = raw.get('markets')
    if isinstance(markets, (list, tuple)):
        clean = [m for m in dict.fromkeys(markets)
                 if isinstance(m, str) and _MARKET_RE.match(m)][:_MAX_MARKETS]
        if clean:
            out['markets'] = clean
    display = raw.get('display')
    if isinstance(display, dict):
        d = {}
        if display.get('density') in _DENSITIES:
            d['density'] = display['density']
        if isinstance(display.get('why_expanded'), bool):
            d['why_expanded'] = display['why_expanded']
        if d:
            out['display'] = d
    return out


def apply_lens_preferences(available_keys, prefs):
    """PURE presentation logic. `available_keys` is the set of lens keys that actually have content this
    request (the builders decided — we never re-derive or add). Returns a deterministic partition of exactly
    those keys into an ordered visible list and a hidden list with VIEW-class reasons:

        {'order': [key,...],            # full deterministic order of the available keys
         'visible': [key,...],          # ordered, not hidden
         'hidden': [{'key','label','reason','classification'}, ...],
         'hidden_count': int}

    A key is hidden ONLY if the user hid it (HIDDEN_BY_USER) or it is out of the user's selected sports
    (OUT_OF_SPORT). visible + [h['key']] == order (a partition); no key outside `available_keys` ever appears.
    """
    prefs = validate_greenlight_prefs(prefs if isinstance(prefs, dict) else {})
    available = [k for k in default_lens_order() if k in set(available_keys)]  # canonical membership, de-duped
    # deterministic order: user order first (restricted to available), then remaining available in default order
    user_order = [k for k in prefs.get('lens_order', []) if k in available]
    ordered = user_order + [k for k in available if k not in set(user_order)]

    hidden_set = set(prefs.get('lens_hidden', []))
    sports = prefs.get('sports')  # None => no sport filter

    visible, hidden = [], []
    for k in ordered:
        reason = None
        if k in hidden_set:
            reason = HIDDEN_BY_USER
        elif sports and not (set(lens_scope(k)) & set(sports)):
            reason = OUT_OF_SPORT
        if reason:
            hidden.append({'key': k, 'label': lens_label(k), 'reason': reason,
                           'classification': lens_classification(k)})
        else:
            visible.append(k)
    return {'order': ordered, 'visible': visible, 'hidden': hidden, 'hidden_count': len(hidden)}
