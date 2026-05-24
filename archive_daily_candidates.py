from pathlib import Path
import pandas as pd
import numpy as np

from app import (
    app,
    CANDIDATE_ARCHIVE_PATH,
    load_gamelogs,
    load_props,
    load_nfl_props,
    load_nfl_game_market_odds,
    load_nfl_schedule,
    load_ncaaf_props,
    load_ncaaf_game_market_odds,
    load_ncaaf_schedule,
    load_wnba_props,
    load_wnba_game_market_odds,
    load_wnba_schedule,
    load_wnba_gamelogs,
    load_mlb_props,
    load_mlb_game_market_odds,
    load_mlb_schedule,
    load_mlb_gamelogs,
    load_player_snapshot,
    load_current_team_overrides,
    build_current_team_map,
    build_trend_board,
    build_football_live_prop_board,
    build_wnba_prop_board,
    build_wnba_method_board,
    build_mlb_method_board,
    get_team_filter,
    archive_trend_candidates,
    archive_football_method_candidates,
    archive_wnba_candidates,
    archive_wnba_method_candidates,
    archive_mlb_method_candidates,
    archive_method_candidates,
    american_odds_to_implied_prob,
)


def archive_routes():
    routes = [
        "/market-edge?postseason=1&sample=current&date=today",
        "/props/floor?postseason=1&sample=current&date=today",
        "/sports/wnba?date=today",
        "/sports/mlb?date=today",
    ]
    client = app.test_client()
    statuses = []
    for route in routes:
        response = client.get(route)
        statuses.append((route, response.status_code))
    return statuses


def archive_trends():
    logs = load_gamelogs()
    props = load_props()
    snapshot = load_player_snapshot()
    overrides = load_current_team_overrides()
    current_team_map = build_current_team_map(logs, snapshot, overrides)
    rows = build_trend_board(
        logs,
        current_team_map,
        props_df=props,
        player_snapshot=snapshot,
        team_filter=get_team_filter(True),
        sample_mode='current',
        stat_filter='all',
    )
    written = archive_trend_candidates(
        rows,
        postseason_only=True,
        sample_mode='current',
    )
    return written


def _best_price(rows, column):
    priced = rows[pd.to_numeric(rows.get(column), errors='coerce').notna()].copy()
    if priced.empty:
        return None, ''
    priced[column] = pd.to_numeric(priced[column], errors='coerce')
    best = priced.sort_values(column, ascending=False).iloc[0]
    return best.get(column), str(best.get('Book') or '').strip()


def archive_available_props_for_sport(sport, props, max_rows=10000):
    if props is None or props.empty:
        return 0
    required = {'Player', 'Stat', 'Game'}
    if not required.issubset(props.columns):
        return 0

    working = props.copy()
    for col in ['Line', 'CurrentLine', 'OpenLine', 'CloseLine', 'OverOdds', 'UnderOdds', 'OpenOverOdds', 'OpenUnderOdds', 'CloseOverOdds', 'CloseUnderOdds']:
        if col in working.columns:
            working[col] = pd.to_numeric(working[col], errors='coerce')
    if 'CurrentLine' not in working.columns:
        working['CurrentLine'] = working.get('Line')
    if 'Line' not in working.columns:
        working['Line'] = working.get('CurrentLine')

    group_cols = ['Player', 'Stat', 'Game', 'CurrentLine']
    rows = []
    for key, group in working.groupby(group_cols, dropna=False, sort=False):
        player, stat, game, current_line = key
        player = str(player or '').strip()
        stat = str(stat or '').strip()
        game = str(game or '').strip()
        line = current_line
        if pd.isna(line):
            numeric_lines = pd.to_numeric(group.get('Line'), errors='coerce').dropna()
            line = numeric_lines.iloc[0] if not numeric_lines.empty else np.nan
        if not player or not stat or not game or pd.isna(line):
            continue

        team = str(group.get('Team', pd.Series([''])).dropna().astype(str).replace('nan', '').head(1).iloc[0] if 'Team' in group.columns and not group['Team'].dropna().empty else '').strip()
        books = sorted({str(book).strip() for book in group.get('Book', pd.Series(dtype=str)).dropna().tolist() if str(book).strip()})
        book_count = len(books)
        open_line = pd.to_numeric(group.get('OpenLine'), errors='coerce').dropna()
        close_line = pd.to_numeric(group.get('CloseLine'), errors='coerce').dropna()
        last_updated = ''
        if 'LastUpdated' in group.columns:
            last_updated = str(group['LastUpdated'].dropna().astype(str).head(1).iloc[0]) if not group['LastUpdated'].dropna().empty else ''
        snapshot_date = pd.to_datetime(last_updated, errors='coerce')
        snapshot_date = snapshot_date.date().isoformat() if pd.notna(snapshot_date) else None

        for direction, odds_col, open_odds_col, close_odds_col in [
            ('OVER', 'OverOdds', 'OpenOverOdds', 'CloseOverOdds'),
            ('UNDER', 'UnderOdds', 'OpenUnderOdds', 'CloseUnderOdds'),
        ]:
            best_price, best_book = _best_price(group, odds_col)
            if best_price is None:
                continue
            implied = american_odds_to_implied_prob(best_price)
            confidence = round(float(implied or 0) * 100, 1) if implied is not None else ''
            rows.append({
                'player': player,
                'team': team,
                'stat': stat.upper(),
                'direction': direction,
                'line': float(line),
                'confidence': confidence,
                'raw_confidence': confidence,
                'avg': '',
                'weighted_over_rate': '',
                'weighted_under_rate': '',
                'market_price': best_price,
                'current_line': float(line),
                'open_line': float(open_line.iloc[0]) if not open_line.empty else '',
                'close_line': float(close_line.iloc[0]) if not close_line.empty else '',
                'bet_line': '',
                'open_price': pd.to_numeric(group.get(open_odds_col), errors='coerce').dropna().iloc[0] if open_odds_col in group.columns and not pd.to_numeric(group.get(open_odds_col), errors='coerce').dropna().empty else '',
                'close_price': pd.to_numeric(group.get(close_odds_col), errors='coerce').dropna().iloc[0] if close_odds_col in group.columns and not pd.to_numeric(group.get(close_odds_col), errors='coerce').dropna().empty else '',
                'bet_price': '',
                'line_move': '',
                'clv_line': '',
                'clv_price_pct': '',
                'market_gap_pct': '',
                'market_view': {'label': 'Available Market', 'note': f'Archived from {book_count} book(s).'},
                'book': best_book,
                'book_count': book_count,
                'edge_pct': '',
                'ev_pct': '',
                'matchup': game.replace('@', ' @ '),
                'opponent': '',
                'game_day': '',
                'situations': ['FULL BOARD ARCHIVE'],
                'method_supports': ['Available Props'],
                'market_calibration_tags': books,
                'public_trend_note': '',
                'baseline_reason': f'Full-board available {sport} prop archive.',
                'weight_profile': 'full_board',
                '_snapshot_date': snapshot_date,
            })

    written = 0
    by_snapshot = {}
    for row in rows:
        by_snapshot.setdefault(row.pop('_snapshot_date'), []).append(row)
    for snapshot_date, snapshot_rows in by_snapshot.items():
        written += archive_method_candidates(
            'Available Props',
            snapshot_rows,
            postseason_only=False,
            sample_mode='available',
            snapshot_date=snapshot_date,
            max_rows=max_rows,
            sport=sport,
        )
    return written


def archive_available_props():
    return {
        'NBA': archive_available_props_for_sport('NBA', load_props()),
        'WNBA': archive_available_props_for_sport('WNBA', load_wnba_props()),
        'MLB': archive_available_props_for_sport('MLB', load_mlb_props()),
        'NFL': archive_available_props_for_sport('NFL', load_nfl_props()),
        'NCAAF': archive_available_props_for_sport('NCAAF', load_ncaaf_props()),
    }


def archive_wnba():
    props = load_wnba_props()
    odds = load_wnba_game_market_odds()
    schedule = load_wnba_schedule()
    gamelogs = load_wnba_gamelogs()
    counts = {}
    for method_key, method_name in [('market_edge', 'Market Edge'), ('floor_plays', 'Floor Plays'), ('trends', 'Trends')]:
        rows = build_wnba_method_board(
            method_key,
            props,
            odds,
            schedule,
            gamelogs=gamelogs,
            date_filter='today',
            stat_filter='',
            direction_filter='all',
            search_query='',
        )
        counts[method_name] = archive_wnba_method_candidates(
            method_name,
            rows,
            postseason_only=False,
            sample_mode='current',
            min_market_prob=55 if method_key == 'trends' else 58,
            min_lean_gap=3 if method_key == 'trends' else 5,
        )
    return counts


def archive_mlb():
    props = load_mlb_props()
    odds = load_mlb_game_market_odds()
    schedule = load_mlb_schedule()
    gamelogs = load_mlb_gamelogs()
    counts = {}
    for method_key, method_name in [('market_edge', 'Market Edge'), ('floor_plays', 'Floor Plays'), ('trends', 'Trends')]:
        rows = build_mlb_method_board(
            method_key,
            props,
            odds,
            schedule,
            gamelogs=gamelogs,
            date_filter='today',
            stat_filter='',
            direction_filter='all',
            search_query='',
        )
        counts[method_name] = archive_mlb_method_candidates(
            method_name,
            rows,
            postseason_only=False,
            sample_mode='current',
            min_market_prob=55 if method_key == 'trends' else 58,
            min_lean_gap=3 if method_key == 'trends' else 4,
        )
    return counts


def archive_football():
    counts = {}
    football_sports = {
        'NFL': (load_nfl_props(), load_nfl_game_market_odds(), load_nfl_schedule()),
        'NCAAF': (load_ncaaf_props(), load_ncaaf_game_market_odds(), load_ncaaf_schedule()),
    }
    for sport, (props, odds, schedule) in football_sports.items():
        for method_key, method_name in [('props', 'Props'), ('trends', 'Trends')]:
            rows = build_football_live_prop_board(
                props,
                odds,
                schedule,
                method_key=method_key,
                date_filter='all',
                stat_filter='',
                direction_filter='all',
                search_query='',
            )
            counts[f'{sport}-{method_name}'] = archive_football_method_candidates(
                method_name,
                rows,
                sport=sport,
                postseason_only=False,
                sample_mode='current',
                min_market_prob=55 if method_key == 'trends' else 57,
                min_lean_gap=3 if method_key == 'trends' else 4,
            )
    return counts


def archive_row_count():
    if not CANDIDATE_ARCHIVE_PATH.exists():
        return 0
    try:
        df = pd.read_csv(CANDIDATE_ARCHIVE_PATH)
        return int(len(df))
    except Exception:
        return 0


def main():
    before = archive_row_count()
    statuses = archive_routes()
    available_written = archive_available_props()
    trend_written = archive_trends()
    wnba_written = archive_wnba()
    mlb_written = archive_mlb()
    football_written = archive_football()
    after = archive_row_count()

    print("BANKROLL KINGS - Archive Daily Candidates")
    for route, status in statuses:
        print(f"{status} {route}")
    print(f"Available prop rows archived: {available_written}")
    print(f"Trends rows archived: {trend_written}")
    print(f"WNBA rows archived: {wnba_written}")
    print(f"MLB rows archived: {mlb_written}")
    print(f"Football rows archived: {football_written}")
    print(f"Archive rows: {before} -> {after}")
    if any(status not in {200, 401, 403} for _, status in statuses):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
