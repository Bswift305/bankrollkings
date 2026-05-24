from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from app import _format_ncaaf_player_stats_history


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
            'team': 'Team',
            'school': 'Team',
            'position': 'Position',
            'pos': 'Position',
            'class': 'Class',
            'year': 'Class',
            'season': 'Season',
            'games': 'Games',
            'gp': 'Games',
            'passingyards': 'PassYds',
            'passyards': 'PassYds',
            'passingtds': 'PassTD',
            'passtds': 'PassTD',
            'passinginterceptions': 'PassInt',
            'interceptions': 'PassInt',
            'rushyards': 'RushYds',
            'rushingyards': 'RushYds',
            'rushtds': 'RushTD',
            'rushingtds': 'RushTD',
            'receptions': 'Receptions',
            'recyards': 'RecYds',
            'receivingyards': 'RecYds',
            'rectds': 'RecTD',
            'receivingtds': 'RecTD',
            'tackles': 'Tackles',
            'sacks': 'Sacks',
            'definterceptions': 'DefInt',
            'defensiveinterceptions': 'DefInt',
        }.get(key)
        if mapped:
            rename_map[col] = mapped
    return df.rename(columns=rename_map).copy()


CANONICAL_COLUMNS = [
    'PlayerID', 'Player', 'Team', 'Position', 'Class', 'Season', 'Games',
    'PassYds', 'PassTD', 'PassInt', 'RushYds', 'RushTD',
    'Receptions', 'RecYds', 'RecTD', 'Tackles', 'Sacks', 'DefInt'
]


def main() -> None:
    parser = argparse.ArgumentParser(description='Normalize a CFB player stats export for Bankroll Kings.')
    parser.add_argument('input', help='Source CSV path')
    parser.add_argument('--output', default='data/historical/NCAAF_PlayerStats_History.csv', help='Normalized output CSV path')
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)
    if not input_path.exists():
        raise SystemExit(f'Input file not found: {input_path}')

    raw = pd.read_csv(input_path)
    working = normalize_columns(raw)
    formatted = _format_ncaaf_player_stats_history(working)
    export = formatted[CANONICAL_COLUMNS].copy()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    export.to_csv(output_path, index=False)
    print(f'Wrote {len(export)} rows to {output_path}')


if __name__ == '__main__':
    main()
