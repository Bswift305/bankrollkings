"""Thin wrapper for historical NCAAF game lines from The Odds API."""

from __future__ import annotations

import sys

import fetch_oddsapi_historical_game_lines as shared_fetch


def main() -> int:
    if "--sport" not in sys.argv[1:]:
        sys.argv.insert(1, "--sport")
        sys.argv.insert(2, "americanfootball_ncaaf")
    return shared_fetch.main()


if __name__ == "__main__":
    raise SystemExit(main())
