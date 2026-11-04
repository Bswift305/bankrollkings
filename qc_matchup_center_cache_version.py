"""QC: the NFL Matchup Center disk cache is version-isolated from pre-fix entries (D4 residual R1).

Residual R1 (cache audit at e1e33dc): `data/cache/nfl_matchup_center.pkl` is keyed on source files + player
logs + ET date + weather, with the same APP_CACHE_VERSION before and after the fix -- so the post-deploy
prewarm would LOAD the pre-fix entry, whose `market.book` can carry the old `build_football_live_games`
fallback `or 'DraftKings'` (a bookmaker the feed never recorded) for up to 24h.

Contract under test (temp DATA_DIR, synthetic feeds, nothing outside the temp dir read for cache or written):
  1. a pre-fix-format entry planted under the OLD key ('nfl_matchup_center' -> nfl_matchup_center.pkl), with
     the exact pre-fix source signature + current APP_CACHE_VERSION and a false 'DraftKings' attribution, is
     IGNORED: the builder runs, the new entry is written under NFL_MATCHUP_CENTER_DISK_KEY
     (nfl_matchup_center_src2.pkl) and the old file is left byte-identical (no delete, no purge)
  2. honest source wording: a row whose feed recorded no book reads 'Unrecorded source'; a recorded book
     passes through; 'DraftKings' appears nowhere -- in the context and in the rendered
     /tools/nfl-matchup-center page
  3. the prewarm path (refresh_runtime_snapshots.prewarm_nfl_tool_caches) writes the SAME new key, and a
     fresh worker then serves it from disk without rebuilding
  4. APP_CACHE_VERSION is untouched by this change (narrow scope; no global purge)
  M  mutation: reverting the key + signature to the pre-fix form serves the planted DraftKings entry ->
     the checks FAIL
Exit 0 = all pass, 1 = any failure.
"""
from __future__ import annotations

from services.qc_no_network import install as _block_network

_block_network()  # before importing app: nothing below may reach the network

import hashlib  # noqa: E402
import inspect  # noqa: E402
import os  # noqa: E402
import pickle  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402
from pathlib import Path  # noqa: E402

import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault('SECRET_KEY', 'qc-matchup-center-cache-version')

import app  # noqa: E402
from services.qc_auth import isolated_owner_client  # noqa: E402

OLD_KEY = 'nfl_matchup_center'
PLANTED_BOOK = 'DraftKings'
results: list[tuple[bool, str]] = []


def ok(cond, msg):
    results.append((bool(cond), msg))
    return bool(cond)


def sha(p: Path):
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None


class Fixture:
    """Temp DATA_DIR + synthetic NFL odds (one row with NO recorded book, one with a recorded book); every
    unrelated slate-wide feed stubbed so only the market/source path is exercised."""

    def __init__(self, td):
        self.td = Path(td)
        self.live_calls = 0

    def __enter__(self):
        (self.td / 'odds').mkdir(parents=True)
        (self.td / 'injuries').mkdir(parents=True)
        today = app.sports_today_date().isoformat()
        upd = (datetime.now(timezone.utc) - timedelta(minutes=30)).strftime('%Y-%m-%dT%H:%M:%SZ')
        self.odds = pd.DataFrame([
            {'Date': today, 'Time': '1:00 PM', 'Away': 'New England Patriots', 'Home': 'Miami Dolphins',
             'AwayFull': 'New England Patriots', 'HomeFull': 'Miami Dolphins', 'Spread': -3.0, 'Total': 44.5,
             'Book': '', 'LastUpdated': upd},
            {'Date': today, 'Time': '4:25 PM', 'Away': 'Chicago Bears', 'Home': 'Detroit Lions',
             'AwayFull': 'Chicago Bears', 'HomeFull': 'Detroit Lions', 'Spread': -6.5, 'Total': 48.5,
             'Book': 'SynBook', 'LastUpdated': upd},
        ])
        self.odds.to_csv(self.td / 'odds' / 'NFL_Odds.csv', index=False)
        pd.DataFrame(columns=['Team', 'Player', 'Status']).to_csv(self.td / 'injuries' / 'NFL_Injuries.csv',
                                                                  index=False)
        real_live = app.build_football_live_games
        fx = self

        def live_spy(*a, **k):
            fx.live_calls += 1
            return real_live(*a, **k)
        stubs = {
            'DATA_DIR': self.td,
            'load_nfl_game_market_odds': lambda *a, **k: self.odds.copy(),
            'load_nfl_schedule': lambda *a, **k: pd.DataFrame(),
            'get_lines_refresh_meta': lambda *a, **k: {'is_stale': False},
            'build_football_live_games': live_spy,
            '_nfl_injury_source_state': lambda *a, **k: {'fresh': False, 'available': False, 'reason': 'qc'},
            'build_nfl_injury_changes': lambda *a, **k: {'changes': []},
            'build_nfl_wave_watch_context': lambda *a, **k: {},
            'build_nfl_milestone_streaks': lambda *a, **k: {},
            '_nfl_game_wind_map': lambda *a, **k: {},
            '_nfl_weather_path': lambda: self.td / 'none.csv',
            '_nfl_ou_tendencies': lambda *a, **k: {'teams': [], 'season': None},
            '_load_line_movement_current': lambda *a, **k: None,
            '_nfl_player_log_signature': lambda: ('qc-player-logs',),
            '_nfl_weather_signature': lambda: ('qc-weather',),
            'record_active_user': lambda *a, **k: None,
            # prewarm siblings (refresh_runtime_snapshots.prewarm_nfl_tool_caches) -- not under test
            'build_nfl_floor_board': lambda *a, **k: {},
            'build_nfl_hot_hand': lambda *a, **k: {},
            'build_nfl_wave_context': lambda *a, **k: {},
        }
        self.saved = {n: getattr(app, n) for n in stubs}
        for n, v in stubs.items():
            setattr(app, n, v)
        app._NFL_MATCHUP_CENTER_CACHE.clear()
        return self

    def __exit__(self, *exc):
        for n, v in self.saved.items():
            setattr(app, n, v)
        app._NFL_MATCHUP_CENTER_CACHE.clear()

    def old_sig(self):
        """The EXACT signature the pre-fix builder computed (e1e33dc)."""
        return (app._build_file_token(self.td / 'odds' / 'NFL_Odds.csv', self.td / 'injuries' / 'NFL_Injuries.csv'),
                app._nfl_player_log_signature(), str(app.sports_today_date()), app._nfl_weather_signature())

    def plant_old_entry(self):
        """Build a structurally complete Matchup Center value whose market.book is the old invented
        'DraftKings' fallback, and write it under the OLD key with the pre-fix signature -- exactly what a
        pre-fix worker / prewarm left on disk."""
        real_store, real_live = app._nfl_disk_cache_store, app.build_football_live_games
        app._nfl_disk_cache_store = lambda *a, **k: None

        def old_live(*a, **k):
            rows = real_live(*a, **k)
            for r in rows:
                r['book'] = PLANTED_BOOK          # a false attribution, as the pre-fix `or 'DraftKings'` wrote
            return rows
        app.build_football_live_games = old_live
        try:
            app._NFL_MATCHUP_CENTER_CACHE.clear()
            value = app.build_nfl_matchup_center_context()
        finally:
            app._nfl_disk_cache_store, app.build_football_live_games = real_store, real_live
            app._NFL_MATCHUP_CENTER_CACHE.clear()
        payload = {'expires_at': datetime.now().timestamp() + 86400, 'version': self.old_sig(),
                   'app_version': app.APP_CACHE_VERSION, 'value': value}
        path = app._disk_ttl_cache_path(OLD_KEY)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('wb') as fh:
            pickle.dump(payload, fh, protocol=pickle.HIGHEST_PROTOCOL)
        return path, value


def books(ctx):
    return [((g.get('market') or {}).get('book')) for g in (ctx or {}).get('games', [])]


def run_checks(rec, fx, old_path, old_hash, label=''):
    new_path = app._disk_ttl_cache_path(app.NFL_MATCHUP_CENTER_DISK_KEY)
    if new_path.exists():
        new_path.unlink()
    app._NFL_MATCHUP_CENTER_CACHE.clear()
    fx.live_calls = 0
    ctx = app.build_nfl_matchup_center_context()
    bk = books(ctx)
    rec(fx.live_calls >= 1, f'{label}1: the planted old-key entry is ignored -- the builder RAN ({fx.live_calls} live-games call)')
    rec(PLANTED_BOOK not in bk and sorted(b for b in bk if b) == ['SynBook', app.UNRECORDED_SOURCE],
        f'{label}2: honest source wording -- unrecorded book reads {app.UNRECORDED_SOURCE!r}, a recorded book passes '
        f'through, no planted {PLANTED_BOOK!r} ({bk})')
    rec(new_path.exists() and new_path != old_path, f'{label}1: the rebuilt entry is written under the NEW key ({new_path.name})')
    doc = app._load_disk_ttl_document(app.NFL_MATCHUP_CENTER_DISK_KEY) or {}
    rec(isinstance(doc.get('version'), tuple) and doc['version'][0] == app.NFL_MATCHUP_CENTER_CACHE_VERSION
        and doc.get('app_version') == app.APP_CACHE_VERSION and PLANTED_BOOK not in books(doc.get('value')),
        f'{label}1: the new entry carries the source-version marker {app.NFL_MATCHUP_CENTER_CACHE_VERSION!r} and honest books')
    rec(old_path.exists() and sha(old_path) == old_hash,
        f'{label}1: the old-key file is left byte-identical (no delete, no purge)')
    with isolated_owner_client('qc-mc-cache-owner') as client:
        r = client.get('/tools/nfl-matchup-center')
        page = r.get_data(as_text=True)
    rec(r.status_code == 200 and PLANTED_BOOK not in page and app.UNRECORDED_SOURCE in page and 'SynBook' in page,
        f'{label}2: rendered /tools/nfl-matchup-center shows {app.UNRECORDED_SOURCE!r} + SynBook, never {PLANTED_BOOK!r} '
        f'(HTTP {r.status_code})')


def check_prewarm(rec, fx, old_path, old_hash):
    import refresh_runtime_snapshots as rrs
    src = inspect.getsource(rrs.prewarm_nfl_tool_caches)
    rec('_appmod.build_nfl_matchup_center_context()' in src and '_nfl_disk_cache' not in src,
        '3: prewarm calls the builder itself (it owns the key; no separate hard-coded cache key)')
    new_path = app._disk_ttl_cache_path(app.NFL_MATCHUP_CENTER_DISK_KEY)
    if new_path.exists():
        new_path.unlink()
    app._NFL_MATCHUP_CENTER_CACHE.clear()
    import contextlib
    import io
    with contextlib.redirect_stdout(io.StringIO()) as out:
        rrs.prewarm_nfl_tool_caches()
    rec(new_path.exists() and '[PREWARM] nfl_matchup_center -> ok' in out.getvalue(),
        f'3: prewarm_nfl_tool_caches writes the NEW key ({new_path.name})')
    rec(sha(old_path) == old_hash, '3: prewarm leaves the old-key file untouched')
    app._NFL_MATCHUP_CENTER_CACHE.clear()            # a fresh worker after the prewarm
    fx.live_calls = 0
    ctx = app.build_nfl_matchup_center_context()
    rec(fx.live_calls == 0 and PLANTED_BOOK not in books(ctx) and app.UNRECORDED_SOURCE in books(ctx),
        '3: a fresh worker serves the prewarmed NEW entry from disk (no rebuild, honest books)')


def check_scope(rec):
    src = (ROOT / 'app.py').read_text(encoding='utf-8')
    rec(app.NFL_MATCHUP_CENTER_DISK_KEY != OLD_KEY
        and app._disk_ttl_cache_path(app.NFL_MATCHUP_CENTER_DISK_KEY).name != f'{OLD_KEY}.pkl',
        f'4: the disk key changed ({OLD_KEY!r} -> {app.NFL_MATCHUP_CENTER_DISK_KEY!r})')
    body = inspect.getsource(app.build_nfl_matchup_center_context)
    rec("_dkey = NFL_MATCHUP_CENTER_DISK_KEY" in body and "'nfl_matchup_center'" not in body,
        '4: the builder reads/writes only the versioned key')
    rec(src.count("APP_CACHE_VERSION = ") == 1 and 'NFL_MATCHUP_CENTER_CACHE_VERSION' not in
        src.split("APP_CACHE_VERSION = ", 1)[1].split('\n', 1)[0],
        '4: the Matchup Center version is its own constant, not folded into APP_CACHE_VERSION (no global purge)')


def mutant_builder():
    """The pre-fix builder: old key, old signature (no version marker)."""
    s = inspect.getsource(app.build_nfl_matchup_center_context)
    s2 = s.replace('sig = (NFL_MATCHUP_CENTER_CACHE_VERSION, ', 'sig = (').replace(
        '_dkey = NFL_MATCHUP_CENTER_DISK_KEY', "_dkey = 'nfl_matchup_center'")
    assert s2 != s and 'NFL_MATCHUP_CENTER_DISK_KEY' not in s2
    ns = dict(app.__dict__)
    exec(compile(s2, 'mutant_matchup_center', 'exec'), ns)  # noqa: S102 -- QC mutation only
    return ns['build_nfl_matchup_center_context']


def main() -> int:
    with tempfile.TemporaryDirectory() as td, Fixture(td) as fx:
        old_path, planted = fx.plant_old_entry()
        old_hash = sha(old_path)
        ok(old_path.name == f'{OLD_KEY}.pkl' and PLANTED_BOOK in books(planted),
           f'0: fixture -- pre-fix entry planted at {old_path.name} carrying {PLANTED_BOOK!r} ({books(planted)})')
        # the plant is genuinely valid for the pre-fix reader (non-vacuous)
        ok(app._nfl_disk_cache_load(OLD_KEY, fx.old_sig()) is not None,
           '0: fixture -- the planted entry IS a valid hit for the pre-fix key + signature')
        for fn, name in ((lambda: run_checks(ok, fx, old_path, old_hash), 'run'),
                         (lambda: check_prewarm(ok, fx, old_path, old_hash), 'prewarm'),
                         (lambda: check_scope(ok), 'scope')):
            try:
                fn()
            except Exception as exc:  # noqa: BLE001
                import traceback
                traceback.print_exc()
                ok(False, f'{name} crashed: {exc!r}')

        # M: revert key + signature to the pre-fix form -> the planted DraftKings entry is served -> FAIL
        real = app.build_nfl_matchup_center_context
        mres = []
        try:
            app.build_nfl_matchup_center_context = mutant_builder()
            run_checks(lambda c, m: mres.append((bool(c), m)), fx, old_path, old_hash, label='M:')
        except Exception as exc:  # noqa: BLE001
            mres.append((False, f'M crashed: {exc!r}'))
        finally:
            app.build_nfl_matchup_center_context = real
            app._NFL_MATCHUP_CENTER_CACHE.clear()
        flipped = [m for c, m in mres if not c]
        must = [m for _c, m in mres if 'builder RAN' in m or 'honest source wording' in m or 'rendered' in m]
        ok(len(must) == 3 and all(m in flipped for m in must),
           f'M: reverting to the pre-fix key/signature serves the planted {PLANTED_BOOK!r} -> '
           f'{sum(1 for m in must if m in flipped)}/{len(must)} source/run/render checks FAIL')

    print('=' * 60)
    print('BANKROLL KINGS MATCHUP CENTER CACHE VERSION QC (D4 / R1)')
    print('=' * 60)
    for passed, msg in results:
        print(f"[{'PASS' if passed else 'FAIL'}] {msg}")
    n_fail = sum(1 for p, _ in results if not p)
    print(f'\n{len(results) - n_fail}/{len(results)} passed')
    return 0 if n_fail == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
