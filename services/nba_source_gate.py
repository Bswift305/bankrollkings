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
