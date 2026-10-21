"""Green Light lens adapters — the common envelope + pure framework (no app import).

Every lens builder (12 of them, varied shapes) is wrapped by an adapter in app.py that reads the builder's
CANONICAL factual membership and hands it to `build_envelope` here. This module owns the uniform contract so
the workspace renders meaningful compact summaries without leaving Green Light, derives the three counts from
the SAME canonical universe, proves Green Light neither adds nor suppresses qualifying records (source vs GL
universe hash), and isolates a failing lens (it abstains cleanly instead of breaking the page).

An adapter supplies a `membership` list of canonical item dicts, each:
    {'id': <stable str>, 'sport': <str>, 'market': <str|None>, 'label': <str>, 'why': <str>,
     'data_through': <str|None>, 'contradiction': <bool>, 'unavailable': <bool>, 'stale': <bool>,
     'gated': <bool>}
`build_envelope` computes the count, the preference-eligible subset, availability, the universe hashes and a
compact item view. It never drops a record from the canonical universe — preference filtering only changes
the *eligible* subset and the per-lens "hidden by your sport/market" count, never `membership_count`.
"""
from __future__ import annotations

import hashlib

# availability states (never a silent zero: an empty/failed lens is unavailable|gated|stale, not "0 fine")
AVAILABLE = 'available'
PARTIAL = 'partial'
UNAVAILABLE = 'unavailable'
STALE = 'stale'
GATED = 'gated'
AVAILABILITY_STATES = (AVAILABLE, PARTIAL, UNAVAILABLE, STALE, GATED)

# preference-visibility (VIEW-class, mirrors services.green_light_lenses)
SHOWN = 'shown'
HIDDEN_BY_USER = 'hidden_by_user'
OUT_OF_SPORT = 'out_of_sport'

MAX_DETAIL_ITEMS = 40


def _hash_ids(ids):
    """Stable hash of a membership id SET (order-independent): the canonical-universe fingerprint."""
    norm = sorted({str(i) for i in ids})
    return 'u_' + hashlib.sha256('\n'.join(norm).encode('utf-8')).hexdigest()[:20]


def _item_matches_pref(item, sports, markets):
    """An item is pref-eligible when its sport is among the selected sports (or none selected) AND, when the
    user selected markets, its market is among them (an item with no market is not excluded by a market filter
    only if it also has no sport constraint conflict). Sport filter dominates; market narrows within sport."""
    if sports:
        if (item.get('sport') or '').lower() not in {s.lower() for s in sports}:
            return False
    if markets:
        mk = item.get('market')
        if mk is not None and mk not in markets:
            return False
    return True


def build_envelope(key, label, classification, sport, market, membership, *, source='', data_through='',
                   availability=None, context_note='', prefs=None, include_items=False,
                   preference_visibility=SHOWN, why=''):
    """Assemble one lens' envelope from its canonical membership. Pure. `availability` may be forced by the
    adapter (e.g. the builder reported unavailable/stale/gated); otherwise it is derived."""
    prefs = prefs or {}
    membership = list(membership or [])
    ids = [m.get('id') for m in membership]
    universe_hash = _hash_ids(ids)

    sports = prefs.get('sports') or []
    markets = prefs.get('markets') or []
    eligible = [m for m in membership if _item_matches_pref(m, sports, markets)]
    filtered_by_pref = len(membership) - len(eligible)

    unavailable_items = [m for m in membership if m.get('unavailable') or m.get('stale') or m.get('gated')]
    contradictions = sum(1 for m in membership if m.get('contradiction'))

    if availability is None:
        if not membership:
            availability = UNAVAILABLE
        elif all(m.get('gated') for m in membership):
            availability = GATED
        elif unavailable_items and len(unavailable_items) == len(membership):
            availability = STALE if all(m.get('stale') for m in unavailable_items) else UNAVAILABLE
        elif unavailable_items:
            availability = PARTIAL
        else:
            availability = AVAILABLE
    if availability not in AVAILABILITY_STATES:
        availability = UNAVAILABLE

    # GL presents EXACTLY the canonical membership as its universe (it never adds or silently suppresses);
    # gl_hash must equal universe_hash. Preference filtering changes only the eligible subset, not the universe.
    gl_hash = _hash_ids(ids)

    env = {
        'key': key, 'label': label, 'classification': classification,
        'governed': classification == 'governed-model',
        'sport': sport, 'market': market,
        'availability': availability,
        'membership_count': len(membership),       # canonical universe size
        'eligible_count': len(eligible),           # after the user's sport/market preference
        'filtered_by_pref': filtered_by_pref,      # eligible items hidden by sport/market (>=0)
        'unavailable_count': len(unavailable_items),
        'contradictions': contradictions,
        'source': source, 'data_through': data_through,
        'why': why or 'You kept this lens visible.',
        'preference_visibility': preference_visibility,
        'context_note': context_note,
        'universe_hash': universe_hash,
        'gl_hash': gl_hash,
        'no_suppression': gl_hash == universe_hash,
        'items': [_compact(m) for m in membership[:MAX_DETAIL_ITEMS]] if include_items else [],
        'item_cap': MAX_DETAIL_ITEMS,
    }
    return env


def _compact(m):
    """A compact, display-safe item view with its own explainer fields (no raw builder internals)."""
    state = AVAILABLE
    if m.get('gated'):
        state = GATED
    elif m.get('stale'):
        state = STALE
    elif m.get('unavailable'):
        state = UNAVAILABLE
    return {'id': str(m.get('id', '')), 'sport': m.get('sport'), 'market': m.get('market'),
            'label': m.get('label', ''), 'why': m.get('why', ''), 'data_through': m.get('data_through'),
            'contradiction': bool(m.get('contradiction')), 'state': state}


def abstain_envelope(key, label, classification, sport='', market=None, reason='adapter_error'):
    """A clean abstention envelope: one failing/absent lens shows as unavailable with a reason and NEVER
    breaks the workspace. membership is empty, counts are zero-but-labeled-unavailable (not a silent zero)."""
    return build_envelope(key, label, classification, sport, market, [], availability=UNAVAILABLE,
                          context_note=reason, source='', data_through='')


def safe_adapter(key, label, classification, fn, sport='', market=None):
    """Run an adapter callable; any exception -> a clean abstention envelope (workspace unaffected)."""
    try:
        env = fn()
        if not isinstance(env, dict) or 'availability' not in env:
            return abstain_envelope(key, label, classification, sport, market, 'adapter_bad_envelope')
        return env
    except Exception as exc:  # noqa: BLE001 -- isolation is the whole point
        return abstain_envelope(key, label, classification, sport, market,
                                f'adapter_exception:{type(exc).__name__}')


def aggregate_counts(visible_envs, out_of_sport_envs, hidden_by_user_keys):
    """The THREE real, never-combined counts, derived from the SAME canonical universe the envelopes carry:
      1. lenses_hidden_by_user         : lens-level (the user hid the lens).
      2. eligible_items_hidden_by_pref : item-level — items removed by the sport/market filter. That is the
                                         filtered_by_pref of each VISIBLE lens PLUS the whole membership of
                                         each lens hidden because it is out of the user's sports (all its
                                         items are filtered).
      3. items_unavailable_by_gate     : item-level — unavailable/stale/gated items in VISIBLE lenses, plus
                                         a wholly-unavailable visible lens counted as >=1 (never a silent 0).
    """
    items_filtered = (sum(e.get('filtered_by_pref', 0) for e in visible_envs)
                      + sum(e.get('membership_count', 0) for e in out_of_sport_envs))
    items_unavailable = 0
    for e in visible_envs:
        if e.get('availability') in (UNAVAILABLE, GATED, STALE) and e.get('membership_count', 0) == 0:
            items_unavailable += 1  # a wholly-unavailable lens is not a silent zero
        else:
            items_unavailable += e.get('unavailable_count', 0)
    return {
        'lenses_hidden_by_user': len(set(hidden_by_user_keys)),
        'eligible_items_hidden_by_pref': items_filtered,
        'items_unavailable_by_gate': items_unavailable,
    }
