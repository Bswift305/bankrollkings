"""Shared streak-explainer NORMALIZED view-model (pure, no app import).

ONE common shape every live streak surface renders, instead of template-specific conditionals. Each family's
builder row is mapped into the same model; a field the source cannot provide is labeled ``unavailable`` and
NEVER synthesized. Governed-model status is carried SEPARATELY from factual membership. The Jinja partial
``templates/_streak_explainer.html`` renders this model identically everywhere.

Model fields: family · threshold · direction · current_streak · current_season · counted_events[] ·
excluded_events[] · source · data_through · freshness · availability · membership_reason · model_status.
Entity names inside the explainer are linked by the centralized resolver at the call site (not here).
"""
from __future__ import annotations

UNAVAILABLE = 'unavailable'
FACTUAL = 'factual membership — not a governed model'


def _val(v):
    return v if v not in (None, '') else UNAVAILABLE


def _event(date=None, week=None, opponent=None, value=None, line=None, result=None):
    return {'date': _val(date), 'week': _val(week), 'opponent': _val(opponent),
            'value': _val(value), 'line': _val(line), 'result': _val(result)}


def _ats_result_word(s):
    """Map a per-game ATS/total result token (builder evidence) to an honest word; an unknown
    token is passed through as-is (never invented)."""
    return {'W': 'cover', 'L': 'loss', 'P': 'push', '1': 'cover', '-1': 'loss', '0': 'push',
            'O': 'over', 'U': 'under'}.get(str(s).strip().upper(), str(s))


def normalize(family, row, meta=None):
    """Map a streak builder's `row` into the common explainer model. `meta` carries surface-level context
    (source, data_through, freshness, season) the row may not include. Missing -> UNAVAILABLE, never faked."""
    row = row or {}
    meta = meta or {}
    m = {'family': family, 'threshold': UNAVAILABLE, 'direction': UNAVAILABLE, 'current_streak': UNAVAILABLE,
         'current_season': _val(meta.get('season')), 'counted_events': UNAVAILABLE, 'excluded_events': [],
         'source': _val(meta.get('source')), 'data_through': _val(meta.get('data_through')),
         'freshness': _val(meta.get('freshness')), 'availability': _val(row.get('availability_state')),
         'membership_reason': UNAVAILABLE, 'model_status': _val(meta.get('model_status')) if meta.get('model_status') else FACTUAL}

    if family == 'milestone':
        m['threshold'] = _val(row.get('threshold'))
        m['direction'] = 'at or above threshold'
        m['current_streak'] = _val(row.get('run'))
        games = row.get('games') or []
        if games:
            m['counted_events'] = [_event(week=g.get('week'), opponent=g.get('opponent'),
                                          value=g.get('value'), line=g.get('threshold'), result='cleared')
                                   for g in games]
            if games[-1].get('season') is not None:
                m['current_season'] = games[-1]['season']
        m['membership_reason'] = (f"{row.get('run', '?')} straight games at/above "
                                  f"{row.get('threshold', '?')} {row.get('stat_label', '')}").strip()

    elif family in ('prop', 'market_line', 'wave'):
        m['threshold'] = _val(row.get('line'))
        m['direction'] = _val(row.get('side'))
        m['current_streak'] = _val(row.get('streak'))
        # this source gives the run's WEEKS (weeks_label) but not per-game values -> per-game events unavailable
        m['counted_events'] = UNAVAILABLE
        m['membership_reason'] = _val(row.get('status_label')) if row.get('status_label') else \
            (f"{row.get('streak', '?')} straight {row.get('side', '')}").strip()

    elif family == 'ats':
        # Generalized across the cover/fade spread boards AND over/under totals boards. The run
        # field varies by builder (`cover_streak` on the NFL ATS wave, `streak` on the CFB board);
        # `kind` (meta or row) distinguishes spread vs total. Builder evidence only.
        kind = str(meta.get('kind') or row.get('kind') or 'cover').lower()
        m['threshold'] = 'the total' if kind in ('over', 'under') else 'the spread'
        m['direction'] = kind
        streak = row.get('cover_streak')
        if streak is None:
            streak = row.get('streak')
        m['current_streak'] = _val(streak)
        results = row.get('results')
        if results is None and isinstance(row.get('last'), str):
            results = [t for t in row['last'].replace(',', ' ').split() if t]
        if results:
            m['counted_events'] = [_event(result=_ats_result_word(s)) for s in results]
        else:
            m['counted_events'] = UNAVAILABLE   # source carries only the run, not per-game results
        noun = {'cover': 'covers', 'fade': 'non-covers', 'over': 'overs', 'under': 'unders'}.get(kind, kind)
        m['membership_reason'] = (f"{streak} straight {noun}" if streak is not None else UNAVAILABLE)

    elif family == 'hot_hand':
        m['threshold'] = _val(row.get('line'))
        m['direction'] = 'clear the line'
        m['current_streak'] = _val(row.get('streak'))
        m['counted_events'] = UNAVAILABLE  # the row summarizes the run; per-game values are not carried here
        m['membership_reason'] = _val(row.get('status_label')) if row.get('status_label') else \
            (f"{row.get('streak', '?')} straight clears")

    return m
