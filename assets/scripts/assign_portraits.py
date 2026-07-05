from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import portrait_assets as pa


def parse_args():
    p = argparse.ArgumentParser(description="Assign portrait IDs to a Franchise Kings save JSON.")
    p.add_argument("save", help="Path to save JSON.")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def players_in_save(save):
    for team in save.get("teams", []):
        for player in team.get("roster", []):
            yield player
        for player in team.get("practice_squad", []):
            yield player
    for player in save.get("free_agents", []):
        yield player
    for player in (save.get("draft") or {}).get("class", []):
        yield player


def main():
    args = parse_args()
    path = Path(args.save)
    save = json.loads(path.read_text(encoding="utf-8"))
    records = pa.load_records()
    used = {p.get("portrait_id") for p in players_in_save(save) if p.get("portrait_id")}
    changed = 0
    for player in players_in_save(save):
        if not player.get("portrait_id"):
            pid = pa.assign_player(player, used_ids=used, records=records)
            if pid:
                used.add(pid)
                changed += 1
    if args.dry_run:
        print(f"Would assign {changed} portraits.")
    else:
        path.write_text(json.dumps(save, indent=2), encoding="utf-8")
        print(f"Assigned {changed} portraits in {path}")


if __name__ == "__main__":
    main()
