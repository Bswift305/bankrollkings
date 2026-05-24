from collections import deque
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "Logos" / "NBA"
OUTPUT_DIR = ROOT / "static" / "logos" / "nba_clean"


SOURCE_MAP = {
    "ATL": "gropicture-NBA-vector-logo-Atlanta-Hawks-basketball-club-ATL-979x1024.webp",
    "BOS": "gropicture-NBA-vector-logo-Boston-Celtics-BOS-887x1024.webp",
    "BKN": "gropicture-NBA-vector-logo-Brooklyn-Nets-BKN-896x1024.webp",
    "CHA": "gropicture-NBA-vector-logo-Charlotte-Hornets-CHA-982x1024.webp",
    "CHI": "gropicture-NBA-vector-logo-Chicago-Bulls-CHI-953x1024.webp",
    "CLE": "gropicture-NBA-vector-logo-Cleveland-Cavaliers-CLE-1024x830.webp",
    "DAL": "gropicture-NBA-vector-logo-Dallas-Mavericks-DAL-909x1024.webp",
    "DEN": "gropicture-NBA-vector-logo-Denver-Nuggets-DEN-1024x914.webp",
    "DET": "gropicture-NBA-vector-logo-Detroit-Pistons-DET-1005x1024.webp",
    "GSW": "gropicture-NBA-vector-logo-Golden-State-Warriors-GSW-858x1024.webp",
    "HOU": "gropicture-NBA-vector-logo-Houston-Rockets-HOU-old-1024x945.webp",
    "IND": "gropicture-NBA-vector-logo-Indiana-Pacers-IND-1024x826.png",
    "LAC": "gropicture-NBA-vector-logo-Los-Angeles-Clippers-LAC-1024x981.webp",
    "LAL": "gropicture-NBA-LA-Lakers-vector-logo.webp",
    "MEM": "gropicture-NBA-vector-logo-Memphis-Grizzlies-MEM-982x1024.webp",
    "MIA": "gropicture-NBA-vector-logo-Miami-Heat-MIA-799x1024.webp",
    "MIL": "gropicture-NBA-vector-logo-Milwaukee-Bucks-MIL-834x1024.webp",
    "MIN": "gropicture-NBA-vector-logo-Minnesota-Timberwolves-MIN-1024x973.webp",
    "NOP": "gropicture-NBA-vector-logo-New-Orleans-Pelicans-NOP-1024x985.webp",
    "NYK": "gropicture-NBA-vector-logo-New-York-Knicks-NYK-1024x982.webp",
    "OKC": "gropicture-NBA-vector-logo-Oklahoma-City-Thunder-OKC-896x1024.webp",
    "ORL": "gropicture-NBA-vector-logo-Orlando-Magic-ORL-1024x982.webp",
    "PHI": "gropicture-NBA-vector-logo-Philadelphia-76ers-PHI-951x1024.webp",
    "PHX": "gropicture-NBA-vector-logo-Phoenix-Suns-PHX-952x1024.webp",
    "POR": "gropicture-NBA-vector-logo-Portland-Trail-Blazers-POR-731x1024.webp",
    "SAC": "gropicture-NBA-vector-logo-Sacramento-Kings-SAC-953x1024.webp",
    "SAS": "gropicture-NBA-vector-logo-San-Antonio-Spurs-SAS-1024x830.webp",
    "TOR": "gropicture-NBA-vector-logo-Toronto-Raptors-TOR-979x1024.webp",
    "UTA": "gropicture-NBA-vector-logo-Utah-Jazz-UTA-1024x844.webp",
    "WAS": "gropicture-NBA-vector-logo-Washington-Wizards-WAS-1024x982.webp",
}


def is_bg_pixel(pixel, threshold=245, max_delta=20):
    r, g, b, a = pixel
    if a == 0:
        return True
    if min(r, g, b) < threshold:
        return False
    return max(abs(r - g), abs(r - b), abs(g - b)) <= max_delta


def remove_edge_background(image: Image.Image) -> Image.Image:
    rgba = image.convert("RGBA")
    width, height = rgba.size
    pixels = rgba.load()
    visited = set()
    queue = deque()

    for x in range(width):
        queue.append((x, 0))
        queue.append((x, height - 1))
    for y in range(height):
        queue.append((0, y))
        queue.append((width - 1, y))

    while queue:
        x, y = queue.popleft()
        if (x, y) in visited or x < 0 or y < 0 or x >= width or y >= height:
            continue
        visited.add((x, y))
        if not is_bg_pixel(pixels[x, y]):
            continue

        pixels[x, y] = (255, 255, 255, 0)
        queue.extend(
            [
                (x - 1, y),
                (x + 1, y),
                (x, y - 1),
                (x, y + 1),
            ]
        )

    bbox = rgba.getbbox()
    return rgba.crop(bbox) if bbox else rgba


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for abbr, filename in SOURCE_MAP.items():
        source = SOURCE_DIR / filename
        if not source.exists():
            print(f"missing {abbr}: {source}")
            continue
        cleaned = remove_edge_background(Image.open(source))
        destination = OUTPUT_DIR / f"{abbr}.png"
        cleaned.save(destination)
        print(f"saved {abbr} -> {destination}")


if __name__ == "__main__":
    main()
