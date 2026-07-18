from __future__ import annotations

import ast
import re

from pathlib import Path
from typing import Callable

import pandas as pd


FilterReviewHistoryScope = Callable[[list[dict], str], list[dict]]
SummarizeBetReview = Callable[[list[dict]], dict]
RecalibrateSavedConfidence = Callable[[float], float]
SavedConfidenceBucketLabel = Callable[[float], str]
GradeCandidateArchiveRows = Callable[[pd.DataFrame, dict], pd.DataFrame]
SummarizeCandidateArchive = Callable[[pd.DataFrame], dict]
FLOOR_PLAY_INDEX_PATH = Path(__file__).resolve().parents[1] / 'data' / 'tracking' / 'Floor_Play_Index.csv'
TRACKING_DIR = Path(__file__).resolve().parents[1] / 'data' / 'tracking'
PLAYER_PROFILE_INDEX_PATH = TRACKING_DIR / 'Player_Profile_Index.csv'
STREAK_HEAT_INDEX_PATH = TRACKING_DIR / 'Streak_Heat_Index.csv'
ALL_PROP_RESULT_PATHS = {
    'NBA': TRACKING_DIR / 'NBA_AllPropResults.csv',
    'WNBA': TRACKING_DIR / 'WNBA_AllPropResults.csv',
    'MLB': TRACKING_DIR / 'MLB_AllPropResults.csv',
    'NFL': TRACKING_DIR / 'NFL_AllPropResults.csv',
    'NCAAF': TRACKING_DIR / 'NCAAF_AllPropResults.csv',
}
_REVIEW_RUNTIME_CACHE: dict[tuple, object] = {}


def _clean_display_value(value):
    if isinstance(value, dict):
        return {key: _clean_display_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_clean_display_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_clean_display_value(item) for item in value)
    try:
        if value is None or pd.isna(value):
            return None
    except Exception:
        pass
    if isinstance(value, str):
        text = value.strip()
        if not text or re.search(r'\bnan\b', text, flags=re.IGNORECASE):
            return ''
        if text.lower() in {'none', 'null'}:
            return ''
        return text
    return value


def _path_token(path: Path) -> tuple:
    try:
        if not path.exists():
            return (str(path), None, None)
        stat = path.stat()
        return (str(path), int(stat.st_mtime), int(stat.st_size))
    except Exception:
        return (str(path), None, None)


def _all_prop_file_token() -> tuple:
    return tuple(_path_token(path) for path in ALL_PROP_RESULT_PATHS.values())


def _latest_source_mtime(paths: list[Path]) -> int:
    mtimes = [token[1] for token in (_path_token(path) for path in paths) if token[1] is not None]
    return max(mtimes) if mtimes else 0


def _artifact_is_fresh(artifact_path: Path, source_paths: list[Path]) -> bool:
    artifact_token = _path_token(artifact_path)
    artifact_mtime = artifact_token[1]
    if artifact_mtime is None:
        return False
    return int(artifact_mtime) >= int(_latest_source_mtime(source_paths))


def _df_token(df: pd.DataFrame | None) -> tuple:
    if df is None or df.empty:
        return (0, (), '')
    date_bits = []
    for column in ['SnapshotWrittenAt', 'SavedAt', 'ResultDate', 'SnapshotDate']:
        if column in df.columns:
            try:
                value = df[column].dropna().astype(str).max()
            except Exception:
                value = ''
            date_bits.append((column, value))
    return (int(len(df)), tuple(str(col) for col in df.columns), tuple(date_bits))


def normalize_history_scope(history_scope: str) -> str:
    scope = str(history_scope or 'native').strip().lower()
    return scope if scope in {'native', 'legacy', 'all'} else 'native'


def filter_bet_review_tickets(
    saved_tickets: list[dict],
    *,
    history_scope: str,
    start_date: str = '',
    end_date: str = '',
    result_filter: str = 'all',
    stat_filter: str = 'ALL',
    structure_filter: str = 'all',
    filter_review_history_scope: FilterReviewHistoryScope,
) -> list[dict]:
    filtered_tickets = list(saved_tickets or [])
    normalized_scope = normalize_history_scope(history_scope)
    start_date = str(start_date or '').strip()
    end_date = str(end_date or '').strip()
    result_filter = str(result_filter or 'all').strip().lower()
    stat_filter = str(stat_filter or 'ALL').strip().upper()
    structure_filter = str(structure_filter or 'all').strip()

    if start_date:
        start_dt = pd.to_datetime(start_date, errors='coerce')
        if not pd.isna(start_dt):
            filtered_tickets = [
                t for t in filtered_tickets
                if pd.to_datetime(t.get('saved_at', ''), errors='coerce') >= start_dt
            ]
    if end_date:
        end_dt = pd.to_datetime(end_date, errors='coerce')
        if not pd.isna(end_dt):
            cutoff = end_dt + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
            filtered_tickets = [
                t for t in filtered_tickets
                if pd.to_datetime(t.get('saved_at', ''), errors='coerce') <= cutoff
            ]
    if result_filter != 'all':
        filtered_tickets = [
            t for t in filtered_tickets
            if str(
                t.get('analysis', {}).get('results_summary', {}).get('ticket_state', '')
            ).lower().replace(' ', '-') == result_filter
        ]
    if stat_filter != 'ALL':
        filtered_tickets = [
            t for t in filtered_tickets
            if any(str(p.get('stat', '')).upper() == stat_filter for p in t.get('picks', []))
        ]
    if structure_filter != 'all':
        filtered_tickets = [
            t for t in filtered_tickets
            if t.get('analysis', {}).get('hindsight_use', {}).get('label') == structure_filter
        ]
    return filter_review_history_scope(filtered_tickets, normalized_scope)


def build_bet_review_context(
    saved_tickets: list[dict],
    *,
    history_scope: str,
    start_date: str = '',
    end_date: str = '',
    result_filter: str = 'all',
    stat_filter: str = 'ALL',
    structure_filter: str = 'all',
    filter_review_history_scope: FilterReviewHistoryScope,
    summarize_bet_review: SummarizeBetReview,
) -> dict:
    normalized_scope = normalize_history_scope(history_scope)
    filtered_tickets = filter_bet_review_tickets(
        saved_tickets,
        history_scope=normalized_scope,
        start_date=start_date,
        end_date=end_date,
        result_filter=result_filter,
        stat_filter=stat_filter,
        structure_filter=structure_filter,
        filter_review_history_scope=filter_review_history_scope,
    )
    available_stats = sorted(
        {
            str(p.get('stat', '')).upper()
            for t in (saved_tickets or [])
            for p in t.get('picks', [])
            if str(p.get('stat', '')).strip()
        }
    )
    available_structures = sorted(
        {
            t.get('analysis', {}).get('hindsight_use', {}).get('label')
            for t in (saved_tickets or [])
            if t.get('analysis', {}).get('hindsight_use', {}).get('label')
        }
    )
    history_counts = {
        'all': len(saved_tickets or []),
        'native': len(filter_review_history_scope(list(saved_tickets or []), 'native')),
        'legacy': len(filter_review_history_scope(list(saved_tickets or []), 'legacy')),
    }
    return {
        'saved_tickets': filtered_tickets,
        'review': summarize_bet_review(filtered_tickets),
        'history_scope': normalized_scope,
        'history_counts': history_counts,
        'available_stats': available_stats,
        'available_structures': available_structures,
        'start_date': str(start_date or '').strip(),
        'end_date': str(end_date or '').strip(),
        'result_filter': str(result_filter or 'all').strip().lower(),
        'stat_filter': str(stat_filter or 'ALL').strip().upper(),
        'structure_filter': str(structure_filter or 'all').strip(),
    }


def build_bet_review_export_rows(filtered_tickets: list[dict]) -> list[dict]:
    rows = []
    for ticket in filtered_tickets or []:
        rows.append({
            'TicketId': ticket.get('ticket_id', ''),
            'SavedAt': ticket.get('saved_at', ''),
            'Label': ticket.get('label', ''),
            'LegCount': ticket.get('leg_count'),
            'Tier1Count': ticket.get('tier1_count'),
            'AvgConfidence': ticket.get('avg_confidence'),
            'ModelVersion': ticket.get('model_version', ''),
            'ConfidenceScale': ticket.get('confidence_scale', ''),
            'TicketState': ticket.get('analysis', {}).get('results_summary', {}).get('ticket_state', ''),
            'Result': ticket.get('result', ''),
            'BestUse': ticket.get('analysis', {}).get('best_use', {}).get('label', ''),
            'HindsightUse': ticket.get('analysis', {}).get('hindsight_use', {}).get('label', ''),
            'ModelReview': ticket.get('analysis', {}).get('model_review', {}).get('label', ''),
            'Stake': ticket.get('stake', 0),
            'Payout': ticket.get('payout', 0),
            'Profit': ticket.get('money', {}).get('profit', 0),
            'ROI': ticket.get('money', {}).get('roi'),
        })
    return rows


def build_bet_review_model_export_rows(
    filtered_tickets: list[dict],
    *,
    recalibrate_saved_confidence: RecalibrateSavedConfidence,
    saved_confidence_bucket_label: SavedConfidenceBucketLabel,
    current_confidence_max: float,
) -> list[dict]:
    rows = []
    for ticket in filtered_tickets or []:
        for pick in ticket.get('picks', []):
            outcome = str(pick.get('outcome_state', 'pending')).strip().lower()
            if outcome not in {'win', 'loss', 'push'}:
                continue
            confidence = float(pick.get('raw_confidence', pick.get('confidence', 0)) or 0)
            effective_confidence = float(
                pick.get('effective_confidence', recalibrate_saved_confidence(confidence)) or 0
            )
            rows.append({
                'TicketId': ticket.get('ticket_id', ''),
                'SavedAt': ticket.get('saved_at', ''),
                'Label': ticket.get('label', ''),
                'Mode': ticket.get('mode', ''),
                'ModelVersion': ticket.get('model_version', ''),
                'ConfidenceScale': ticket.get('confidence_scale', ''),
                'Player': str(pick.get('player', '')).strip(),
                'Team': str(pick.get('team', '')).strip().upper(),
                'Stat': str(pick.get('stat', '')).strip().upper(),
                'Direction': str(pick.get('direction', '')).strip().upper(),
                'Line': float(pick.get('line', 0) or 0),
                'Confidence': confidence,
                'EffectiveConfidence': effective_confidence,
                'ConfidenceBucket': saved_confidence_bucket_label(effective_confidence),
                'LegacyScale': bool(pick.get('legacy_confidence_scale', confidence > current_confidence_max)),
                'Tier': str(pick.get('tier', '')).strip(),
                'Outcome': outcome.title(),
                'ActualValue': pick.get('actual_value'),
                'GameDate': str(pick.get('game_date', '')).strip(),
                'Matchup': str(pick.get('resolved_matchup', pick.get('matchup', ''))).strip(),
                'TicketState': ticket.get('analysis', {}).get('results_summary', {}).get('ticket_state', ''),
                'BestUse': ticket.get('analysis', {}).get('best_use', {}).get('label', ''),
                'HindsightUse': ticket.get('analysis', {}).get('hindsight_use', {}).get('label', ''),
                'ModelReview': ticket.get('analysis', {}).get('model_review', {}).get('label', ''),
            })
    return rows


def load_floor_play_index() -> pd.DataFrame:
    if not FLOOR_PLAY_INDEX_PATH.exists():
        return pd.DataFrame()
    cache_key = ('floor_play_index', _path_token(FLOOR_PLAY_INDEX_PATH))
    cached = _REVIEW_RUNTIME_CACHE.get(cache_key)
    if cached is not None:
        return cached.copy()
    try:
        index = pd.read_csv(FLOOR_PLAY_INDEX_PATH, low_memory=False)
    except Exception:
        return pd.DataFrame()
    if index.empty:
        return pd.DataFrame()
    if 'IsFloorPlay' in index.columns:
        index['IsFloorPlay'] = index['IsFloorPlay'].astype(str).str.lower().isin({'true', '1', 'yes'})
    else:
        index['IsFloorPlay'] = index.get('Method', pd.Series(dtype=str)).fillna('').astype(str).str.contains('floor', case=False, na=False)
    if 'Hit_Binary' not in index.columns:
        index['Hit_Binary'] = index.get('OutcomeState', pd.Series(dtype=str)).map({'Hit': 1, 'Miss': 0})
    if not {'ReviewTier', 'FailureReason', 'FailureSignals'}.issubset(index.columns):
        index = enrich_candidate_review_rows(index)
    if 'FloorReliability' not in index.columns:
        index = apply_floor_reliability(index, build_floor_reliability_table(index))
    _REVIEW_RUNTIME_CACHE[cache_key] = index.copy()
    return index


def load_all_prop_results_for_review() -> pd.DataFrame:
    cache_key = ('all_prop_results', _all_prop_file_token())
    cached = _REVIEW_RUNTIME_CACHE.get(cache_key)
    if cached is not None:
        return cached.copy()
    frames = []
    for sport, path in ALL_PROP_RESULT_PATHS.items():
        if not path.exists() or path.stat().st_size == 0:
            continue
        try:
            df = pd.read_csv(path, low_memory=False)
        except Exception:
            continue
        if df.empty:
            continue
        if 'Sport' not in df.columns:
            df['Sport'] = sport
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    combined = pd.concat(frames, ignore_index=True, sort=False)
    combined = enrich_candidate_review_rows(combined)
    _REVIEW_RUNTIME_CACHE[cache_key] = combined.copy()
    return combined


def _missed_prop_key(row: pd.Series) -> tuple:
    return (
        str(row.get('SnapshotDate') or '').strip(),
        str(row.get('Sport') or '').strip().upper(),
        str(row.get('Player') or '').strip().lower(),
        str(row.get('Stat') or '').strip().upper(),
        str(row.get('Direction') or '').strip().upper(),
        str(row.get('Line') or '').strip(),
        str(row.get('Matchup') or '').strip().lower(),
    )


def _clean_review_value(value) -> str:
    if value is None:
        return ''
    try:
        if pd.isna(value):
            return ''
    except Exception:
        pass
    text = str(value).strip()
    return '' if text.lower() in {'nan', 'none', 'null'} else text


def calculate_missed_opportunity_grade(row: pd.Series) -> tuple[int, str, list[str]]:
    score = 0
    reasons: list[str] = []

    confidence = pd.to_numeric(row.get('Confidence'), errors='coerce')
    if pd.notna(confidence):
        if confidence >= 90:
            score += 46
            reasons.append(f"{confidence:.1f} confidence")
        elif confidence >= 80:
            score += 40
            reasons.append(f"{confidence:.1f} confidence")
        elif confidence >= 70:
            score += 30
            reasons.append(f"{confidence:.1f} confidence")
        elif confidence >= 60:
            score += 18
            reasons.append(f"{confidence:.1f} confidence")

    bet_tier = _clean_review_value(row.get('BetTier')) or _clean_review_value(row.get('ReviewTier'))
    if bet_tier == 'Tier 1':
        score += 18
        reasons.append('Tier 1')
    elif bet_tier == 'Tier 2':
        score += 12
        reasons.append('Tier 2')
    elif bet_tier == 'Tier 3':
        score += 6
        reasons.append('Tier 3')

    market_gate = str(row.get('MarketGate') or '').strip().upper()
    if market_gate == 'CLEAR':
        score += 12
        reasons.append('clear market gate')
    elif market_gate == 'HOLD':
        score -= 6
        reasons.append('market hold')

    volatility = str(row.get('VolatilityFlag') or '').strip().upper()
    if volatility == 'STABLE':
        score += 8
        reasons.append('stable volatility')
    elif volatility == 'HIGH':
        score -= 8
        reasons.append('high volatility')
    elif volatility == 'ELEVATED':
        score -= 3
        reasons.append('elevated volatility')

    market_depth = str(row.get('MarketDepthBucket') or '').strip().lower()
    book_count = pd.to_numeric(row.get('BookCount'), errors='coerce')
    if 'multi' in market_depth or (pd.notna(book_count) and book_count >= 3):
        score += 14
        reasons.append(f"{int(book_count) if pd.notna(book_count) else 'multi'} books")
    elif 'two' in market_depth or (pd.notna(book_count) and book_count == 2):
        score += 10
        reasons.append('two-book support')
    elif 'single' in market_depth or (pd.notna(book_count) and book_count <= 1):
        score += 2
        reasons.append('single-book market')

    move_bucket = str(row.get('MarketMoveBucket') or '').strip().lower()
    if 'toward' in move_bucket:
        score += 8
        reasons.append('line moved toward play')
    elif 'against' in move_bucket:
        score -= 5
        reasons.append('line moved against play')

    edge_pct = pd.to_numeric(row.get('EdgePct'), errors='coerce')
    if pd.notna(edge_pct):
        if edge_pct >= 15:
            score += 8
            reasons.append(f"{edge_pct:.1f}% edge")
        elif edge_pct >= 8:
            score += 5
            reasons.append(f"{edge_pct:.1f}% edge")

    situations = str(row.get('Situations') or '').upper()
    risk_terms = ['CONTRADICTION', 'AVOID', 'PASS', 'HIGH VOL', 'SINGLE BOOK', 'WIDE RANGE']
    if any(term in situations for term in risk_terms):
        score -= 8
        reasons.append('risk tag present')
    else:
        score += 6
        score += 8
        reasons.append('no obvious contradiction tag')

    sample_mode = _clean_review_value(row.get('SampleMode')).lower()
    method = _clean_review_value(row.get('Method')).lower()
    if sample_mode in {'available', 'full_board'} or method in {'available props', 'main board'}:
        score += 8
        reasons.append('full-board hit')

    method_tags = str(row.get('MarketTags') or row.get('MethodLabels') or '').upper()
    if 'ANCHOR' in method_tags:
        score += 12
        reasons.append('anchor signal')
    if 'CONFIRMED' in method_tags or 'MULTI-BOOK' in method_tags:
        score += 6
        reasons.append('confirmed market support')
    if 'CALIBRATED+' in method_tags:
        score += 6
        reasons.append('calibrated plus tag')

    score = int(max(0, min(100, round(score))))
    if score >= 85:
        label = 'A+'
    elif score >= 70:
        label = 'A'
    elif score >= 55:
        label = 'B'
    elif score >= 40:
        label = 'C'
    else:
        label = 'D'
    return score, label, reasons[:5]


def _missed_winner_candidates(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    working = df.copy()
    for column in ['Method', 'OutcomeState', 'Sport', 'Stat', 'Direction', 'Player', 'Matchup', 'SnapshotDate']:
        if column not in working.columns:
            working[column] = ''
        working[column] = working[column].fillna('').astype(str).str.strip()
    methods = working['Method'].str.lower()
    sample_mode = working.get('SampleMode', pd.Series('', index=working.index)).fillna('').astype(str).str.lower()
    available = working[
        working['OutcomeState'].eq('Hit')
        & (
            methods.eq('available props')
            | methods.eq('main board')
            | sample_mode.isin({'available', 'full_board'})
        )
    ].copy()
    if available.empty:
        return available
    promoted = working[
        ~methods.eq('available props')
        & ~sample_mode.isin({'available', 'full_board'})
        & working['Method'].ne('')
    ].copy()
    promoted_keys = {_missed_prop_key(row) for _, row in promoted.iterrows()}
    available['_MissedKey'] = available.apply(_missed_prop_key, axis=1)
    return available[~available['_MissedKey'].isin(promoted_keys)].copy()


def build_missed_winner_bucket_frequency(df: pd.DataFrame | None = None, *, lookback_days: int = 7) -> dict:
    cache_key = (
        'missed_winner_bucket_frequency',
        _df_token(df) if df is not None else _all_prop_file_token(),
        int(lookback_days or 0),
    )
    cached = _REVIEW_RUNTIME_CACHE.get(cache_key)
    if cached is not None:
        return dict(cached)
    source = df if df is not None else load_all_prop_results_for_review()
    missed = _missed_winner_candidates(source)
    if missed.empty:
        return {}
    missed['SnapshotDateParsed'] = pd.to_datetime(missed.get('SnapshotDate'), errors='coerce')
    valid_dates = missed['SnapshotDateParsed'].dropna()
    if not valid_dates.empty and lookback_days:
        cutoff = valid_dates.max() - pd.Timedelta(days=int(lookback_days))
        missed = missed[missed['SnapshotDateParsed'] >= cutoff].copy()
    if missed.empty:
        return {}

    grades = missed.apply(calculate_missed_opportunity_grade, axis=1)
    missed['MissedGradeScore'] = [item[0] for item in grades]
    missed['MissedGrade'] = [item[1] for item in grades]
    missed = missed[missed['MissedGrade'].isin(['A+', 'A', 'B'])].copy()
    if missed.empty:
        return {}

    counts = {}
    grouped = missed.groupby([
        missed['Sport'].astype(str).str.upper(),
        missed['Stat'].astype(str).str.upper(),
        missed['Direction'].astype(str).str.upper(),
    ], dropna=False)
    for key, group in grouped:
        sport, stat, direction = [str(part).strip().upper() for part in key]
        if not sport or not stat or direction not in {'OVER', 'UNDER'}:
            continue
        counts[(sport, stat, direction)] = {
            'count': int(len(group)),
            'a_plus': int((group['MissedGrade'] == 'A+').sum()),
            'avg_grade': round(float(group['MissedGradeScore'].mean()), 1),
            'last_seen': group['SnapshotDateParsed'].max().strftime('%Y-%m-%d') if group['SnapshotDateParsed'].notna().any() else '',
        }
    _REVIEW_RUNTIME_CACHE[cache_key] = dict(counts)
    return counts


def calculate_promotion_signal(profile: dict, bucket_frequency: dict) -> dict:
    key = (
        str(profile.get('sport') or '').strip().upper(),
        str(profile.get('stat') or '').strip().upper(),
        str(profile.get('direction') or '').strip().upper(),
    )
    bucket = bucket_frequency.get(key, {})
    missed_count = int(bucket.get('count', 0) or 0)
    reliability = str(profile.get('reliability') or '').strip().upper()
    resolved = int(profile.get('resolved', 0) or 0)
    hit_rate = profile.get('hit_rate')

    if reliability == 'AVOID':
        signal = 'HOLD'
        action = 'Demote or investigate before featuring.'
    elif missed_count >= 3 and reliability in {'ANCHOR', 'WATCH'}:
        signal = 'PROMOTE HARD'
        action = 'Candidate for featured surface if live QC is clean.'
    elif missed_count >= 2 and reliability in {'ANCHOR', 'WATCH'}:
        signal = 'PROMOTE'
        action = 'Move up the board when this bucket appears live.'
    elif missed_count >= 1 and reliability == 'DEVELOPING':
        signal = 'SURFACE'
        action = 'Show on board, but do not force as a feature yet.'
    else:
        signal = 'STANDARD'
        action = 'Use normal scoring and QC rules.'

    if missed_count:
        reason = f"{missed_count} recent missed winners in bucket"
    else:
        reason = "No recent missed-winner bucket pressure"
    if reliability:
        reason += f" | player {reliability}"
    if resolved and hit_rate is not None:
        reason += f" | {resolved} resolved at {hit_rate}%"
    return {
        'signal': signal,
        'missed_count': missed_count,
        'bucket_a_plus': int(bucket.get('a_plus', 0) or 0),
        'bucket_avg_grade': bucket.get('avg_grade'),
        'last_seen': bucket.get('last_seen', ''),
        'reason': reason,
        'action': action,
    }


def build_missed_opportunities_context(
    *,
    sport_filter: str = '',
    stat_filter: str = '',
    grade_filter: str = '',
    start_date: str = '',
    end_date: str = '',
    min_grade: str = '',
    limit: int = 250,
) -> dict:
    df = load_all_prop_results_for_review()
    empty = {
        'rows': [],
        'summary': {'total': 0, 'a_plus': 0, 'a_or_better': 0, 'avg_grade': None, 'avg_confidence': None},
        'charts': {'by_sport': [], 'by_stat': [], 'by_grade': [], 'by_day': []},
        'sport_filter': sport_filter,
        'stat_filter': stat_filter,
        'grade_filter': grade_filter,
        'start_date': start_date,
        'end_date': end_date,
        'min_grade': min_grade,
        'sport_options': [],
        'stat_options': [],
        'grade_options': ['A+', 'A', 'B', 'C', 'D'],
    }
    if df.empty:
        return empty

    for column in ['Method', 'OutcomeState', 'Sport', 'Stat', 'Direction', 'Player', 'Matchup', 'SnapshotDate']:
        if column not in df.columns:
            df[column] = ''
        df[column] = df[column].fillna('').astype(str).str.strip()

    available = _missed_winner_candidates(df)

    if available.empty:
        return empty | {
            'sport_options': sorted(df['Sport'].dropna().astype(str).str.upper().unique().tolist()),
            'stat_options': sorted(df['Stat'].dropna().astype(str).str.upper().unique().tolist()),
        }

    available['ConfidenceNum'] = pd.to_numeric(available.get('Confidence'), errors='coerce')
    available['LineNum'] = pd.to_numeric(available.get('Line'), errors='coerce')
    available['ResultValueNum'] = pd.to_numeric(available.get('ResultValue'), errors='coerce')
    available['SnapshotDateParsed'] = pd.to_datetime(available['SnapshotDate'], errors='coerce')

    grades = available.apply(calculate_missed_opportunity_grade, axis=1)
    available['MissedGradeScore'] = [item[0] for item in grades]
    available['MissedGrade'] = [item[1] for item in grades]
    available['MissedReasons'] = ['; '.join(item[2]) for item in grades]

    sport_options = sorted(available['Sport'].dropna().astype(str).str.upper().unique().tolist())
    stat_options = sorted(available['Stat'].dropna().astype(str).str.upper().unique().tolist())

    sport_filter = str(sport_filter or '').strip().upper()
    stat_filter = str(stat_filter or '').strip().upper()
    grade_filter = str(grade_filter or '').strip().upper()
    if sport_filter:
        available = available[available['Sport'].str.upper().eq(sport_filter)].copy()
    if stat_filter:
        available = available[available['Stat'].str.upper().eq(stat_filter)].copy()
    if grade_filter:
        available = available[available['MissedGrade'].str.upper().eq(grade_filter)].copy()
    if min_grade:
        threshold = pd.to_numeric(pd.Series([min_grade]), errors='coerce').iloc[0]
        if pd.notna(threshold):
            available = available[available['MissedGradeScore'] >= float(threshold)].copy()
    if start_date:
        start_dt = pd.to_datetime(start_date, errors='coerce')
        if pd.notna(start_dt):
            available = available[available['SnapshotDateParsed'] >= start_dt].copy()
    if end_date:
        end_dt = pd.to_datetime(end_date, errors='coerce')
        if pd.notna(end_dt):
            available = available[available['SnapshotDateParsed'] <= end_dt].copy()

    if available.empty:
        return empty | {'sport_options': sport_options, 'stat_options': stat_options}

    available = available.sort_values(
        ['MissedGradeScore', 'ConfidenceNum', 'SnapshotDateParsed'],
        ascending=[False, False, False],
    )

    def chart_rows(group_col: str, label_key: str, top_n: int = 12) -> list[dict]:
        rows = []
        if group_col not in available.columns:
            return rows
        for label, group in available.groupby(group_col, dropna=False):
            if not str(label).strip():
                continue
            rows.append({
                label_key: str(label),
                'count': int(len(group)),
                'avg_grade': round(float(group['MissedGradeScore'].mean()), 1),
                'avg_confidence': round(float(group['ConfidenceNum'].mean()), 1) if group['ConfidenceNum'].notna().any() else None,
                'a_plus': int((group['MissedGrade'] == 'A+').sum()),
            })
        return sorted(rows, key=lambda row: (row['a_plus'], row['count'], row['avg_grade']), reverse=True)[:top_n]

    by_day = []
    day_source = available.dropna(subset=['SnapshotDateParsed']).copy()
    if not day_source.empty:
        day_source['DayLabel'] = day_source['SnapshotDateParsed'].dt.strftime('%Y-%m-%d')
        by_day = chart_rows('DayLabel', 'date', top_n=20)
        by_day = sorted(by_day, key=lambda row: row['date'])

    by_grade = []
    grade_order = {'A+': 0, 'A': 1, 'B': 2, 'C': 3, 'D': 4}
    for label, group in available.groupby('MissedGrade'):
        by_grade.append({
            'grade': str(label),
            'count': int(len(group)),
            'avg_grade': round(float(group['MissedGradeScore'].mean()), 1),
        })
    by_grade = sorted(by_grade, key=lambda row: grade_order.get(row['grade'], 99))

    rows = []
    for _, row in available.head(int(limit or 250)).iterrows():
        result_value = row.get('ResultValueNum')
        line = row.get('LineNum')
        book_count_value = pd.to_numeric(row.get('BookCount'), errors='coerce')
        rows.append({
            'snapshot_date': str(row.get('SnapshotDate') or '').strip(),
            'sport': str(row.get('Sport') or '').strip().upper(),
            'player': str(row.get('Player') or '').strip(),
            'team': _clean_review_value(row.get('Team')),
            'stat': str(row.get('Stat') or '').strip().upper(),
            'direction': str(row.get('Direction') or '').strip().upper(),
            'line': round(float(line), 1) if pd.notna(line) else row.get('Line'),
            'actual': round(float(result_value), 1) if pd.notna(result_value) else '',
            'confidence': round(float(row.get('ConfidenceNum')), 1) if pd.notna(row.get('ConfidenceNum')) else None,
            'grade_score': int(row.get('MissedGradeScore') or 0),
            'grade': str(row.get('MissedGrade') or ''),
            'why': str(row.get('MissedReasons') or ''),
            'book_count': int(book_count_value) if pd.notna(book_count_value) else '',
            'market_depth': _clean_review_value(row.get('MarketDepthBucket')),
            'market_move': _clean_review_value(row.get('MarketMoveBucket')),
            'method': _clean_review_value(row.get('Method')),
            'matchup': _clean_review_value(row.get('Matchup')),
            'baseline_reason': _clean_review_value(row.get('BaselineReason')) or _clean_review_value(row.get('PublicTrendNote')),
        })

    total = int(len(available))
    summary = {
        'total': total,
        'a_plus': int((available['MissedGrade'] == 'A+').sum()),
        'a_or_better': int(available['MissedGrade'].isin(['A+', 'A']).sum()),
        'avg_grade': round(float(available['MissedGradeScore'].mean()), 1),
        'avg_confidence': round(float(available['ConfidenceNum'].mean()), 1) if available['ConfidenceNum'].notna().any() else None,
    }
    return {
        'rows': rows,
        'summary': summary,
        'charts': {
            'by_sport': chart_rows('Sport', 'sport'),
            'by_stat': chart_rows('Stat', 'stat'),
            'by_grade': by_grade,
            'by_day': by_day,
        },
        'sport_filter': sport_filter,
        'stat_filter': stat_filter,
        'grade_filter': grade_filter,
        'start_date': start_date,
        'end_date': end_date,
        'min_grade': min_grade,
        'sport_options': sport_options,
        'stat_options': stat_options,
        'grade_options': ['A+', 'A', 'B', 'C', 'D'],
    }


def filter_floor_index_for_review(
    index_df: pd.DataFrame,
    *,
    sport_filter: str = '',
    outcome_filter: str = '',
    stat_filter: str = '',
    direction_filter: str = '',
    player_search_filter: str = '',
    player_tier_filter: str = '',
    bet_tier_filter: str = '',
    weight_profile_filter: str = '',
    volatility_filter: str = '',
    market_gate_filter: str = '',
    floor_reliability_filter: str = '',
    days_to_result_filter: str = '',
    start_date: str = '',
    end_date: str = '',
) -> pd.DataFrame:
    if index_df is None or index_df.empty:
        return pd.DataFrame()
    filtered = index_df.copy()
    if sport_filter and 'Sport' in filtered.columns:
        filtered = filtered[filtered['Sport'].fillna('').astype(str).str.upper() == sport_filter].copy()
    if outcome_filter:
        allowed = {'hit': 'Hit', 'miss': 'Miss', 'push': 'Push', 'pending': 'Pending'}
        if outcome_filter in allowed and 'OutcomeState' in filtered.columns:
            filtered = filtered[filtered['OutcomeState'].astype(str) == allowed[outcome_filter]].copy()
    if stat_filter and 'Stat' in filtered.columns:
        filtered = filtered[filtered['Stat'].astype(str).str.upper() == stat_filter].copy()
    if direction_filter in {'OVER', 'UNDER'} and 'Direction' in filtered.columns:
        filtered = filtered[filtered['Direction'].astype(str).str.upper() == direction_filter].copy()
    if player_search_filter and 'Player' in filtered.columns:
        filtered = filtered[filtered['Player'].fillna('').astype(str).str.contains(player_search_filter, case=False, na=False, regex=False)].copy()
    if player_tier_filter and 'RoleLabel' in filtered.columns:
        filtered = filtered[filtered['RoleLabel'].astype(str).str.upper() == player_tier_filter].copy()
    if bet_tier_filter and 'ReviewTier' in filtered.columns:
        filtered = filtered[filtered['ReviewTier'].astype(str) == bet_tier_filter].copy()
    if weight_profile_filter and 'WeightProfile' in filtered.columns:
        filtered = filtered[filtered['WeightProfile'].astype(str) == weight_profile_filter].copy()
    if volatility_filter and 'VolatilityFlag' in filtered.columns:
        filtered = filtered[filtered['VolatilityFlag'].astype(str).str.upper() == volatility_filter].copy()
    if market_gate_filter and 'MarketGate' in filtered.columns:
        filtered = filtered[filtered['MarketGate'].astype(str).str.upper() == market_gate_filter].copy()
    if floor_reliability_filter and 'FloorReliability' in filtered.columns:
        filtered = filtered[filtered['FloorReliability'].astype(str).str.upper() == floor_reliability_filter].copy()
    if days_to_result_filter and 'DaysToResult' in filtered.columns:
        days = pd.to_numeric(filtered.get('DaysToResult'), errors='coerce')
        if days_to_result_filter == 'same_day':
            filtered = filtered[days == 0].copy()
        elif days_to_result_filter == 'one_day':
            filtered = filtered[days == 1].copy()
        elif days_to_result_filter == 'two_plus':
            filtered = filtered[days >= 2].copy()
        elif days_to_result_filter == 'resolved':
            filtered = filtered[days.notna()].copy()
        elif days_to_result_filter == 'pending':
            filtered = filtered[days.isna()].copy()
    date_col = 'ResultDay' if 'ResultDay' in filtered.columns else 'SnapshotDate'
    if start_date and date_col in filtered.columns:
        start_dt = pd.to_datetime(start_date, errors='coerce')
        if not pd.isna(start_dt):
            filtered = filtered[pd.to_datetime(filtered[date_col], errors='coerce') >= start_dt].copy()
    if end_date and date_col in filtered.columns:
        end_dt = pd.to_datetime(end_date, errors='coerce')
        if not pd.isna(end_dt):
            filtered = filtered[pd.to_datetime(filtered[date_col], errors='coerce') <= end_dt].copy()
    return filtered


def calculate_floor_reliability(resolved_count, hit_rate) -> str:
    count = int(resolved_count or 0)
    if hit_rate is None or pd.isna(hit_rate):
        return 'SMALL SAMPLE'
    rate = float(hit_rate)
    if count < 10:
        return 'SMALL SAMPLE'
    if count >= 20 and rate >= 0.65:
        return 'ANCHOR'
    if count >= 10 and rate >= 0.60:
        return 'WATCH'
    if count >= 10 and rate < 0.52:
        return 'AVOID'
    return 'DEVELOPING'


def build_floor_reliability_table(floor_index_df: pd.DataFrame) -> list[dict]:
    if floor_index_df is None or floor_index_df.empty:
        return []
    df = floor_index_df.copy()
    if 'IsFloorPlay' in df.columns:
        df = df[df['IsFloorPlay'].astype(bool)].copy()
    elif 'Method' in df.columns:
        df = df[df['Method'].fillna('').astype(str).str.contains('floor', case=False, na=False)].copy()
    if df.empty:
        return []
    for column in ['Sport', 'Stat', 'Direction', 'OutcomeState']:
        if column not in df.columns:
            df[column] = ''
        df[column] = df[column].fillna('').astype(str)
    resolved = df[df['OutcomeState'].isin(['Hit', 'Miss'])].copy()
    rows = []
    all_keys = df.groupby(['Sport', 'Stat', 'Direction'], dropna=False)
    resolved_groups = resolved.groupby(['Sport', 'Stat', 'Direction'], dropna=False) if not resolved.empty else {}
    for keys, group in all_keys:
        if not isinstance(keys, tuple):
            keys = (keys,)
        sport, stat, direction = keys
        if not str(sport).strip() or not str(stat).strip() or not str(direction).strip():
            continue
        if not resolved.empty and keys in resolved_groups.groups:
            decisive = resolved_groups.get_group(keys)
        else:
            decisive = pd.DataFrame()
        resolved_count = int(len(decisive))
        hits = int((decisive['OutcomeState'] == 'Hit').sum()) if not decisive.empty else 0
        misses = int((decisive['OutcomeState'] == 'Miss').sum()) if not decisive.empty else 0
        hit_rate = float(hits / resolved_count) if resolved_count else None
        pending_count = int((group['OutcomeState'] == 'Pending').sum())
        reliability = calculate_floor_reliability(resolved_count, hit_rate)
        rows.append({
            'sport': str(sport).upper(),
            'stat': str(stat).upper(),
            'direction': str(direction).upper(),
            'bucket': f"{str(sport).upper()} {str(stat).upper()} {str(direction).upper()}",
            'resolved_count': resolved_count,
            'hits': hits,
            'misses': misses,
            'pending_count': pending_count,
            'hit_rate': round(hit_rate * 100, 1) if hit_rate is not None else None,
            'floor_reliability': reliability,
            'parlay_eligible': reliability in {'ANCHOR', 'WATCH'},
        })
    order = {'ANCHOR': 0, 'WATCH': 1, 'DEVELOPING': 2, 'SMALL SAMPLE': 3, 'AVOID': 4}
    return sorted(
        rows,
        key=lambda row: (
            order.get(row['floor_reliability'], 99),
            -(row['hit_rate'] if row['hit_rate'] is not None else -1),
            -row['resolved_count'],
        ),
    )


def floor_reliability_lookup(floor_buckets: list[dict]) -> dict:
    return {
        (row['sport'], row['stat'], row['direction']): row
        for row in floor_buckets or []
    }


def apply_floor_reliability(df: pd.DataFrame, floor_buckets: list[dict]) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    lookup = floor_reliability_lookup(floor_buckets)
    working = df.copy()
    for column in ['Sport', 'Stat', 'Direction']:
        if column not in working.columns:
            working[column] = ''
    if 'Method' not in working.columns:
        working['Method'] = ''
    labels = []
    notes = []
    eligible = []
    for _, row in working.iterrows():
        is_floor = 'floor' in str(row.get('Method') or '').lower() or bool(row.get('IsFloorPlay', False))
        key = (
            str(row.get('Sport') or '').upper(),
            str(row.get('Stat') or '').upper(),
            str(row.get('Direction') or '').upper(),
        )
        bucket = lookup.get(key)
        if is_floor and bucket:
            labels.append(bucket['floor_reliability'])
            hit_rate = bucket['hit_rate']
            rate_text = f"{hit_rate}%" if hit_rate is not None else "-"
            notes.append(f"{bucket['resolved_count']} resolved at {rate_text}")
            eligible.append(bool(bucket['parlay_eligible']))
        elif is_floor:
            labels.append('SMALL SAMPLE')
            notes.append('No resolved bucket sample yet')
            eligible.append(False)
        else:
            labels.append('')
            notes.append('')
            eligible.append(False)
    working['FloorReliability'] = labels
    working['FloorReliabilityNote'] = notes
    working['FloorParlayEligible'] = eligible
    return working


def check_floor_reliability_watch(floor_buckets: list[dict]) -> list[dict]:
    watches = []
    for row in floor_buckets or []:
        label = row.get('floor_reliability')
        if label == 'ANCHOR':
            watches.append({
                'type': 'ANCHOR CONFIRMED',
                'title': row.get('bucket', 'Floor Anchor'),
                'detail': f"{row.get('resolved_count', 0)} resolved at {row.get('hit_rate')}% - use as parlay stabilizer.",
            })
        elif label == 'AVOID':
            watches.append({
                'type': 'AVOID CONFIRMED',
                'title': row.get('bucket', 'Floor Avoid'),
                'detail': f"{row.get('resolved_count', 0)} resolved at {row.get('hit_rate')}% - exclude from parlay construction.",
            })
    return watches


def calculate_player_line_sensitivity(player_df: pd.DataFrame) -> dict:
    if player_df is None or player_df.empty or 'LineNum' not in player_df.columns:
        return {
            'low_line_hit_rate': None,
            'high_line_hit_rate': None,
            'line_sensitive': False,
            'line_note': 'No line sample',
        }
    working = player_df.dropna(subset=['LineNum']).copy()
    if len(working) < 4:
        return {
            'low_line_hit_rate': None,
            'high_line_hit_rate': None,
            'line_sensitive': False,
            'line_note': 'Need 4+ lined results',
        }
    median_line = working['LineNum'].median()
    low_line = working[working['LineNum'] <= median_line]
    high_line = working[working['LineNum'] > median_line]
    if low_line.empty or high_line.empty:
        return {
            'low_line_hit_rate': None,
            'high_line_hit_rate': None,
            'line_sensitive': False,
            'line_note': 'One-sided line sample',
        }
    low_rate = float((low_line['OutcomeState'] == 'Hit').mean())
    high_rate = float((high_line['OutcomeState'] == 'Hit').mean())
    gap = abs(low_rate - high_rate)
    better = 'lower lines' if low_rate > high_rate else 'higher lines'
    return {
        'low_line_hit_rate': round(low_rate * 100, 1),
        'high_line_hit_rate': round(high_rate * 100, 1),
        'line_sensitive': gap >= 0.12,
        'line_note': f"Better at {better}" if gap >= 0.12 else 'No strong line split',
    }


def calculate_player_reliability(resolved_count, hit_rate) -> str:
    if hit_rate is None or pd.isna(hit_rate):
        return 'NO SAMPLE'
    if resolved_count < 3:
        return 'TOO THIN'
    if resolved_count >= 10 and hit_rate >= 0.65:
        return 'ANCHOR'
    if resolved_count >= 5 and hit_rate >= 0.60:
        return 'WATCH'
    if resolved_count >= 5 and hit_rate < 0.52:
        return 'AVOID'
    if resolved_count >= 3:
        return 'DEVELOPING'
    return 'TOO THIN'


def _player_model_accuracy(avg_confidence, hit_rate) -> str:
    if avg_confidence is None or hit_rate is None or pd.isna(avg_confidence) or pd.isna(hit_rate):
        return 'CALIBRATED'
    confidence = float(avg_confidence)
    rate = float(hit_rate)
    if confidence >= 70 and rate < 0.52:
        return 'OVERVALUED'
    if confidence <= 60 and rate >= 0.72:
        return 'UNDERVALUED'
    return 'CALIBRATED'


def build_player_hit_profiles(result_df: pd.DataFrame) -> list[dict]:
    if result_df is None or result_df.empty:
        return []
    cache_key = ('player_hit_profiles', _df_token(result_df))
    cached = _REVIEW_RUNTIME_CACHE.get(cache_key)
    if cached is not None:
        return [dict(row) for row in cached]
    source_paths = [FLOOR_PLAY_INDEX_PATH, *ALL_PROP_RESULT_PATHS.values()]
    if len(result_df) >= 10000 and _artifact_is_fresh(PLAYER_PROFILE_INDEX_PATH, source_paths):
        try:
            artifact = pd.read_csv(PLAYER_PROFILE_INDEX_PATH, low_memory=False)
        except Exception:
            artifact = pd.DataFrame()
        if not artifact.empty:
            rows = artifact.where(pd.notna(artifact), None).to_dict('records')
            _REVIEW_RUNTIME_CACHE[cache_key] = [dict(row) for row in rows]
            return rows
    df = result_df.copy()
    for column in ['Player', 'Sport', 'Stat', 'Direction', 'OutcomeState']:
        if column not in df.columns:
            df[column] = ''
        df[column] = df[column].fillna('').astype(str)
    resolved = df[df['OutcomeState'].isin(['Hit', 'Miss'])].copy()
    if resolved.empty:
        return []
    for column in ['SnapshotDate', 'ResultDate', 'Matchup', 'Line']:
        if column not in resolved.columns:
            resolved[column] = ''
        resolved[column] = resolved[column].fillna('').astype(str)
    resolved['LineNum'] = pd.to_numeric(resolved.get('Line'), errors='coerce')
    resolved['ConfidenceNum'] = pd.to_numeric(resolved.get('Confidence'), errors='coerce')
    resolved['_ProfileDate'] = resolved['ResultDate'].where(resolved['ResultDate'].astype(str).str.strip() != '', resolved['SnapshotDate'])
    resolved['_ProfileLine'] = resolved['LineNum'].round(3).astype(str).where(resolved['LineNum'].notna(), resolved['Line'].astype(str))
    resolved['_ConfidenceSort'] = resolved['ConfidenceNum'].fillna(-1)
    resolved = (
        resolved.sort_values('_ConfidenceSort', ascending=False)
        .drop_duplicates(
            subset=['_ProfileDate', 'Player', 'Sport', 'Stat', 'Direction', '_ProfileLine', 'Matchup', 'OutcomeState'],
            keep='first',
        )
        .copy()
    )
    rows = []
    grouped = resolved.groupby(['Player', 'Sport', 'Stat', 'Direction'], dropna=False)
    for keys, group in grouped:
        player, sport, stat, direction = [str(part).strip() for part in keys]
        if not player or not sport or not stat or direction not in {'OVER', 'UNDER'}:
            continue
        resolved_count = int(len(group))
        hits = int((group['OutcomeState'] == 'Hit').sum())
        misses = int((group['OutcomeState'] == 'Miss').sum())
        hit_rate_raw = hits / resolved_count if resolved_count else None
        avg_line = group['LineNum'].mean()
        avg_conf = group['ConfidenceNum'].mean()
        sensitivity = calculate_player_line_sensitivity(group)
        reliability = calculate_player_reliability(resolved_count, hit_rate_raw)
        rows.append({
            'player': player,
            'sport': sport.upper(),
            'stat': stat.upper(),
            'direction': direction.upper(),
            'bucket': f"{player} {sport.upper()} {stat.upper()} {direction.upper()}",
            'resolved': resolved_count,
            'hits': hits,
            'misses': misses,
            'hit_rate': round(hit_rate_raw * 100, 1) if hit_rate_raw is not None else None,
            'avg_line': round(float(avg_line), 1) if not pd.isna(avg_line) else None,
            'avg_confidence': round(float(avg_conf), 1) if not pd.isna(avg_conf) else None,
            'reliability': reliability,
            'model_accuracy': _player_model_accuracy(avg_conf, hit_rate_raw),
            **sensitivity,
        })
    order = {'ANCHOR': 0, 'WATCH': 1, 'DEVELOPING': 2, 'SMALL SAMPLE': 3, 'AVOID': 4}
    model_order = {'UNDERVALUED': 0, 'CALIBRATED': 1, 'OVERVALUED': 2}
    rows = sorted(
        rows,
        key=lambda row: (
            model_order.get(row['model_accuracy'], 9),
            order.get(row['reliability'], 9),
            -(row['hit_rate'] if row['hit_rate'] is not None else -1),
            -row['resolved'],
        ),
    )
    if len(result_df) >= 10000:
        try:
            PLAYER_PROFILE_INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
            pd.DataFrame(rows).to_csv(PLAYER_PROFILE_INDEX_PATH, index=False)
        except Exception:
            pass
    _REVIEW_RUNTIME_CACHE[cache_key] = [dict(row) for row in rows]
    return rows


def player_profile_lookup(player_profiles: list[dict]) -> dict:
    return {
        (
            str(row.get('player') or '').strip().lower(),
            str(row.get('sport') or '').strip().upper(),
            str(row.get('stat') or '').strip().upper(),
            str(row.get('direction') or '').strip().upper(),
        ): row
        for row in player_profiles or []
    }


def apply_player_profiles(df: pd.DataFrame, player_profiles: list[dict]) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    lookup = player_profile_lookup(player_profiles)
    working = df.copy()
    for column in ['Player', 'Sport', 'Stat', 'Direction']:
        if column not in working.columns:
            working[column] = ''
    labels = []
    models = []
    notes = []
    hit_rates = []
    resolved_counts = []
    for _, row in working.iterrows():
        key = (
            str(row.get('Player') or '').strip().lower(),
            str(row.get('Sport') or '').strip().upper(),
            str(row.get('Stat') or '').strip().upper(),
            str(row.get('Direction') or '').strip().upper(),
        )
        profile = lookup.get(key)
        if profile and int(profile.get('resolved', 0) or 0) >= 3:
            labels.append(profile.get('reliability', ''))
            models.append(profile.get('model_accuracy', ''))
            rate = profile.get('hit_rate')
            resolved = profile.get('resolved', 0)
            hit_rates.append(rate)
            resolved_counts.append(resolved)
            rate_text = f"{rate}%" if rate is not None else "-"
            notes.append(f"{resolved} resolved at {rate_text}")
        else:
            labels.append('')
            models.append('')
            notes.append('')
            hit_rates.append(None)
            resolved_counts.append(0)
    working['PlayerReliability'] = labels
    working['PlayerModelAccuracy'] = models
    working['PlayerProfileNote'] = notes
    working['PlayerHitRate'] = hit_rates
    working['PlayerResolvedCount'] = resolved_counts
    return working


def build_player_profile_summary(result_df: pd.DataFrame, player_name: str) -> dict:
    empty = {
        'available': False,
        'overall': {},
        'rows': [],
        'best': None,
        'worst': None,
        'recent': [],
        'current_streak': '',
    }
    if result_df is None or result_df.empty or not player_name:
        return empty
    df = result_df.copy()
    if 'Player' not in df.columns:
        return empty
    player_key = str(player_name).strip().lower()
    player_rows = df[df['Player'].fillna('').astype(str).str.lower() == player_key].copy()
    if player_rows.empty:
        return empty
    profiles = build_player_hit_profiles(player_rows)
    resolved = player_rows[player_rows.get('OutcomeState', pd.Series('', index=player_rows.index)).isin(['Hit', 'Miss'])].copy()
    if resolved.empty:
        return {
            **empty,
            'available': True,
            'rows': profiles,
            'overall': {'resolved': 0, 'hits': 0, 'misses': 0, 'hit_rate': None, 'model_accuracy': 'PENDING'},
        }
    for column in ['SnapshotDate', 'ResultDate', 'Matchup', 'Line', 'Player', 'Sport', 'Stat', 'Direction']:
        if column not in resolved.columns:
            resolved[column] = ''
        resolved[column] = resolved[column].fillna('').astype(str)
    resolved['_LineNum'] = pd.to_numeric(resolved.get('Line'), errors='coerce')
    resolved['_ProfileDate'] = resolved['ResultDate'].where(resolved['ResultDate'].astype(str).str.strip() != '', resolved['SnapshotDate'])
    resolved['_ProfileLine'] = resolved['_LineNum'].round(3).astype(str).where(resolved['_LineNum'].notna(), resolved['Line'].astype(str))
    resolved['_ConfidenceSort'] = pd.to_numeric(resolved.get('Confidence'), errors='coerce').fillna(-1)
    resolved = (
        resolved.sort_values('_ConfidenceSort', ascending=False)
        .drop_duplicates(
            subset=['_ProfileDate', 'Player', 'Sport', 'Stat', 'Direction', '_ProfileLine', 'Matchup', 'OutcomeState'],
            keep='first',
        )
        .copy()
    )
    hits = int((resolved['OutcomeState'] == 'Hit').sum())
    misses = int((resolved['OutcomeState'] == 'Miss').sum())
    resolved_count = int(len(resolved))
    hit_rate = hits / resolved_count if resolved_count else None
    avg_conf = pd.to_numeric(resolved.get('Confidence'), errors='coerce').mean()
    trusted = [row for row in profiles if row.get('resolved', 0) >= 3 and row.get('hit_rate') is not None]
    best = max(trusted, key=lambda row: (row['hit_rate'], row['resolved']), default=None)
    worst = min(trusted, key=lambda row: (row['hit_rate'], -row['resolved']), default=None)
    date_col = 'ResultDate' if 'ResultDate' in resolved.columns else 'SnapshotDate'
    resolved['_ReviewDate'] = pd.to_datetime(resolved.get(date_col), errors='coerce')
    recent_rows = resolved.sort_values('_ReviewDate', ascending=False).head(5)
    recent = []
    for _, row in recent_rows.iterrows():
        recent.append({
            'date': row.get(date_col, ''),
            'stat': str(row.get('Stat') or '').upper(),
            'direction': str(row.get('Direction') or '').upper(),
            'line': row.get('Line', ''),
            'outcome': row.get('OutcomeState', ''),
        })
    streak_outcome = ''
    streak_count = 0
    for item in recent:
        if not streak_outcome:
            streak_outcome = item['outcome']
            streak_count = 1
        elif item['outcome'] == streak_outcome:
            streak_count += 1
        else:
            break
    return {
        'available': True,
        'overall': {
            'resolved': resolved_count,
            'hits': hits,
            'misses': misses,
            'hit_rate': round(hit_rate * 100, 1) if hit_rate is not None else None,
            'avg_confidence': round(float(avg_conf), 1) if not pd.isna(avg_conf) else None,
            'model_accuracy': _player_model_accuracy(avg_conf, hit_rate),
        },
        'rows': profiles,
        'best': best,
        'worst': worst,
        'recent': recent,
        'current_streak': f"{streak_count} {streak_outcome.lower()}s" if streak_count and streak_outcome else '',
    }


def build_archived_player_page_context(player_name: str) -> dict:
    df = load_all_prop_results_for_review()
    player_name = str(player_name or '').strip()
    empty = {
        'available': False,
        'player': player_name,
        'summary': {},
        'profiles': [],
        'streak_heat': [],
        'recent_rows': [],
        'sports': [],
        'stats': [],
    }
    if df.empty or not player_name:
        return empty
    for column in ['Player', 'Sport', 'Stat', 'Direction', 'OutcomeState', 'SnapshotDate']:
        if column not in df.columns:
            df[column] = ''
        df[column] = df[column].fillna('').astype(str)
    player_df = df[df['Player'].str.lower() == player_name.lower()].copy()
    if player_df.empty:
        return empty

    profiles = [
        row for row in build_player_hit_profiles(player_df)
        if row.get('resolved', 0) >= 3
    ]
    resolved = player_df[player_df['OutcomeState'].isin(['Hit', 'Miss'])].copy()
    if not resolved.empty:
        for column in ['SnapshotDate', 'ResultDate', 'Matchup', 'Line', 'Player', 'Sport', 'Stat', 'Direction']:
            if column not in resolved.columns:
                resolved[column] = ''
            resolved[column] = resolved[column].fillna('').astype(str)
        resolved['_LineNum'] = pd.to_numeric(resolved.get('Line'), errors='coerce')
        resolved['_ProfileDate'] = resolved['ResultDate'].where(resolved['ResultDate'].astype(str).str.strip() != '', resolved['SnapshotDate'])
        resolved['_ProfileLine'] = resolved['_LineNum'].round(3).astype(str).where(resolved['_LineNum'].notna(), resolved['Line'].astype(str))
        resolved['_ConfidenceSort'] = pd.to_numeric(resolved.get('Confidence'), errors='coerce').fillna(-1)
        resolved = (
            resolved.sort_values('_ConfidenceSort', ascending=False)
            .drop_duplicates(
                subset=['_ProfileDate', 'Player', 'Sport', 'Stat', 'Direction', '_ProfileLine', 'Matchup', 'OutcomeState'],
                keep='first',
            )
            .copy()
        )
    hits = int((resolved['OutcomeState'] == 'Hit').sum()) if not resolved.empty else 0
    misses = int((resolved['OutcomeState'] == 'Miss').sum()) if not resolved.empty else 0
    pending = int((player_df['OutcomeState'] == 'Pending').sum())
    pushes = int((player_df['OutcomeState'] == 'Push').sum())
    hit_rate = round(float(hits / len(resolved)) * 100, 1) if len(resolved) else None
    avg_conf = pd.to_numeric(player_df.get('Confidence'), errors='coerce').mean()
    recent_source = player_df.copy()
    recent_source['SnapshotDateParsed'] = pd.to_datetime(recent_source['SnapshotDate'], errors='coerce')
    recent_source = recent_source.sort_values('SnapshotDateParsed', ascending=False)
    recent_rows = []
    for _, row in recent_source.head(75).iterrows():
        confidence = pd.to_numeric(row.get('Confidence'), errors='coerce')
        line = pd.to_numeric(row.get('Line'), errors='coerce')
        actual = pd.to_numeric(row.get('ResultValue'), errors='coerce')
        recent_rows.append({
            'snapshot_date': _clean_review_value(row.get('SnapshotDate')),
            'sport': _clean_review_value(row.get('Sport')).upper(),
            'method': _clean_review_value(row.get('Method')),
            'matchup': _clean_review_value(row.get('Matchup')),
            'stat': _clean_review_value(row.get('Stat')).upper(),
            'direction': _clean_review_value(row.get('Direction')).upper(),
            'line': round(float(line), 1) if pd.notna(line) else _clean_review_value(row.get('Line')),
            'actual': round(float(actual), 1) if pd.notna(actual) else '',
            'outcome': _clean_review_value(row.get('OutcomeState')),
            'confidence': round(float(confidence), 1) if pd.notna(confidence) else None,
            'tier': _clean_review_value(row.get('ReviewTier')) or _clean_review_value(row.get('BetTier')),
            'book_count': _clean_review_value(row.get('BookCount')),
        })
    return {
        'available': True,
        'player': player_name,
        'summary': {
            'total_rows': int(len(player_df)),
            'resolved': int(len(resolved)),
            'hits': hits,
            'misses': misses,
            'pushes': pushes,
            'pending': pending,
            'hit_rate': hit_rate,
            'avg_confidence': round(float(avg_conf), 1) if pd.notna(avg_conf) else None,
        },
        'profiles': profiles,
        'streak_heat': build_player_streak_heat(player_df),
        'recent_rows': recent_rows,
        'sports': sorted({_clean_review_value(v).upper() for v in player_df['Sport'].tolist() if _clean_review_value(v)}),
        'stats': sorted({_clean_review_value(v).upper() for v in player_df['Stat'].tolist() if _clean_review_value(v)}),
    }


def build_player_streak_heat(player_df: pd.DataFrame, *, max_streak: int = 10) -> list[dict]:
    if player_df is None or player_df.empty:
        return []
    df = player_df.copy()
    for column in ['SnapshotDate', 'ResultDate', 'Matchup', 'Line', 'Player', 'Sport', 'Stat', 'Direction', 'OutcomeState']:
        if column not in df.columns:
            df[column] = ''
        df[column] = df[column].fillna('').astype(str)
    resolved = df[df['OutcomeState'].isin(['Hit', 'Miss'])].copy()
    if resolved.empty:
        return []
    resolved['_LineNum'] = pd.to_numeric(resolved.get('Line'), errors='coerce')
    resolved['_ProfileDate'] = resolved['ResultDate'].where(resolved['ResultDate'].astype(str).str.strip() != '', resolved['SnapshotDate'])
    resolved['_ProfileLine'] = resolved['_LineNum'].round(3).astype(str).where(resolved['_LineNum'].notna(), resolved['Line'].astype(str))
    resolved['_ConfidenceSort'] = pd.to_numeric(resolved.get('Confidence'), errors='coerce').fillna(-1)
    resolved['_ProfileDateParsed'] = pd.to_datetime(resolved['_ProfileDate'], errors='coerce')
    resolved = (
        resolved.sort_values(['_ProfileDateParsed', '_ConfidenceSort'], ascending=[True, False])
        .drop_duplicates(
            subset=['_ProfileDate', 'Player', 'Sport', 'Stat', 'Direction', '_ProfileLine', 'Matchup', 'OutcomeState'],
            keep='first',
        )
        .copy()
    )

    rows = []
    grouped = resolved.groupby(['Sport', 'Stat', 'Direction'], dropna=False)
    for keys, group in grouped:
        sport, stat, direction = [str(part).strip().upper() for part in keys]
        if not sport or not stat or direction not in {'OVER', 'UNDER'}:
            continue
        group = group.sort_values('_ProfileDateParsed')
        longest_hit = longest_miss = current_count = 0
        current_outcome = ''
        last_outcome = ''
        run = 0
        hits = int((group['OutcomeState'] == 'Hit').sum())
        misses = int((group['OutcomeState'] == 'Miss').sum())
        sequence = []
        for _, item in group.iterrows():
            outcome = str(item.get('OutcomeState') or '')
            sequence.append('H' if outcome == 'Hit' else 'M')
            if outcome == last_outcome:
                run += 1
            else:
                last_outcome = outcome
                run = 1
            if outcome == 'Hit':
                longest_hit = max(longest_hit, run)
            elif outcome == 'Miss':
                longest_miss = max(longest_miss, run)
        if last_outcome:
            current_outcome = last_outcome
            current_count = run
        resolved_count = int(len(group))
        rows.append({
            'sport': sport,
            'stat': stat,
            'direction': direction,
            'label': f"{sport} {stat} {direction}",
            'resolved': resolved_count,
            'hits': hits,
            'misses': misses,
            'hit_rate': round(float(hits / resolved_count) * 100, 1) if resolved_count else None,
            'longest_hit': int(longest_hit),
            'longest_miss': int(longest_miss),
            'best_streak': int(max(longest_hit, longest_miss)),
            'current_outcome': current_outcome,
            'current_count': int(current_count),
            'sequence': ''.join(sequence[-10:]),
            'heat_cells': [
                {
                    'n': value,
                    'hit_active': value <= min(longest_hit, max_streak),
                    'miss_active': value <= min(longest_miss, max_streak),
                }
                for value in range(1, max_streak + 1)
            ],
        })
    return sorted(
        rows,
        key=lambda row: (row['best_streak'], row['resolved'], row['hit_rate'] or 0),
        reverse=True,
    )


def calculate_heat_score(current_streak: int, hit_rate: float | None, total_resolved: int) -> int:
    streak_score = min(max(int(current_streak or 0), 0) * 8, 50)
    reliability_score = (float(hit_rate or 0) / 100) * 30
    sample_score = min(max(int(total_resolved or 0), 0) / 2, 20)
    return int(round(streak_score + reliability_score + sample_score))


def heat_tier_from_score(score: int) -> int:
    value = int(score or 0)
    if value >= 85:
        return 5
    if value >= 70:
        return 4
    if value >= 55:
        return 3
    if value >= 40:
        return 2
    return 1


def build_streak_heat_chart(
    resolved_df: pd.DataFrame | None = None,
    *,
    min_resolved: int = 3,
    max_streak: int = 10,
    limit: int = 50,
) -> list[dict]:
    cache_key = (
        'streak_heat_chart',
        _df_token(resolved_df) if resolved_df is not None else _all_prop_file_token(),
        int(min_resolved or 0),
        int(max_streak or 0),
        int(limit or 0),
    )
    cached = _REVIEW_RUNTIME_CACHE.get(cache_key)
    if cached is not None:
        return [dict(row) for row in cached]
    if resolved_df is None and _artifact_is_fresh(STREAK_HEAT_INDEX_PATH, list(ALL_PROP_RESULT_PATHS.values())):
        try:
            artifact = pd.read_csv(STREAK_HEAT_INDEX_PATH, low_memory=False)
        except Exception:
            artifact = pd.DataFrame()
        if not artifact.empty:
            rows = artifact.where(pd.notna(artifact), None).to_dict('records')[:int(limit or 50)]
            # CSV round-trip turns list columns into strings like "['H', 'H', 'H']".
            # Restore them to real lists so the H/M chips render the actual outcomes
            # (oldest -> newest) instead of iterating the string's characters.
            import ast as _ast
            for row in rows:
                for col in ('last_10', 'last_5'):
                    val = row.get(col)
                    if isinstance(val, str):
                        label = str(row.get('last_10_label') or '') if col == 'last_10' else ''
                        if label:
                            row[col] = [ch for ch in label]
                        else:
                            try:
                                parsed = _ast.literal_eval(val)
                                row[col] = parsed if isinstance(parsed, list) else []
                            except Exception:
                                row[col] = []
            _REVIEW_RUNTIME_CACHE[cache_key] = [dict(row) for row in rows]
            return rows
    df = resolved_df if resolved_df is not None else load_all_prop_results_for_review()
    if df is None or df.empty:
        return []
    working = df.copy()
    for column in ['SnapshotDate', 'ResultDate', 'Matchup', 'Line', 'Player', 'Sport', 'Stat', 'Direction', 'OutcomeState']:
        if column not in working.columns:
            working[column] = ''
        working[column] = working[column].fillna('').astype(str)

    resolved = working[working['OutcomeState'].isin(['Hit', 'Miss'])].copy()
    if resolved.empty:
        return []

    resolved['_LineNum'] = pd.to_numeric(resolved.get('Line'), errors='coerce')
    resolved['_ProfileDate'] = resolved['ResultDate'].where(resolved['ResultDate'].astype(str).str.strip() != '', resolved['SnapshotDate'])
    resolved['_ProfileLine'] = resolved['_LineNum'].round(3).astype(str).where(resolved['_LineNum'].notna(), resolved['Line'].astype(str))
    resolved['_ConfidenceSort'] = pd.to_numeric(resolved.get('Confidence'), errors='coerce').fillna(-1)
    resolved['_ProfileDateParsed'] = pd.to_datetime(resolved['_ProfileDate'], errors='coerce')
    resolved = (
        resolved.sort_values(['_ProfileDateParsed', '_ConfidenceSort'], ascending=[True, False])
        .drop_duplicates(
            subset=['_ProfileDate', 'Player', 'Sport', 'Stat', 'Direction', '_ProfileLine', 'Matchup', 'OutcomeState'],
            keep='first',
        )
        .copy()
    )

    rows: list[dict] = []
    grouped = resolved.groupby(['Player', 'Sport', 'Stat', 'Direction'], dropna=False)
    for keys, group in grouped:
        player, sport, stat, direction = [str(part).strip() for part in keys]
        sport = sport.upper()
        stat = stat.upper()
        direction = direction.upper()
        if not player or not sport or not stat or direction not in {'OVER', 'UNDER'}:
            continue
        group = group.sort_values('_ProfileDateParsed')
        if len(group) < int(min_resolved):
            continue

        outcomes = [str(value) for value in group['OutcomeState'].tolist()]
        hits = outcomes.count('Hit')
        misses = outcomes.count('Miss')
        total = len(outcomes)
        hit_rate = round(float(hits / total) * 100, 1) if total else 0

        current_streak = 0
        current_outcome = outcomes[-1] if outcomes else ''
        for outcome in reversed(outcomes):
            if outcome == current_outcome:
                current_streak += 1
            else:
                break

        longest_hit = 0
        longest_miss = 0
        running_outcome = ''
        running_count = 0
        for outcome in outcomes:
            if outcome == running_outcome:
                running_count += 1
            else:
                running_outcome = outcome
                running_count = 1
            if outcome == 'Hit':
                longest_hit = max(longest_hit, running_count)
            elif outcome == 'Miss':
                longest_miss = max(longest_miss, running_count)

        current_hit_streak = current_streak if current_outcome == 'Hit' else 0
        heat_score = calculate_heat_score(current_hit_streak, hit_rate, total)
        last_10 = ['H' if outcome == 'Hit' else 'M' for outcome in outcomes[-10:]]
        last_5 = ['H' if outcome == 'Hit' else 'M' for outcome in outcomes[-5:]]
        team = ''
        if 'Team' in group.columns:
            team_vals = group['Team'].dropna().astype(str).str.strip()
            team_vals = team_vals[team_vals != '']
            if not team_vals.empty:
                team = team_vals.iloc[-1].upper()
        rows.append({
            'player': player,
            'team': team,
            'sport': sport,
            'stat': stat,
            'direction': direction,
            'bucket': f"{player} {sport} {stat} {direction}",
            'current_streak': int(current_hit_streak),
            'current_outcome': current_outcome,
            'current_any_streak': int(current_streak),
            'longest_streak': int(longest_hit),
            'longest_miss_streak': int(longest_miss),
            'total_resolved': int(total),
            'hits': int(hits),
            'misses': int(misses),
            'hit_rate': hit_rate,
            'heat_score': heat_score,
            'heat_tier': heat_tier_from_score(heat_score),
            'last_result': current_outcome,
            'last_10': last_10,
            'last_5': last_5,
            'last_10_label': ''.join(last_10),
            'heat_cells': [
                {'n': value, 'active': value <= min(current_hit_streak, max_streak)}
                for value in range(1, max_streak + 1)
            ],
        })

    rows = sorted(
        rows,
        key=lambda row: (
            row['current_streak'],
            row['heat_score'],
            row['longest_streak'],
            row['total_resolved'],
            row['hit_rate'],
        ),
        reverse=True,
    )[:int(limit or 50)]
    _REVIEW_RUNTIME_CACHE[cache_key] = [dict(row) for row in rows]
    if resolved_df is None:
        try:
            STREAK_HEAT_INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
            pd.DataFrame(rows).to_csv(STREAK_HEAT_INDEX_PATH, index=False)
        except Exception:
            pass
    return rows


def build_candidate_review_context(
    archive_df: pd.DataFrame,
    gamelog_map: dict,
    *,
    postseason_only: bool,
    sport_filter: str = '',
    method_filter: str = '',
    outcome_filter: str = '',
    stat_filter: str = '',
    direction_filter: str = '',
    market_depth_filter: str = '',
    player_search_filter: str = '',
    player_tier_filter: str = '',
    weight_profile_filter: str = '',
    volatility_filter: str = '',
    market_gate_filter: str = '',
    bet_tier_filter: str = '',
    floor_reliability_filter: str = '',
    profile_sport_filter: str = '',
    profile_stat_filter: str = '',
    profile_direction_filter: str = '',
    profile_reliability_filter: str = '',
    profile_model_filter: str = '',
    profile_promotion_filter: str = '',
    profile_player_filter: str = '',
    streak_sport_filter: str = '',
    days_to_result_filter: str = '',
    start_date: str = '',
    end_date: str = '',
    min_confidence: str = '',
    row_limit: int = 100,
    profile_limit: int = 100,
    grade_candidate_archive_rows: GradeCandidateArchiveRows,
    summarize_candidate_archive: SummarizeCandidateArchive,
) -> dict:
    sport_filter = str(sport_filter or '').strip().upper()
    method_filter = str(method_filter or '').strip()
    outcome_filter = str(outcome_filter or '').strip().lower()
    stat_filter = str(stat_filter or '').strip().upper()
    direction_filter = str(direction_filter or '').strip().upper()
    market_depth_filter = str(market_depth_filter or '').strip()
    player_search_filter = str(player_search_filter or '').strip()
    player_tier_filter = str(player_tier_filter or '').strip().upper()
    weight_profile_filter = str(weight_profile_filter or '').strip()
    volatility_filter = str(volatility_filter or '').strip().upper()
    market_gate_filter = str(market_gate_filter or '').strip().upper()
    bet_tier_filter = str(bet_tier_filter or '').strip()
    floor_reliability_filter = str(floor_reliability_filter or '').strip().upper()
    profile_sport_filter = str(profile_sport_filter or '').strip().upper()
    profile_stat_filter = str(profile_stat_filter or '').strip().upper()
    profile_direction_filter = str(profile_direction_filter or '').strip().upper()
    profile_reliability_filter = str(profile_reliability_filter or '').strip().upper()
    profile_model_filter = str(profile_model_filter or '').strip().upper()
    profile_promotion_filter = str(profile_promotion_filter or '').strip().upper()
    profile_player_filter = str(profile_player_filter or '').strip()
    streak_sport_filter = str(streak_sport_filter or '').strip().upper()
    days_to_result_filter = str(days_to_result_filter or '').strip().lower()
    start_date = str(start_date or '').strip()
    end_date = str(end_date or '').strip()
    min_confidence = str(min_confidence or '').strip()
    try:
        row_limit = int(row_limit or 100)
    except (TypeError, ValueError):
        row_limit = 100
    try:
        profile_limit = int(profile_limit or 100)
    except (TypeError, ValueError):
        profile_limit = 100
    row_limit = max(50, min(row_limit, 750))
    profile_limit = max(50, min(profile_limit, 750))

    floor_index_full = load_floor_play_index()
    floor_buckets_full = build_floor_reliability_table(floor_index_full)
    player_profiles_full = build_player_hit_profiles(floor_index_full)
    graded = grade_candidate_archive_rows(archive_df, gamelog_map)
    if not {'ReviewTier', 'FailureReason', 'FailureSignals'}.issubset(graded.columns):
        graded = enrich_candidate_review_rows(graded)
    if 'FloorReliability' not in graded.columns:
        graded = apply_floor_reliability(graded, floor_buckets_full)
    graded = apply_player_profiles(graded, player_profiles_full)
    if postseason_only and not graded.empty and 'PostseasonOnly' in graded.columns:
        # Postseason mode is an NBA-specific lens here. Keep WNBA/MLB/etc. full-board
        # archives visible so sport-specific review pages do not look empty.
        sport_series = graded['Sport'].astype(str).str.upper()
        nba_postseason = graded['PostseasonOnly'].astype(str) == '1'
        graded = graded[(sport_series != 'NBA') | nba_postseason].copy()
    if sport_filter:
        graded = graded[graded['Sport'].astype(str).str.upper() == sport_filter].copy()
    option_source = graded.copy()
    if method_filter:
        graded = graded[graded['Method'].astype(str) == method_filter].copy()
    if outcome_filter:
        allowed = {'hit': 'Hit', 'miss': 'Miss', 'push': 'Push', 'pending': 'Pending'}
        if outcome_filter in allowed:
            graded = graded[graded['OutcomeState'].astype(str) == allowed[outcome_filter]].copy()
    if stat_filter:
        graded = graded[graded['Stat'].astype(str).str.upper() == stat_filter].copy()
    if direction_filter in {'OVER', 'UNDER'}:
        graded = graded[graded['Direction'].astype(str).str.upper() == direction_filter].copy()
    if player_search_filter and 'Player' in graded.columns:
        graded = graded[graded['Player'].fillna('').astype(str).str.contains(player_search_filter, case=False, na=False, regex=False)].copy()
    if market_depth_filter:
        graded = graded[graded['MarketDepthBucket'].astype(str) == market_depth_filter].copy()
    if player_tier_filter and 'RoleLabel' in graded.columns:
        graded = graded[graded['RoleLabel'].astype(str).str.upper() == player_tier_filter].copy()
    if weight_profile_filter and 'WeightProfile' in graded.columns:
        graded = graded[graded['WeightProfile'].astype(str) == weight_profile_filter].copy()
    if volatility_filter and 'VolatilityFlag' in graded.columns:
        graded = graded[graded['VolatilityFlag'].astype(str).str.upper() == volatility_filter].copy()
    if market_gate_filter and 'MarketGate' in graded.columns:
        graded = graded[graded['MarketGate'].astype(str).str.upper() == market_gate_filter].copy()
    if bet_tier_filter and 'ReviewTier' in graded.columns:
        graded = graded[graded['ReviewTier'].astype(str) == bet_tier_filter].copy()
    if floor_reliability_filter and 'FloorReliability' in graded.columns:
        graded = graded[graded['FloorReliability'].astype(str).str.upper() == floor_reliability_filter].copy()
    if days_to_result_filter:
        days = pd.to_numeric(graded.get('DaysToResult'), errors='coerce')
        if days_to_result_filter == 'same_day':
            graded = graded[days == 0].copy()
        elif days_to_result_filter == 'one_day':
            graded = graded[days == 1].copy()
        elif days_to_result_filter == 'two_plus':
            graded = graded[days >= 2].copy()
        elif days_to_result_filter == 'resolved':
            graded = graded[days.notna()].copy()
        elif days_to_result_filter == 'pending':
            graded = graded[days.isna()].copy()
    if start_date:
        start_dt = pd.to_datetime(start_date, errors='coerce')
        if not pd.isna(start_dt):
            graded = graded[pd.to_datetime(graded['SnapshotDate'], errors='coerce') >= start_dt].copy()
    if end_date:
        end_dt = pd.to_datetime(end_date, errors='coerce')
        if not pd.isna(end_dt):
            graded = graded[pd.to_datetime(graded['SnapshotDate'], errors='coerce') <= end_dt].copy()
    if min_confidence:
        min_conf = pd.to_numeric(pd.Series([min_confidence]), errors='coerce').iloc[0]
        if not pd.isna(min_conf):
            graded = graded[pd.to_numeric(graded.get('Confidence'), errors='coerce') >= float(min_conf)].copy()

    floor_index = filter_floor_index_for_review(
        floor_index_full,
        sport_filter=sport_filter,
        outcome_filter=outcome_filter,
        stat_filter=stat_filter,
        direction_filter=direction_filter,
        player_search_filter=player_search_filter,
        player_tier_filter=player_tier_filter,
        bet_tier_filter=bet_tier_filter,
        weight_profile_filter=weight_profile_filter,
        volatility_filter=volatility_filter,
        market_gate_filter=market_gate_filter,
        floor_reliability_filter=floor_reliability_filter,
        days_to_result_filter=days_to_result_filter,
        start_date=start_date,
        end_date=end_date,
    )

    recent_rows = []
    charts = build_candidate_review_charts(
        graded,
        floor_index_df=floor_index,
        profile_filters={
            'sport': profile_sport_filter,
            'stat': profile_stat_filter,
            'direction': profile_direction_filter,
            'reliability': profile_reliability_filter,
            'model': profile_model_filter,
            'promotion': profile_promotion_filter,
            'player': profile_player_filter,
        },
        streak_sport_filter=streak_sport_filter,
        profile_limit=profile_limit,
    )
    if not graded.empty:
        working = graded.copy()
        working['SnapshotDate'] = pd.to_datetime(working['SnapshotDate'], errors='coerce')
        recent_rows = working.sort_values(['SnapshotDate', 'Confidence'], ascending=[False, False]).head(row_limit).to_dict('records')

    sport_options = sorted(
        {
            str(v).upper()
            for v in archive_df.get('Sport', pd.Series(dtype=str)).dropna().unique()
            if str(v).strip()
        }
    )
    method_options = sorted(
        {
            str(v)
            for v in option_source.get('Method', pd.Series(dtype=str)).dropna().unique()
            if str(v).strip()
        }
    )
    stat_options = sorted(
        {
            str(v).upper()
            for v in option_source.get('Stat', pd.Series(dtype=str)).dropna().unique()
            if str(v).strip()
        }
    )
    market_depth_options = sorted(
        {
            str(v)
            for v in option_source.get('MarketDepthBucket', pd.Series(dtype=str)).dropna().unique()
            if str(v).strip()
        }
    )
    player_tier_options = sorted(
        {
            str(v).upper()
            for v in option_source.get('RoleLabel', pd.Series(dtype=str)).dropna().unique()
            if str(v).strip()
        }
    )
    weight_profile_options = sorted(
        {
            str(v)
            for v in option_source.get('WeightProfile', pd.Series(dtype=str)).dropna().unique()
            if str(v).strip()
        }
    )
    volatility_options = sorted(
        {
            str(v).upper()
            for v in option_source.get('VolatilityFlag', pd.Series(dtype=str)).dropna().unique()
            if str(v).strip()
        }
    )
    market_gate_options = sorted(
        {
            str(v).upper()
            for v in option_source.get('MarketGate', pd.Series(dtype=str)).dropna().unique()
            if str(v).strip()
        }
    )
    bet_tier_options = ['Tier 1', 'Tier 2', 'Tier 3']
    context = {
        'summary': summarize_candidate_archive(graded),
        'charts': charts,
        'rows': recent_rows,
        'sport_filter': sport_filter,
        'sport_options': sport_options,
        'method_filter': method_filter,
        'outcome_filter': outcome_filter,
        'stat_filter': stat_filter,
        'direction_filter': direction_filter,
        'market_depth_filter': market_depth_filter,
        'player_search_filter': player_search_filter,
        'player_tier_filter': player_tier_filter,
        'weight_profile_filter': weight_profile_filter,
        'volatility_filter': volatility_filter,
        'market_gate_filter': market_gate_filter,
        'bet_tier_filter': bet_tier_filter,
        'floor_reliability_filter': floor_reliability_filter,
        'profile_sport_filter': profile_sport_filter,
        'profile_stat_filter': profile_stat_filter,
        'profile_direction_filter': profile_direction_filter,
        'profile_reliability_filter': profile_reliability_filter,
        'profile_model_filter': profile_model_filter,
        'profile_promotion_filter': profile_promotion_filter,
        'profile_player_filter': profile_player_filter,
        'streak_sport_filter': streak_sport_filter,
        'days_to_result_filter': days_to_result_filter,
        'start_date': start_date,
        'end_date': end_date,
        'min_confidence': min_confidence,
        'row_limit': row_limit,
        'profile_limit': profile_limit,
        'method_options': method_options,
        'stat_options': stat_options,
        'market_depth_options': market_depth_options,
        'player_tier_options': player_tier_options,
        'weight_profile_options': weight_profile_options,
        'volatility_options': volatility_options,
        'market_gate_options': market_gate_options,
        'bet_tier_options': bet_tier_options,
        'floor_reliability_options': ['ANCHOR', 'WATCH', 'DEVELOPING', 'SMALL SAMPLE', 'AVOID'],
    }
    return _clean_display_value(context)


def expected_hit_rate_from_confidence(confidence: float) -> float | None:
    if pd.isna(confidence):
        return None
    value = float(confidence)
    # Floor: without it every sub-55 confidence collapsed to a 52.5% expectation,
    # so a long shot the model correctly rated 0.5% (MLB home-run / stolen-base
    # OVERs live at 0.5%-15% by design) was scored against a coin-flip and read
    # as underperformance. Below the lowest band a prop's own stated confidence
    # IS its expected hit rate; bands above 50 keep their established midpoints.
    if value < 50:
        return round(value, 1)
    if value < 55:
        return 52.5
    if value < 60:
        return 57.5
    if value < 65:
        return 62.5
    if value < 70:
        return 67.5
    if value < 75:
        return 72.5
    if value < 80:
        return 77.5
    return 82.5


def _bet_tier_label(value) -> str:
    if isinstance(value, dict):
        return str(value.get('label') or value.get('tier') or '').strip()
    text = str(value or '').strip()
    if not text or text.lower() in {'nan', 'none'}:
        return ''
    if text.startswith('{') and text.endswith('}'):
        try:
            parsed = ast.literal_eval(text)
            if isinstance(parsed, dict):
                return str(parsed.get('label') or parsed.get('tier') or '').strip()
        except (SyntaxError, ValueError):
            return text
    return text


def _to_float_value(value, default=float('nan')) -> float:
    try:
        if value is None or pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def derive_review_tier(row) -> str:
    label = _bet_tier_label(row.get('BetTier')).upper()
    if 'TIER 1' in label or 'FULL UNIT' in label:
        return 'Tier 1'
    if 'TIER 2' in label or 'HALF UNIT' in label:
        return 'Tier 2'
    if 'TIER 3' in label or 'SKIP' in label or 'WATCH' in label:
        return 'Tier 3'
    confidence = _to_float_value(row.get('Confidence'))
    if pd.isna(confidence):
        return 'Tier 3'
    if float(confidence) >= 80:
        return 'Tier 1'
    if float(confidence) >= 70:
        return 'Tier 2'
    return 'Tier 3'


def candidate_failure_reason(row) -> tuple[str, str]:
    if str(row.get('OutcomeState') or '').strip() != 'Miss':
        return '', ''
    signals = []
    confidence = _to_float_value(row.get('Confidence'))
    clv_line = _to_float_value(row.get('ClvLine'))
    book_count = _to_float_value(row.get('BookCount'))
    role = str(row.get('RoleLabel') or '').strip().upper()
    volatility = str(row.get('VolatilityFlag') or '').strip().upper()
    market_gate = str(row.get('MarketGate') or '').strip().upper()
    move = str(row.get('MarketMoveBucket') or '').strip()
    profile = str(row.get('WeightProfile') or '').strip()
    tier = str(row.get('ReviewTier') or derive_review_tier(row)).strip()

    if not pd.isna(confidence) and float(confidence) >= 75:
        signals.append('Confidence Overstated')
    if role in {'SUPPORT', 'BENCH'}:
        signals.append('Role Fragility')
    if volatility in {'HIGH', 'ELEVATED'}:
        signals.append('Volatility Drag')
    if market_gate in {'HOLD', 'SPLIT'}:
        signals.append('Market Gate Warning')
    if 'Against' in move:
        signals.append('Market Moved Against')
    elif move in {'No Move Data', ''}:
        signals.append('No Move Confirmation')
    if not pd.isna(clv_line) and float(clv_line) < 0:
        signals.append('Lost Closing Line')
    if not pd.isna(book_count) and float(book_count) <= 1:
        signals.append('Thin Book Market')
    if profile in {'r3_r4', 'r1_early', 'r1_late'}:
        signals.append('Context Weight Risk')
    if tier == 'Tier 1' and not signals:
        signals.append('Tier 1 Formula Miss')

    if not signals:
        signals.append('Unclassified Miss')
    return signals[0], ' | '.join(dict.fromkeys(signals[:4]))


def enrich_candidate_review_rows(graded: pd.DataFrame) -> pd.DataFrame:
    if graded is None or graded.empty:
        return graded
    working = graded.copy()
    confidence = pd.to_numeric(working.get('Confidence'), errors='coerce')
    working['ReviewTier'] = 'Tier 3'
    working.loc[confidence >= 70, 'ReviewTier'] = 'Tier 2'
    working.loc[confidence >= 80, 'ReviewTier'] = 'Tier 1'
    if 'BetTier' in working.columns:
        bet_text = working['BetTier'].fillna('').astype(str).str.upper()
        working.loc[bet_text.str.contains('TIER 1|FULL UNIT', regex=True, na=False), 'ReviewTier'] = 'Tier 1'
        working.loc[bet_text.str.contains('TIER 2|HALF UNIT', regex=True, na=False), 'ReviewTier'] = 'Tier 2'
        working.loc[bet_text.str.contains('TIER 3|SKIP|WATCH', regex=True, na=False), 'ReviewTier'] = 'Tier 3'

    working['FailureReason'] = ''
    working['FailureSignals'] = ''
    miss_mask = working.get('OutcomeState', pd.Series('', index=working.index)).astype(str).eq('Miss')
    if miss_mask.any():
        for idx, row in working.loc[miss_mask].iterrows():
            reason, signals = candidate_failure_reason(row)
            working.at[idx, 'FailureReason'] = reason
            working.at[idx, 'FailureSignals'] = signals
    return working


def build_floor_play_summary(index_df: pd.DataFrame) -> dict:
    empty_summary = {
        'candidates': 0,
        'resolved': 0,
        'hits': 0,
        'misses': 0,
        'pending': 0,
        'hit_rate': None,
        'by_sport': [],
    }
    if index_df is None or index_df.empty:
        return empty_summary
    floor = index_df[index_df.get('IsFloorPlay', pd.Series(False, index=index_df.index)).astype(bool)].copy()
    if floor.empty:
        return empty_summary
    resolved = floor[floor['OutcomeState'].isin(['Hit', 'Miss'])].copy()
    summary = {
        'candidates': int(len(floor)),
        'resolved': int(len(resolved)),
        'hits': int((floor['OutcomeState'] == 'Hit').sum()),
        'misses': int((floor['OutcomeState'] == 'Miss').sum()),
        'pending': int((floor['OutcomeState'] == 'Pending').sum()),
        'hit_rate': round(float((resolved['OutcomeState'] == 'Hit').mean()) * 100, 1) if not resolved.empty else None,
        'by_sport': [],
    }
    if 'Sport' in floor.columns:
        summary['by_sport'] = floor_rate_rows(floor.groupby('Sport'), 'sport')
    return summary


def floor_rate_rows(grouped, label_name):
    rows = []
    for label, group in grouped:
        decisive = group[group['OutcomeState'].isin(['Hit', 'Miss'])].copy()
        if decisive.empty:
            continue
        rows.append({
            label_name: str(label),
            'resolved': int(len(decisive)),
            'hits': int((decisive['OutcomeState'] == 'Hit').sum()),
            'misses': int((decisive['OutcomeState'] == 'Miss').sum()),
            'hit_rate': round(float((decisive['OutcomeState'] == 'Hit').mean()) * 100, 1),
        })
    return sorted(rows, key=lambda row: (row['hit_rate'], row['resolved']), reverse=True)


def find_best_sport_combos(resolved_df: pd.DataFrame) -> list[dict]:
    if resolved_df is None or resolved_df.empty or 'Sport' not in resolved_df.columns:
        return []
    from itertools import combinations

    day_col = 'ResultDay' if 'ResultDay' in resolved_df.columns else 'ResultDate'
    working = resolved_df.copy()
    working[day_col] = working[day_col].fillna('').astype(str)
    working = working[working[day_col].str.strip() != ''].copy()
    combo_stats: dict[str, dict] = {}
    for _, group in working.groupby(day_col):
        sports = sorted({str(s).upper() for s in group['Sport'].dropna().tolist() if str(s).strip()})
        if len(sports) < 2:
            continue
        all_hit = bool((group['OutcomeState'] == 'Hit').all())
        for combo in combinations(sports, 2):
            key = f"{combo[0]}+{combo[1]}"
            combo_stats.setdefault(key, {'days': 0, 'all_hit': 0})
            combo_stats[key]['days'] += 1
            if all_hit:
                combo_stats[key]['all_hit'] += 1

    results = []
    for combo, stats in combo_stats.items():
        if stats['days'] >= 3:
            results.append({
                'combo': combo,
                'days': int(stats['days']),
                'hit_rate': round(float(stats['all_hit'] / stats['days']) * 100, 1),
            })
    return sorted(results, key=lambda row: (row['hit_rate'], row['days']), reverse=True)


def build_cross_sport_mix_analysis(index_df: pd.DataFrame) -> dict:
    empty = {
        'multi_sport_hit_rate': None,
        'single_sport_hit_rate': None,
        'multi_sport_days': 0,
        'single_sport_days': 0,
        'best_combinations': [],
    }
    if index_df is None or index_df.empty:
        return empty
    floor = index_df[index_df.get('IsFloorPlay', pd.Series(False, index=index_df.index)).astype(bool)].copy()
    resolved = floor[floor['OutcomeState'].isin(['Hit', 'Miss'])].copy()
    if resolved.empty or 'Sport' not in resolved.columns:
        return empty
    day_col = 'ResultDay' if 'ResultDay' in resolved.columns else 'ResultDate'
    if day_col not in resolved.columns:
        return empty
    resolved[day_col] = resolved[day_col].fillna('').astype(str)
    resolved = resolved[resolved[day_col].str.strip() != ''].copy()
    if resolved.empty:
        return empty

    daily_rows = []
    for date_value, group in resolved.groupby(day_col):
        sports = sorted({str(s).upper() for s in group['Sport'].dropna().tolist() if str(s).strip()})
        daily_rows.append({
            'date': str(date_value),
            'sports': sports,
            'sport_count': len(sports),
            'all_hit': bool((group['OutcomeState'] == 'Hit').all()),
            'hit_rate': float((group['OutcomeState'] == 'Hit').mean()),
            'count': int(len(group)),
        })
    daily = pd.DataFrame(daily_rows)
    if daily.empty:
        return empty
    multi = daily[daily['sport_count'] > 1].copy()
    single = daily[daily['sport_count'] == 1].copy()
    return {
        'multi_sport_hit_rate': round(float(multi['hit_rate'].mean()) * 100, 1) if not multi.empty else None,
        'single_sport_hit_rate': round(float(single['hit_rate'].mean()) * 100, 1) if not single.empty else None,
        'multi_sport_days': int(len(multi)),
        'single_sport_days': int(len(single)),
        'best_combinations': find_best_sport_combos(resolved),
    }


def calculate_floor_efficiency(index_df: pd.DataFrame) -> dict:
    empty = {
        'floor_hit_rate': None,
        'straight_hit_rate': None,
        'floor_edge': None,
        'floor_sample': 0,
        'straight_sample': 0,
        'verdict': 'WAITING FOR RESOLVED FLOOR DATA',
    }
    if index_df is None or index_df.empty:
        return empty
    is_floor = index_df.get('IsFloorPlay', pd.Series(False, index=index_df.index)).astype(bool)
    floor_resolved = index_df[is_floor & index_df['OutcomeState'].isin(['Hit', 'Miss'])].copy()
    straight_resolved = index_df[(~is_floor) & index_df['OutcomeState'].isin(['Hit', 'Miss'])].copy()
    if floor_resolved.empty or straight_resolved.empty:
        result = empty.copy()
        result['floor_sample'] = int(len(floor_resolved))
        result['straight_sample'] = int(len(straight_resolved))
        return result
    floor_rate = float((floor_resolved['OutcomeState'] == 'Hit').mean())
    straight_rate = float((straight_resolved['OutcomeState'] == 'Hit').mean())
    edge = floor_rate - straight_rate
    verdict = (
        'FLOOR PLAYS OUTPERFORMING'
        if edge >= 0.05
        else 'FLOOR PLAYS UNDERPERFORMING'
        if edge <= -0.05
        else 'FLOOR PLAYS TRACKING WITH STRAIGHT LINES'
    )
    return {
        'floor_hit_rate': round(floor_rate * 100, 1),
        'straight_hit_rate': round(straight_rate * 100, 1),
        'floor_edge': round(edge * 100, 1),
        'floor_sample': int(len(floor_resolved)),
        'straight_sample': int(len(straight_resolved)),
        'verdict': verdict,
    }


def build_floor_play_review_charts(index_df: pd.DataFrame) -> tuple[dict, list[dict], list[dict], list[dict], list[dict], dict, dict, list[dict]]:
    empty_summary = build_floor_play_summary(pd.DataFrame())
    if index_df is None or index_df.empty:
        return empty_summary, [], [], [], [], build_cross_sport_mix_analysis(pd.DataFrame()), calculate_floor_efficiency(pd.DataFrame()), []
    floor = index_df[index_df.get('IsFloorPlay', pd.Series(False, index=index_df.index)).astype(bool)].copy()
    if floor.empty:
        return empty_summary, [], [], [], [], build_cross_sport_mix_analysis(index_df), calculate_floor_efficiency(index_df), []

    def floor_rate_rows(grouped, label_name):
        rows = []
        for label, group in grouped:
            decisive = group[group['OutcomeState'].isin(['Hit', 'Miss'])].copy()
            if decisive.empty:
                continue
            rows.append({
                label_name: str(label),
                'resolved': int(len(decisive)),
                'hits': int((decisive['OutcomeState'] == 'Hit').sum()),
                'misses': int((decisive['OutcomeState'] == 'Miss').sum()),
                'hit_rate': round(float((decisive['OutcomeState'] == 'Hit').mean()) * 100, 1),
            })
        return sorted(rows, key=lambda row: (row['hit_rate'], row['resolved']), reverse=True)

    summary = build_floor_play_summary(index_df)
    floor_by_sport = floor_rate_rows(floor.groupby('Sport'), 'sport') if 'Sport' in floor.columns else []
    floor_by_stat = floor_rate_rows(floor.groupby('Stat'), 'stat') if 'Stat' in floor.columns else []
    floor_by_tier = floor_rate_rows(floor.groupby('ReviewTier'), 'tier') if 'ReviewTier' in floor.columns else []
    tier_order = {'Tier 1': 0, 'Tier 2': 1, 'Tier 3': 2}
    floor_by_tier = sorted(floor_by_tier, key=lambda row: tier_order.get(row['tier'], 99))

    floor_mix_spots = []
    required_cols = {'Sport', 'Stat', 'Direction', 'ReviewTier'}
    if required_cols <= set(floor.columns):
        for keys, group in floor.groupby(['Sport', 'Stat', 'Direction', 'ReviewTier']):
            decisive = group[group['OutcomeState'].isin(['Hit', 'Miss'])].copy()
            if len(decisive) < 3:
                continue
            sport, stat, direction, tier = keys
            hit_rate = float((decisive['OutcomeState'] == 'Hit').mean())
            floor_mix_spots.append({
                'label': f"{sport} {stat} {direction} {tier}",
                'resolved': int(len(decisive)),
                'hits': int((decisive['OutcomeState'] == 'Hit').sum()),
                'misses': int((decisive['OutcomeState'] == 'Miss').sum()),
                'hit_rate': round(hit_rate * 100, 1),
            })
    floor_mix_spots = sorted(floor_mix_spots, key=lambda row: (row['hit_rate'], row['resolved']), reverse=True)[:10]
    floor_reliability_table = build_floor_reliability_table(index_df)
    return (
        summary,
        floor_by_sport,
        floor_by_stat[:10],
        floor_by_tier,
        floor_mix_spots,
        build_cross_sport_mix_analysis(index_df),
        calculate_floor_efficiency(index_df),
        floor_reliability_table,
    )


def build_candidate_review_charts(
    graded: pd.DataFrame,
    floor_index_df: pd.DataFrame | None = None,
    profile_filters: dict | None = None,
    streak_sport_filter: str = '',
    profile_limit: int = 100,
) -> dict:
    empty = {
        'daily': [],
        'by_confidence': [],
        'by_line': [],
        'by_review_tier': [],
        'failure_reasons': [],
        'floor_summary': {},
        'floor_by_sport': [],
        'floor_by_stat': [],
        'floor_by_tier': [],
        'floor_mix_spots': [],
        'cross_sport_mix': {},
        'floor_efficiency': {},
        'floor_reliability_table': [],
        'player_profiles': [],
        'player_profile_total': 0,
        'player_profile_options': {
            'sports': [],
            'stats': [],
            'directions': ['OVER', 'UNDER'],
            'reliabilities': ['ANCHOR', 'WATCH', 'DEVELOPING', 'AVOID'],
            'models': ['UNDERVALUED', 'CALIBRATED', 'OVERVALUED'],
            'promotions': ['PROMOTE HARD', 'PROMOTE', 'SURFACE', 'HOLD', 'STANDARD'],
        },
        'promotion_signals': [],
        'streak_heat_chart': [],
        'streak_heat_all': [],
        'streak_heat_sports': [],
        'overvalued_players': [],
        'by_stat_time': [],
        'by_direction_time': [],
        'line_movement': [],
        'tier_by_month': [],
        'expected_rate': None,
        'insights': [],
    }
    if graded is None or graded.empty:
        if floor_index_df is not None and not floor_index_df.empty:
            (
                floor_summary,
                floor_by_sport,
                floor_by_stat,
                floor_by_tier,
                floor_mix_spots,
                cross_sport_mix,
                floor_efficiency,
                floor_reliability_table,
            ) = build_floor_play_review_charts(floor_index_df)
            empty.update({
                'floor_summary': floor_summary,
                'floor_by_sport': floor_by_sport,
                'floor_by_stat': floor_by_stat,
                'floor_by_tier': floor_by_tier,
                'floor_mix_spots': floor_mix_spots,
                'cross_sport_mix': cross_sport_mix,
                'floor_efficiency': floor_efficiency,
                'floor_reliability_table': floor_reliability_table,
                'insights': check_floor_reliability_watch(floor_reliability_table)[:4],
            })
        return empty
    df = graded.copy()
    df['SnapshotDate'] = pd.to_datetime(df['SnapshotDate'], errors='coerce')
    df['ConfidenceNum'] = pd.to_numeric(df.get('Confidence'), errors='coerce')
    df['LineNum'] = pd.to_numeric(df.get('Line'), errors='coerce')
    df['DaysToResultNum'] = pd.to_numeric(df.get('DaysToResult'), errors='coerce')
    for column, default in [
        ('Stat', 'UNKNOWN'),
        ('Direction', 'UNKNOWN'),
        ('RoleLabel', 'UNSPECIFIED'),
        ('WeightProfile', 'regular'),
        ('VolatilityFlag', 'STABLE'),
        ('MarketGate', 'CLEAR'),
        ('MarketMoveBucket', 'No Move Data'),
        ('ReviewTier', 'Tier 3'),
        ('FailureReason', ''),
    ]:
        if column not in df.columns:
            df[column] = default
        df[column] = df[column].fillna('').astype(str).replace('', default)
    resolved = df[df['OutcomeState'].isin(['Hit', 'Miss'])].copy()
    if not resolved.empty:
        expected_values = resolved['ConfidenceNum'].apply(expected_hit_rate_from_confidence).dropna()
        expected_rate = round(float(expected_values.mean()), 1) if not expected_values.empty else None
    else:
        expected_rate = None

    def rate_rows(grouped, label_name):
        rows = []
        for label, group in grouped:
            if group.empty:
                continue
            rows.append({
                label_name: str(label),
                'resolved': int(len(group)),
                'hits': int((group['OutcomeState'] == 'Hit').sum()),
                'hit_rate': round(float((group['OutcomeState'] == 'Hit').mean()) * 100, 1),
            })
        return rows

    def time_series(group_col, *, date_mode='day', top_n=6):
        if resolved.empty or group_col not in resolved.columns:
            return []
        working = resolved.dropna(subset=['SnapshotDate']).copy()
        if working.empty:
            return []
        if date_mode == 'month':
            working['TimeLabel'] = working['SnapshotDate'].dt.strftime('%Y-%m')
        else:
            working['TimeLabel'] = working['SnapshotDate'].dt.strftime('%Y-%m-%d')
        group_order = (
            working.groupby(group_col)['OutcomeState']
            .size()
            .sort_values(ascending=False)
            .head(top_n)
            .index
            .tolist()
        )
        labels = sorted(working['TimeLabel'].dropna().unique().tolist())
        denom = max(len(labels) - 1, 1)
        colors = ['#84d7d2', '#d3a15f', '#8bb8ff', '#4ade80', '#f59e0b', '#f472b6', '#c084fc']
        series = []
        for idx, group_label in enumerate(group_order):
            sub = working[working[group_col] == group_label]
            grouped = sub.groupby('TimeLabel')
            points = []
            for label_idx, label in enumerate(labels):
                chunk = grouped.get_group(label) if label in grouped.groups else pd.DataFrame()
                if chunk.empty:
                    continue
                hit_rate = round(float((chunk['OutcomeState'] == 'Hit').mean()) * 100, 1)
                points.append({
                    'label': label,
                    'resolved': int(len(chunk)),
                    'hits': int((chunk['OutcomeState'] == 'Hit').sum()),
                    'hit_rate': hit_rate,
                    'x': round(label_idx / denom * 100, 2),
                    'y': round(40 - (hit_rate / 100 * 36), 2),
                })
            if points:
                series.append({
                    'label': str(group_label),
                    'color': colors[idx % len(colors)],
                    'points': points,
                })
        return series

    daily = []
    if not resolved.empty:
        daily = rate_rows(resolved.groupby(resolved['SnapshotDate'].dt.strftime('%Y-%m-%d'), dropna=True), 'date')
        daily = sorted(daily, key=lambda item: item['date'])

    by_confidence = []
    if not resolved.empty:
        bins = [0, 55, 60, 65, 70, 75, 80, 100]
        labels = ['<55', '55-60', '60-65', '65-70', '70-75', '75-80', '80+']
        working = resolved.dropna(subset=['ConfidenceNum']).copy()
        if not working.empty:
            working['ConfidenceBand'] = pd.cut(working['ConfidenceNum'], bins=bins, labels=labels, include_lowest=True, right=False)
            by_confidence = rate_rows(working.groupby('ConfidenceBand', observed=True), 'bucket')
            for row in by_confidence:
                bucket_rows = working[working['ConfidenceBand'].astype(str) == row['bucket']]
                expected_values = bucket_rows['ConfidenceNum'].apply(expected_hit_rate_from_confidence).dropna()
                row['expected_rate'] = round(float(expected_values.mean()), 1) if not expected_values.empty else None

    by_line = []
    if not resolved.empty:
        working = resolved.dropna(subset=['LineNum']).copy()
        if not working.empty:
            working['LineBucket'] = working['LineNum'].apply(lambda value: '<1' if value < 1 else '1-4.5' if value < 5 else '5-9.5' if value < 10 else '10-19.5' if value < 20 else '20+')
            by_line = rate_rows(working.groupby('LineBucket'), 'bucket')

    line_movement = []
    if not resolved.empty:
        line_movement = rate_rows(resolved.groupby('MarketMoveBucket'), 'bucket')

    by_review_tier = []
    if not resolved.empty:
        tier_order = {'Tier 1': 0, 'Tier 2': 1, 'Tier 3': 2}
        by_review_tier = rate_rows(resolved.groupby('ReviewTier'), 'tier')
        by_review_tier = sorted(by_review_tier, key=lambda row: tier_order.get(row['tier'], 99))

    failure_reasons = []
    misses = df[df['OutcomeState'].astype(str) == 'Miss'].copy()
    if not misses.empty:
        for reason, group in misses.groupby('FailureReason'):
            if not str(reason).strip():
                continue
            failure_reasons.append({
                'reason': str(reason),
                'misses': int(len(group)),
                'share': round(float(len(group) / len(misses)) * 100, 1),
            })
        failure_reasons = sorted(failure_reasons, key=lambda row: row['misses'], reverse=True)

    floor_source = floor_index_df if floor_index_df is not None and not floor_index_df.empty else df
    (
        floor_summary,
        floor_by_sport,
        floor_by_stat,
        floor_by_tier,
        floor_mix_spots,
        cross_sport_mix,
        floor_efficiency,
        floor_reliability_table,
    ) = build_floor_play_review_charts(floor_source)

    profile_source = floor_index_df if floor_index_df is not None and not floor_index_df.empty else df
    player_profiles = [
        row for row in build_player_hit_profiles(profile_source)
        if row.get('resolved', 0) >= 3
    ]
    missed_bucket_frequency = build_missed_winner_bucket_frequency(df, lookback_days=7)
    for row in player_profiles:
        promotion = calculate_promotion_signal(row, missed_bucket_frequency)
        row['promotion_signal'] = promotion['signal']
        row['promotion_reason'] = promotion['reason']
        row['promotion_action'] = promotion['action']
        row['missed_winner_count'] = promotion['missed_count']
        row['missed_winner_a_plus'] = promotion['bucket_a_plus']
        row['missed_winner_avg_grade'] = promotion['bucket_avg_grade']
        row['missed_winner_last_seen'] = promotion['last_seen']
    profile_filters = profile_filters or {}
    try:
        profile_limit = int(profile_limit or 100)
    except (TypeError, ValueError):
        profile_limit = 100
    profile_limit = max(50, min(profile_limit, 750))
    player_profile_options = {
        'sports': sorted({row.get('sport') for row in player_profiles if row.get('sport')}),
        'stats': sorted({row.get('stat') for row in player_profiles if row.get('stat')}),
        'directions': ['OVER', 'UNDER'],
        'reliabilities': ['ANCHOR', 'WATCH', 'DEVELOPING', 'AVOID'],
        'models': ['UNDERVALUED', 'CALIBRATED', 'OVERVALUED'],
        'promotions': ['PROMOTE HARD', 'PROMOTE', 'SURFACE', 'HOLD', 'STANDARD'],
    }

    player_profile_table = list(player_profiles)
    profile_sport = str(profile_filters.get('sport') or '').strip().upper()
    profile_stat = str(profile_filters.get('stat') or '').strip().upper()
    profile_direction = str(profile_filters.get('direction') or '').strip().upper()
    profile_reliability = str(profile_filters.get('reliability') or '').strip().upper()
    profile_model = str(profile_filters.get('model') or '').strip().upper()
    profile_promotion = str(profile_filters.get('promotion') or '').strip().upper()
    profile_player = str(profile_filters.get('player') or '').strip()
    if profile_sport:
        player_profile_table = [row for row in player_profile_table if str(row.get('sport') or '').upper() == profile_sport]
    if profile_stat:
        player_profile_table = [row for row in player_profile_table if str(row.get('stat') or '').upper() == profile_stat]
    if profile_direction in {'OVER', 'UNDER'}:
        player_profile_table = [row for row in player_profile_table if str(row.get('direction') or '').upper() == profile_direction]
    if profile_reliability:
        player_profile_table = [row for row in player_profile_table if str(row.get('reliability') or '').upper() == profile_reliability]
    if profile_model:
        player_profile_table = [row for row in player_profile_table if str(row.get('model_accuracy') or '').upper() == profile_model]
    if profile_promotion:
        player_profile_table = [row for row in player_profile_table if str(row.get('promotion_signal') or '').upper() == profile_promotion]
    if profile_player:
        needle = profile_player.lower()
        player_profile_table = [row for row in player_profile_table if needle in str(row.get('player') or '').lower()]
    player_profile_filtered_total = len(player_profile_table)
    player_profile_table = player_profile_table[:profile_limit]

    promotion_order = {'PROMOTE HARD': 0, 'PROMOTE': 1, 'SURFACE': 2, 'HOLD': 3, 'STANDARD': 4}
    promotion_signals = [
        row for row in player_profiles
        if row.get('promotion_signal') in {'PROMOTE HARD', 'PROMOTE', 'SURFACE', 'HOLD'}
    ]
    promotion_signals = sorted(
        promotion_signals,
        key=lambda row: (
            promotion_order.get(row.get('promotion_signal'), 9),
            -(row.get('missed_winner_count') or 0),
            -(row.get('resolved') or 0),
            -(row.get('hit_rate') or 0),
        ),
    )[:20]
    overvalued_players = [
        row for row in player_profiles
        if row.get('model_accuracy') == 'OVERVALUED' and row.get('resolved', 0) >= 10
    ][:10]
    insights = find_candidate_review_nuances(resolved)
    for row in overvalued_players[:4]:
        insights.append({
            'type': 'PLAYER QC',
            'title': f"{row.get('player')} {row.get('stat')} {row.get('direction')} overvalued",
            'detail': (
                f"Model averaged {row.get('avg_confidence')} confidence, but the bucket is "
                f"{row.get('hits')}-{row.get('misses')} ({row.get('hit_rate')}%) over {row.get('resolved')} resolved props."
            ),
        })
    if floor_efficiency.get('floor_sample', 0) >= 10 and floor_efficiency.get('straight_sample', 0) >= 10:
        insights.append({
            'type': 'FLOOR EFFICIENCY',
            'title': floor_efficiency.get('verdict', 'Floor Efficiency'),
            'detail': (
                f"Floor plays are hitting {floor_efficiency.get('floor_hit_rate')}% "
                f"vs straight-line rows at {floor_efficiency.get('straight_hit_rate')}% "
                f"over {floor_efficiency.get('floor_sample')} floor and {floor_efficiency.get('straight_sample')} straight resolved props."
            ),
        })
    insights.extend(check_floor_reliability_watch(floor_reliability_table)[:4])
    for source, label_key, prefix in [
        (by_confidence, 'bucket', 'Confidence'),
        (by_line, 'bucket', 'Line'),
    ]:
        qualified = [row for row in source if row['resolved'] >= 10]
        if qualified:
            best = max(qualified, key=lambda row: (row['hit_rate'], row['resolved']))
            worst = min(qualified, key=lambda row: (row['hit_rate'], -row['resolved']))
            insights.append(f"{prefix} sweet spot: {best[label_key]} at {best['hit_rate']}% over {best['resolved']} resolved.")
            insights.append(f"{prefix} caution: {worst[label_key]} at {worst['hit_rate']}% over {worst['resolved']} resolved.")

    streak_heat_all = build_streak_heat_chart(limit=50)
    streak_heat_sports = sorted({row.get('sport') for row in streak_heat_all if row.get('sport')})
    streak_sport_filter = str(streak_sport_filter or '').strip().upper()
    streak_heat_chart = [
        row for row in streak_heat_all
        if not streak_sport_filter or row.get('sport') == streak_sport_filter
    ][:25]

    return {
        'daily': daily,
        'by_confidence': by_confidence,
        'by_line': by_line,
        'by_review_tier': by_review_tier,
        'failure_reasons': failure_reasons,
        'floor_summary': floor_summary,
        'floor_by_sport': floor_by_sport,
        'floor_by_stat': floor_by_stat,
        'floor_by_tier': floor_by_tier,
        'floor_mix_spots': floor_mix_spots,
        'cross_sport_mix': cross_sport_mix,
        'floor_efficiency': floor_efficiency,
        'floor_reliability_table': floor_reliability_table[:80],
        'player_profiles': player_profile_table,
        'player_profile_total': len(player_profiles),
        'player_profile_filtered_total': player_profile_filtered_total,
        'player_profile_options': player_profile_options,
        'promotion_signals': promotion_signals,
        'streak_heat_chart': streak_heat_chart,
        'streak_heat_all': streak_heat_all,
        'streak_heat_sports': streak_heat_sports,
        'overvalued_players': overvalued_players,
        'by_stat_time': time_series('Stat', top_n=7),
        'by_direction_time': time_series('Direction', top_n=2),
        'line_movement': line_movement,
        'tier_by_month': time_series('RoleLabel', date_mode='month', top_n=6),
        'expected_rate': expected_rate,
        'insights': insights[:8],
    }


def find_candidate_review_nuances(resolved: pd.DataFrame) -> list[dict]:
    if resolved is None or resolved.empty:
        return []
    df = resolved.copy()
    df['ConfidenceNum'] = pd.to_numeric(df.get('ConfidenceNum', df.get('Confidence')), errors='coerce')
    nuances: list[dict] = []

    def hit_rate(rows: pd.DataFrame) -> float | None:
        if rows.empty:
            return None
        return float((rows['OutcomeState'] == 'Hit').mean())

    def add(kind: str, title: str, detail: str) -> None:
        nuances.append({'type': kind, 'title': title, 'detail': detail})

    support_high_conf = df[
        (df.get('RoleLabel', pd.Series('', index=df.index)).astype(str).str.upper() == 'SUPPORT')
        & (df['ConfidenceNum'] >= 70)
    ]
    support_rate = hit_rate(support_high_conf)
    if len(support_high_conf) >= 10 and support_rate is not None and support_rate < 0.55:
        add(
            'CAUTION',
            'Support Tier Overconfident',
            f"Support players at 70+ confidence are hitting {support_rate:.0%} over {len(support_high_conf)} resolved props.",
        )

    over_rows = df[df.get('Direction', pd.Series('', index=df.index)).astype(str).str.upper() == 'OVER']
    under_rows = df[df.get('Direction', pd.Series('', index=df.index)).astype(str).str.upper() == 'UNDER']
    over_rate = hit_rate(over_rows)
    under_rate = hit_rate(under_rows)
    if len(over_rows) >= 10 and len(under_rows) >= 10 and over_rate is not None and under_rate is not None:
        gap = abs(over_rate - under_rate)
        if gap >= 0.10:
            better = 'UNDER' if under_rate > over_rate else 'OVER'
            add(
                'SWEET SPOT',
                f'{better}s Outperforming',
                f"{better}s are hitting {max(over_rate, under_rate):.0%} vs {min(over_rate, under_rate):.0%} on the other side in this slice.",
            )

    gate_series = df.get('MarketGate', pd.Series('', index=df.index)).astype(str).str.upper()
    clear_rows = df[gate_series == 'CLEAR']
    hold_rows = df[gate_series == 'HOLD']
    clear_rate = hit_rate(clear_rows)
    hold_rate = hit_rate(hold_rows)
    if len(clear_rows) >= 5 and len(hold_rows) >= 5 and clear_rate is not None and hold_rate is not None:
        if clear_rate > hold_rate + 0.08:
            add(
                'VALIDATED',
                'Market Gate Adding Value',
                f"CLEAR props are hitting {clear_rate:.0%} vs HOLD props at {hold_rate:.0%}.",
            )
        elif hold_rate > clear_rate:
            add(
                'REVIEW',
                'Market Gate May Be Over-Pruning',
                f"HOLD props are hitting {hold_rate:.0%} vs CLEAR props at {clear_rate:.0%}.",
            )

    profiles = ['r1_early', 'r1_late', 'r2', 'r3_r4', 'regular']
    profile_series = df.get('WeightProfile', pd.Series('', index=df.index)).astype(str)
    for profile in profiles:
        sub = df[profile_series == profile]
        rate = hit_rate(sub)
        if len(sub) >= 10 and rate is not None:
            if rate >= 0.72:
                add('SWEET SPOT', f'{profile} Profile Strong', f"{profile} is hitting {rate:.0%} over {len(sub)} resolved props.")
            elif rate < 0.50:
                add('CAUTION', f'{profile} Profile Weak', f"{profile} is hitting only {rate:.0%} over {len(sub)} resolved props.")

    volatility_series = df.get('VolatilityFlag', pd.Series('', index=df.index)).astype(str).str.upper()
    high_vol = df[volatility_series == 'HIGH']
    high_vol_rate = hit_rate(high_vol)
    if len(high_vol) >= 10 and high_vol_rate is not None and high_vol_rate < 0.50:
        add('CAUTION', 'High Volatility Drag', f"HIGH volatility props are hitting {high_vol_rate:.0%} over {len(high_vol)} resolved props.")

    tier_series = df.get('ReviewTier', pd.Series('', index=df.index)).astype(str)
    for tier in ['Tier 1', 'Tier 2', 'Tier 3']:
        sub = df[tier_series == tier]
        rate = hit_rate(sub)
        if len(sub) >= 10 and rate is not None:
            if tier == 'Tier 1' and rate < 0.60:
                add('REVIEW', 'Tier 1 Needs Tightening', f"Tier 1 is hitting {rate:.0%} over {len(sub)} resolved props in this slice.")
            elif tier == 'Tier 3' and rate >= 0.60:
                add('SWEET SPOT', 'Tier 3 May Be Undervalued', f"Tier 3 is hitting {rate:.0%} over {len(sub)} resolved props.")

    misses = df[df['OutcomeState'].astype(str) == 'Miss'].copy()
    if not misses.empty and 'FailureReason' in misses.columns:
        top_reason = misses['FailureReason'].replace('', pd.NA).dropna().value_counts()
        if not top_reason.empty:
            reason = str(top_reason.index[0])
            count = int(top_reason.iloc[0])
            share = count / len(misses)
            if count >= 5:
                add('FAILURE PATTERN', reason, f"{reason} explains {share:.0%} of misses in this filtered slice ({count} misses).")

    if 'Method' in df.columns:
        floor_rows = df[df['Method'].astype(str).str.contains('floor', case=False, na=False)].copy()
        non_floor_rows = df[~df['Method'].astype(str).str.contains('floor', case=False, na=False)].copy()
        floor_rate = hit_rate(floor_rows)
        non_floor_rate = hit_rate(non_floor_rows)
        if len(floor_rows) >= 10 and floor_rate is not None:
            if non_floor_rate is not None and len(non_floor_rows) >= 10 and floor_rate >= non_floor_rate + 0.08:
                add('SWEET SPOT', 'Floor Plays Beating Board', f"Floor plays are hitting {floor_rate:.0%} vs {non_floor_rate:.0%} for non-floor rows in this slice.")
            elif floor_rate >= 0.65:
                add('SWEET SPOT', 'Floor Plays Holding Up', f"Floor plays are hitting {floor_rate:.0%} over {len(floor_rows)} resolved props.")

    return nuances
