from __future__ import annotations

import argparse
import csv
import re
import zipfile
from pathlib import Path
import xml.etree.ElementTree as ET


WORKSPACE = Path(__file__).resolve().parent
DEFAULT_DOC = Path(r"C:\Users\Decatur\OneDrive\Documents\NBA Current Roster.docx")
DEFAULT_OUTPUT = WORKSPACE / "data" / "tracking" / "NBA_CurrentRoster_FromDoc.csv"
NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
TEAM_ABBR = {
    "ATLANTA HAWKS": "ATL", "BOSTON CELTICS": "BOS", "BROOKLYN NETS": "BKN", "CHARLOTTE HORNETS": "CHA",
    "CHICAGO BULLS": "CHI", "CLEVELAND CAVALIERS": "CLE", "DALLAS MAVERICKS": "DAL", "DENVER NUGGETS": "DEN",
    "DETROIT PISTONS": "DET", "GOLDEN STATE WARRIORS": "GSW", "HOUSTON ROCKETS": "HOU", "INDIANA PACERS": "IND",
    "LOS ANGELES CLIPPERS": "LAC", "LOS ANGELES LAKERS": "LAL", "MEMPHIS GRIZZLIES": "MEM", "MIAMI HEAT": "MIA",
    "MILWAUKEE BUCKS": "MIL", "MINNESOTA TIMBERWOLVES": "MIN", "NEW ORLEANS PELICANS": "NOP", "NEW YORK KNICKS": "NYK",
    "OKLAHOMA CITY THUNDER": "OKC", "ORLANDO MAGIC": "ORL", "PHILADELPHIA 76ERS": "PHI", "PHILADELPHIA SIXERS": "PHI", "PHOENIX SUNS": "PHX",
    "PORTLAND TRAIL BLAZERS": "POR", "SACRAMENTO KINGS": "SAC", "SAN ANTONIO SPURS": "SAS", "TORONTO RAPTORS": "TOR",
    "UTAH JAZZ": "UTA", "WASHINGTON WIZARDS": "WAS",
}


def normalize_team_name(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", str(value or "").replace(".", "")).strip().upper()
    return TEAM_ABBR.get(cleaned, cleaned)


def extract_rows(doc_path: Path) -> list[dict[str, str]]:
    with zipfile.ZipFile(doc_path) as zf:
        xml_bytes = zf.read("word/document.xml")
    root = ET.fromstring(xml_bytes)
    tables = root.findall(".//w:tbl", NS)
    if len(tables) < 2:
        raise RuntimeError("Could not find roster table in Word document.")
    rows = []
    for row in tables[1].findall(".//w:tr", NS)[1:]:
        cells = []
        for cell in row.findall("./w:tc", NS):
            text = " ".join(t.text for t in cell.findall(".//w:t", NS) if t.text).strip()
            cells.append(text)
        if len(cells) < 7:
            continue
        rows.append({
            "Number": cells[0],
            "Player": cells[1],
            "Pos": cells[2],
            "HT": cells[3],
            "WT": cells[4],
            "Age": cells[5],
            "CurrentTeam": normalize_team_name(cells[6]),
            "YOS": cells[7] if len(cells) > 7 else "",
            "PreDraftTeam": cells[8] if len(cells) > 8 else "",
            "DraftStatus": cells[9] if len(cells) > 9 else "",
            "Nationality": cells[10] if len(cells) > 10 else "",
        })
    return rows


def load_existing_team_map(csv_path: Path) -> dict[str, str]:
    if not csv_path.exists():
        return {}
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return {
            str(row.get("Player", "")).strip(): normalize_team_name(str(row.get("CurrentTeam", "")).strip())
            for row in reader if row.get("Player")
        }


def write_rows(rows: list[dict[str, str]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["Number", "Player", "Pos", "HT", "WT", "Age", "CurrentTeam", "YOS", "PreDraftTeam", "DraftStatus", "Nationality"]
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def build_diff(old_map: dict[str, str], new_rows: list[dict[str, str]]) -> list[tuple[str, str, str]]:
    changes = []
    for row in new_rows:
        player = row["Player"].strip()
        new_team = row["CurrentTeam"].strip()
        old_team = old_map.get(player, "")
        if old_team and old_team != new_team:
            changes.append((player, old_team, new_team))
    return sorted(changes, key=lambda item: item[0])


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh the current NBA roster CSV from the roster Word document.")
    parser.add_argument("--doc", default=str(DEFAULT_DOC), help="Path to NBA Current Roster.docx")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Path to output CSV")
    args = parser.parse_args()

    doc_path = Path(args.doc)
    output_path = Path(args.output)
    if not doc_path.exists():
        raise SystemExit(f"Roster document not found: {doc_path}")

    old_map = load_existing_team_map(output_path)
    rows = extract_rows(doc_path)
    write_rows(rows, output_path)
    changes = build_diff(old_map, rows)

    print(f"Refreshed roster file: {output_path}")
    print(f"Rows written: {len(rows)}")
    if changes:
        print("Team changes detected:")
        for player, old_team, new_team in changes[:50]:
            print(f" - {player}: {old_team} -> {new_team}")
        if len(changes) > 50:
            print(f" ... and {len(changes) - 50} more")
    else:
        print("No team changes detected against the previous CSV.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
