"""Thin wrapper for college football player props using the shared props fetcher."""

from __future__ import annotations

import sys

import fetch_player_props as shared_fetch


def main() -> int:
    if "--sport" not in sys.argv[1:]:
        sys.argv.insert(1, "--sport")
        sys.argv.insert(2, "americanfootball_ncaaf")
    if "--bookmakers" not in sys.argv[1:]:
        sys.argv.insert(3, "--bookmakers")
        sys.argv.insert(4, "draftkings,caesars,fanduel,betmgm")
    return shared_fetch.main()


if __name__ == "__main__":
    raise SystemExit(main())
