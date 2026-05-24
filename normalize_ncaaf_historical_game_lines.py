from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from app import _format_ncaaf_game_lines_history


CANONICAL_COLUMNS = [
    'Date',
    'Season',
    'Week',
    'Away',
    'Home',
    'Spread',
    'Total',
    'AwayScore',
    'HomeScore',
    'HomeSpread',
    'AwaySpread',
    'OpenHomeSpread',
    'OpenAwaySpread',
    'OpenTotal',
    'CloseTotal',
    'HomeCloseML',
    'AwayCloseML',
    'Source',
]


RENAME_MAP = {
    'gameday': 'Date',
    'date': 'Date',
    'season': 'Season',
    'week': 'Week',
    'away_team': 'Away',
    'awayteam': 'Away',
    'away': 'Away',
    'home_team': 'Home',
    'hometeam': 'Home',
    'home': 'Home',
    'spread_line': 'AwaySpread',
    'away_spread': 'AwaySpread',
    'awayspread': 'AwaySpread',
    'home_spread': 'HomeSpread',
    'homespread': 'HomeSpread',
    'spread': 'Spread',
    'total_line': 'Total',
    'total': 'Total',
    'away_score': 'AwayScore',
    'awayscore': 'AwayScore',
    'home_score': 'HomeScore',
    'homescore': 'HomeScore',
    'open_total': 'OpenTotal',
    'closetotal': 'CloseTotal',
    'close_total': 'CloseTotal',
    'open_home_spread': 'OpenHomeSpread',
    'open_away_spread': 'OpenAwaySpread',
    'home_ml': 'HomeCloseML',
    'away_ml': 'AwayCloseML',
}


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    renamed = {}
    for col in df.columns:
        key = ''.join(ch.lower() for ch in str(col).strip() if ch.isalnum() or ch == '_')
        renamed[col] = RENAME_MAP.get(key, col)
    return df.rename(columns=renamed).copy()


def main() -> None:
    parser = argparse.ArgumentParser(description='Normalize college football historical game lines for Bankroll Kings.')
    parser.add_argument('input', help='Source CSV path')
    parser.add_argument('--output', default='data/historical/NCAAF_GameLines_History.csv', help='Normalized output CSV path')
    parser.add_argument('--source', default='manual_import', help='Source label written into the output file')
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)
    if not input_path.exists():
        raise SystemExit(f'Input file not found: {input_path}')

    raw = pd.read_csv(input_path)
    working = normalize_columns(raw)
    if 'Source' not in working.columns:
        working['Source'] = args.source
    formatted = _format_ncaaf_game_lines_history(working)
    for col in CANONICAL_COLUMNS:
        if col not in formatted.columns:
            formatted[col] = pd.NA
    formatted = formatted[CANONICAL_COLUMNS].copy()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    formatted.to_csv(output_path, index=False)
    print(f'Wrote {len(formatted)} rows to {output_path}')


if __name__ == '__main__':
    main()
