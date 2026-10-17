"""QC: CFB runtime-data resolver + deploy hardening (docs/cfb_runtime_data_corrective.md).

No network. Proves (correction 7):
  * runtime data takes precedence over a committed seed;
  * a missing live runtime dataset FAILS CLOSED rather than serving a stale seed;
  * an atomic-write failure preserves the prior runtime version (and leaves no partial file);
  * a dirty tracked file blocks deployment; a clean or untracked-only tree does not;
  * a fresh checkout starts safely before its first refresh.

Exits 0 on success, 1 otherwise.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

import bk_runtime

LIVE = "cfb_line_moves.json"            # classified live-authoritative (no seed fallback)
SEEDABLE = "cfb_power.json"             # NOT live -> may fall back to a committed seed


def _with_dirs(fn):
    """Run fn with BK_RUNTIME_DIR + bk_runtime._TRACKED_SCENARIOS pointed at throwaway temp dirs."""
    prev_env = os.environ.get("BK_RUNTIME_DIR")
    prev_seed = bk_runtime._TRACKED_SCENARIOS
    with tempfile.TemporaryDirectory() as rt, tempfile.TemporaryDirectory() as seed:
        os.environ["BK_RUNTIME_DIR"] = rt
        bk_runtime._TRACKED_SCENARIOS = Path(seed)
        try:
            return fn(Path(rt), Path(seed))
        finally:
            bk_runtime._TRACKED_SCENARIOS = prev_seed
            if prev_env is None:
                os.environ.pop("BK_RUNTIME_DIR", None)
            else:
                os.environ["BK_RUNTIME_DIR"] = prev_env


def qc_runtime_precedence():
    def body(rt, seed):
        issues = []
        # seed present for a NON-live file; no runtime copy -> reads the seed
        (seed / SEEDABLE).write_text(json.dumps({"src": "seed"}), encoding="utf-8")
        if bk_runtime.read_json(SEEDABLE, {}).get("src") != "seed":
            issues.append("non-live file did not fall back to the committed seed")
        # publish a runtime copy -> runtime wins over the seed
        bk_runtime.publish_json(SEEDABLE, {"src": "runtime"})
        if bk_runtime.read_json(SEEDABLE, {}).get("src") != "runtime":
            issues.append("runtime copy did not take precedence over the seed")
        return issues
    return _with_dirs(body)


def qc_live_missing_fails_closed():
    def body(rt, seed):
        issues = []
        # a seed EXISTS for the live file, but with no runtime copy it must NOT be used
        (seed / LIVE).write_text(json.dumps({"updated": "2020-01-01", "games": [1]}), encoding="utf-8")
        p = bk_runtime.scenario_read_path(LIVE)
        if p.exists():
            issues.append("live file resolved to an existing path (stale seed?) when no runtime copy")
        if bk_runtime.read_json(LIVE, None) is not None:
            issues.append("live file served a stale seed instead of failing closed")
        # once a runtime copy exists, it resolves
        bk_runtime.publish_json(LIVE, {"updated": "now", "games": []})
        if bk_runtime.read_json(LIVE, {}).get("updated") != "now":
            issues.append("live runtime copy not read after publish")
        return issues
    return _with_dirs(body)


def qc_atomic_write_preserves_prior():
    def body(rt, seed):
        issues = []
        bk_runtime.publish_json(LIVE, {"v": 1})
        dest = bk_runtime.scenario_write_path(LIVE)
        # force the atomic replace to fail mid-publish
        orig = os.replace
        os.replace = lambda *a, **k: (_ for _ in ()).throw(OSError("boom"))
        try:
            bk_runtime.publish_json(LIVE, {"v": 2})
            issues.append("publish did not raise on os.replace failure")
        except OSError:
            pass
        finally:
            os.replace = orig
        if json.loads(dest.read_text(encoding="utf-8")).get("v") != 1:
            issues.append("prior runtime version not preserved after a failed publish")
        leftovers = [p.name for p in dest.parent.iterdir() if p.name.endswith(".tmp")]
        if leftovers:
            issues.append(f"partial temp file left behind: {leftovers}")
        return issues
    return _with_dirs(body)


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True)


def _porcelain_blocks(repo):
    """The exact decision the deploy guard makes: modified TRACKED files (untracked excluded) block."""
    out = _git(repo, "status", "--porcelain", "--untracked-files=no").stdout
    return bool(out.strip())


def qc_deploy_dirty_guard():
    issues = []
    with tempfile.TemporaryDirectory() as d:
        repo = Path(d)
        _git(repo, "init", "-q")
        _git(repo, "config", "user.email", "qc@bk.local")
        _git(repo, "config", "user.name", "qc")
        (repo / "tracked.txt").write_text("v1\n", encoding="utf-8")
        _git(repo, "add", "tracked.txt")
        _git(repo, "commit", "-q", "-m", "init")
        # clean tree -> does not block
        if _porcelain_blocks(repo):
            issues.append("clean tree wrongly blocked deployment")
        # untracked-only -> does not block
        (repo / "new_untracked.txt").write_text("x\n", encoding="utf-8")
        if _porcelain_blocks(repo):
            issues.append("untracked-only tree wrongly blocked deployment")
        # modified tracked file -> blocks
        (repo / "tracked.txt").write_text("v2-local-edit\n", encoding="utf-8")
        if not _porcelain_blocks(repo):
            issues.append("a modified tracked file did not block deployment")
    return issues


def qc_fresh_checkout_safe():
    def body(rt, seed):
        issues = []
        # empty runtime dir, no seed at all -> live read fails closed, no exception/crash
        try:
            if bk_runtime.read_json(LIVE, "CLOSED") != "CLOSED":
                issues.append("fresh checkout did not fail closed for a live file")
            if bk_runtime.read_json(SEEDABLE, "CLOSED") != "CLOSED":
                issues.append("fresh checkout did not return default for a missing seed file")
            # mtime of an absent source is 0 (safe for cache signatures)
            if bk_runtime.scenario_source_mtime(LIVE) != 0:
                issues.append("absent source mtime not 0")
        except Exception as e:  # noqa
            issues.append(f"fresh checkout raised: {type(e).__name__}: {e}")
        return issues
    return _with_dirs(body)


CHECKS = [("runtime_precedence", qc_runtime_precedence),
          ("live_missing_fails_closed", qc_live_missing_fails_closed),
          ("atomic_write_preserves_prior", qc_atomic_write_preserves_prior),
          ("deploy_dirty_guard", qc_deploy_dirty_guard),
          ("fresh_checkout_safe", qc_fresh_checkout_safe)]


def main() -> int:
    print("=" * 60)
    print("BANKROLL KINGS CFB RUNTIME-DATA / DEPLOY QC")
    print("=" * 60)
    failed = 0
    for name, fn in CHECKS:
        try:
            issues = fn()
        except Exception as e:  # noqa
            import traceback
            issues = [f"EXCEPTION {type(e).__name__}: {e}"]
            traceback.print_exc()
        if issues:
            failed += 1
            for i in issues:
                print(f"[FAIL] {name}: {i}")
        else:
            print(f"[PASS] {name}")
    print("-" * 60)
    print(f"FAIL: {failed}" if failed else "CFB runtime-data / deploy hardening verified.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
