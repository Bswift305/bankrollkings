"""Thin wrapper for MLB game lines using the shared Odds API game-lines fetcher."""

from __future__ import annotations

import sys

import fetch_game_lines as shared_fetch


def main() -> int:
    if "--sport" not in sys.argv[1:]:
        sys.argv.insert(1, "--sport")
        sys.argv.insert(2, "baseball_mlb")
    if "--bookmakers" not in sys.argv[1:]:
        sys.argv.insert(3, "--bookmakers")
        sys.argv.insert(4, "draftkings,caesars,fanduel,betmgm")
    return shared_fetch.main()


if __name__ == "__main__":
    raise SystemExit(main())
