from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from app import _format_ncaaf_current_roster


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    rename_map = {}
    for col in df.columns:
        key = ''.join(ch.lower() for ch in str(col).strip() if ch.isalnum() or ch == '_')
        mapped = {
            'playerid': 'PlayerID',
            'id': 'PlayerID',
            'player': 'Player',
            'playername': 'Player',
            'name': 'Player',
            'fullname': 'Player',
            'team': 'CurrentTeam',
            'currentteam': 'CurrentTeam',
            'school': 'CurrentTeam',
            'position': 'Position',
            'pos': 'Position',
            'class': 'Class',
            'year': 'Class',
            'height': 'Height',
            'weight': 'Weight',
            'jersey': 'Jersey',
            'number': 'Jersey',
            'status': 'Status',
        }.get(key)
        if mapped:
            rename_map[col] = mapped
    return df.rename(columns=rename_map).copy()


CANONICAL_COLUMNS = ['PlayerID', 'Player', 'CurrentTeam', 'Position', 'Class', 'Height', 'Weight', 'Jersey', 'Status']


def main() -> None:
    parser = argparse.ArgumentParser(description='Normalize a current CFB roster export for Bankroll Kings.')
    parser.add_argument('input', help='Source CSV path')
    parser.add_argument('--output', default='data/rosters/NCAAF_CurrentRoster.csv', help='Normalized output CSV path')
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)
    if not input_path.exists():
        raise SystemExit(f'Input file not found: {input_path}')

    raw = pd.read_csv(input_path)
    working = normalize_columns(raw)
    formatted = _format_ncaaf_current_roster(working)
    export = formatted[CANONICAL_COLUMNS].copy()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    export.to_csv(output_path, index=False)
    print(f'Wrote {len(export)} rows to {output_path}')


if __name__ == '__main__':
    main()
