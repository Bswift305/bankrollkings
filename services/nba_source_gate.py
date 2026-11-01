"""NBA.com data-rights gate (docs/legal_ip_audit.md).

`BK_NBA_STATS_ENABLED` defaults **OFF**. While off, information whose lineage reaches NBA.com /
stats.nba.com / cdn.nba.com / official.nba.com / nba_api is withheld from **customer display** and
**model inputs**, and **new ingestion is stopped** — pending documented rights or sports/IP counsel
approval. Licensed Odds API market data (lines/prices) and all non-NBA.com content are unaffected.

Stdlib-only, no app import (safe to import anywhere, incl. standalone fetch scripts).
"""
from __future__ import annotations

import os

# The NBA.com-family sources this gate isolates (for logging / documentation).
SOURCES = ('NBA.com', 'stats.nba.com', 'cdn.nba.com', 'official.nba.com', 'nba_api')


def nba_stats_enabled() -> bool:
    """True only when BK_NBA_STATS_ENABLED is explicitly on. Default off = gated."""
    return (os.environ.get('BK_NBA_STATS_ENABLED', '') or '').strip().lower() in ('1', 'true', 'yes', 'on')


# Team-mapping abstention (F3b). A player's NBA team comes ONLY from build_current_team_map (gamelogs +
# player snapshot + roster overrides). The first two are NBA.com-derived and gated empty, and the licensed
# Odds props feed carries the matchup (AWAY@HOME) but NOT the player's side -- so while the gate is off a
# prop row's team is honestly unknown. It is NEVER inferred from the Game string; surfaces abstain visibly.
TEAM_MAPPING_UNAVAILABLE = 'TEAM_MAPPING_UNAVAILABLE'
TEAM_MAPPING_UNAVAILABLE_LABEL = 'Team unavailable (data-rights gated)'


def team_mapping_gated(team_map) -> bool:
    """True when a missing team is an expected data-rights abstention rather than a mapping defect:
    the stats gate is OFF *and* the resolved team map is EMPTY. A non-empty map under the gate (e.g.
    roster overrides present) means misses are real and must still be reported."""
    return (not nba_stats_enabled()) and not team_map


def block_ingestion_if_disabled(label: str) -> bool:
    """For NBA.com-touching fetchers: returns True (and logs) when ingestion must be skipped.

        from services.nba_source_gate import block_ingestion_if_disabled
        if block_ingestion_if_disabled('NBA schedule'):
            return 0
    """
    if nba_stats_enabled():
        return False
    print(f'[gated] NBA.com-derived ingestion disabled (BK_NBA_STATS_ENABLED off) — skipping {label}.')
    return True
