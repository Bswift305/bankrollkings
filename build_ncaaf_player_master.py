from __future__ import annotations

import argparse
from pathlib import Path

from app import build_ncaaf_player_master


def main() -> None:
    parser = argparse.ArgumentParser(description='Build the CFB current-roster + career-stats master table.')
    parser.add_argument('--last-season', type=int, default=None, help='Season to treat as last season when setting LastSeasonTeam')
    parser.add_argument('--output', default='data/tracking/NCAAF_PlayerMaster.csv', help='Output CSV path')
    args = parser.parse_args()

    master = build_ncaaf_player_master(last_season=args.last_season)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    master.to_csv(output_path, index=False)
    print(f'Wrote {len(master)} rows to {output_path}')


if __name__ == '__main__':
    main()
