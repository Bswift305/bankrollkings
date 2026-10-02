"""Personal bet tracker + CLV -- the credibility piece.

The honest grinder/sharp wants their own graded record: what they bet, at what
price, how it settled, and whether they beat the closing line (CLV). Pure JSON
per user under data/user_bets/<uid>.json; no pandas, no network. All math is
plain and auditable -- ROI is flat-stake net / amount risked, CLV is the implied
probability you locked in vs where the market closed.
"""
import json
import os
import uuid
from datetime import datetime

VALID_RESULTS = ('pending', 'win', 'loss', 'push', 'void')
SETTLED = ('win', 'loss', 'push')
VALID_SPORTS = ('NFL', 'CFB', 'MLB', 'NBA', 'WNBA', 'Other')


def _path(data_dir, uid):
    return os.path.join(str(data_dir), 'user_bets', f'{uid}.json')


def load_bets(data_dir, uid):
    """This user's logged bets, newest first. [] if none / unreadable."""
    if not uid:
        return []
    try:
        with open(_path(data_dir, uid), encoding='utf-8') as fh:
            d = json.load(fh) or {}
        bets = d.get('bets') if isinstance(d, dict) else d
        return bets if isinstance(bets, list) else []
    except (OSError, ValueError):
        return []


def _save(data_dir, uid, bets):
    p = _path(data_dir, uid)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'w', encoding='utf-8') as fh:
        json.dump({'bets': bets}, fh)


def american_to_decimal(odds):
    o = float(odds)
    return 1 + o / 100.0 if o > 0 else 1 + 100.0 / abs(o)


def implied_prob(odds):
    """American odds -> implied win probability (with vig, as priced)."""
    o = float(odds)
    return 100.0 / (o + 100.0) if o > 0 else abs(o) / (abs(o) + 100.0)


def _valid_american(v):
    try:
        iv = int(v)
    except (TypeError, ValueError):
        return None
    return iv if abs(iv) >= 100 else None


def add_bet(data_dir, uid, sport, description, selection, odds, stake,
            closing_odds=None, placed=None, book=''):
    """Append a pending bet. Returns the bet dict, or None on invalid odds/stake."""
    if not uid:
        return None
    o = _valid_american(odds)
    if o is None:
        return None
    try:
        st = round(float(stake), 2)
    except (TypeError, ValueError):
        return None
    if st <= 0:
        return None
    co = _valid_american(closing_odds) if closing_odds not in (None, '') else None
    sport = sport if sport in VALID_SPORTS else 'Other'
    bet = {
        'id': uuid.uuid4().hex[:12],
        'placed': (placed or datetime.utcnow().strftime('%Y-%m-%d'))[:10],
        'sport': sport,
        'description': str(description or '').strip()[:140],
        'selection': str(selection or '').strip()[:140],
        'odds': o,
        'stake': st,
        'closing_odds': co,
        'book': str(book or '').strip()[:40],
        'result': 'pending',
        'logged': datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC'),
    }
    bets = load_bets(data_dir, uid)
    bets.insert(0, bet)
    _save(data_dir, uid, bets)
    return bet


def settle_bet(data_dir, uid, bet_id, result):
    if result not in VALID_RESULTS:
        return False
    bets = load_bets(data_dir, uid)
    ok = False
    for b in bets:
        if b.get('id') == bet_id:
            b['result'] = result
            ok = True
            break
    if ok:
        _save(data_dir, uid, bets)
    return ok


def set_closing(data_dir, uid, bet_id, closing_odds):
    """Record / update the closing line for a bet so CLV can be computed."""
    co = _valid_american(closing_odds) if closing_odds not in (None, '') else None
    bets = load_bets(data_dir, uid)
    ok = False
    for b in bets:
        if b.get('id') == bet_id:
            b['closing_odds'] = co
            ok = True
            break
    if ok:
        _save(data_dir, uid, bets)
    return ok


def delete_bet(data_dir, uid, bet_id):
    bets = load_bets(data_dir, uid)
    kept = [b for b in bets if b.get('id') != bet_id]
    if len(kept) != len(bets):
        _save(data_dir, uid, kept)
        return True
    return False


def bet_profit(b):
    """Flat-stake profit (excl. returned stake) for a settled bet; 0 for push/void/pending."""
    r = b.get('result')
    stake = float(b.get('stake') or 0)
    if r == 'win':
        return stake * (american_to_decimal(b.get('odds')) - 1)
    if r == 'loss':
        return -stake
    return 0.0


def _clv_points(b):
    """CLV in implied-probability points: (close implied %) - (your implied %). Positive =
    you locked a better price than the market closed at. None if no closing line."""
    co = b.get('closing_odds')
    if not co:
        return None
    return (implied_prob(co) - implied_prob(b['odds'])) * 100.0


def summarize(bets):
    """Record, flat-stake ROI, and CLV over a list of bets. Honest and auditable."""
    settled = [b for b in bets if b.get('result') in SETTLED]
    wins = sum(1 for b in settled if b['result'] == 'win')
    losses = sum(1 for b in settled if b['result'] == 'loss')
    pushes = sum(1 for b in settled if b['result'] == 'push')
    staked = sum(float(b.get('stake') or 0) for b in settled if b['result'] != 'push')
    net = sum(bet_profit(b) for b in settled)
    roi = (net / staked * 100.0) if staked > 0 else None
    decided = wins + losses
    win_pct = (wins / decided * 100.0) if decided else None

    clv_bets = [b for b in bets if b.get('closing_odds')]
    clv_vals = [_clv_points(b) for b in clv_bets]
    clv_avg = (sum(clv_vals) / len(clv_vals)) if clv_vals else None
    beat = sum(1 for v in clv_vals if v is not None and v > 0)
    beat_rate = (beat / len(clv_vals) * 100.0) if clv_vals else None

    by_sport = {}
    for b in settled:
        s = b.get('sport') or 'Other'
        d = by_sport.setdefault(s, {'w': 0, 'l': 0, 'p': 0, 'staked': 0.0, 'net': 0.0})
        d['w'] += b['result'] == 'win'
        d['l'] += b['result'] == 'loss'
        d['p'] += b['result'] == 'push'
        if b['result'] != 'push':
            d['staked'] += float(b.get('stake') or 0)
        d['net'] += bet_profit(b)
    sport_rows = []
    for s, d in by_sport.items():
        sport_rows.append({
            'sport': s,
            'record': f"{d['w']}-{d['l']}" + (f"-{d['p']}" if d['p'] else ''),
            'net': round(d['net'], 2),
            'roi': (round(d['net'] / d['staked'] * 100.0, 1) if d['staked'] > 0 else None),
        })
    sport_rows.sort(key=lambda r: (r['roi'] is None, -(r['roi'] or 0)))

    return {
        'n': len(bets),
        'settled': len(settled),
        'pending': sum(1 for b in bets if b.get('result') == 'pending'),
        'wins': wins, 'losses': losses, 'pushes': pushes,
        'record': f"{wins}-{losses}" + (f"-{pushes}" if pushes else ''),
        'win_pct': (round(win_pct, 1) if win_pct is not None else None),
        'staked': round(staked, 2),
        'net': round(net, 2),
        'roi': (round(roi, 1) if roi is not None else None),
        'clv_n': len(clv_bets),
        'clv_avg': (round(clv_avg, 2) if clv_avg is not None else None),
        'beat_rate': (round(beat_rate, 1) if beat_rate is not None else None),
        'by_sport': sport_rows,
    }


def decorate(bets):
    """Attach display helpers (profit, clv points) to each bet for templating."""
    out = []
    for b in bets:
        d = dict(b)
        d['profit'] = round(bet_profit(b), 2) if b.get('result') in SETTLED else None
        clv = _clv_points(b)
        d['clv'] = round(clv, 1) if clv is not None else None
        out.append(d)
    return out
