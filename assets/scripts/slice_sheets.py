from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import portrait_assets as pa


def parse_args():
    p = argparse.ArgumentParser(description="Slice a clean portrait sheet into individual PNG portraits.")
    p.add_argument("--input", required=True, help="Input sprite sheet PNG.")
    p.add_argument("--cols", type=int, required=True, help="Number of columns in the sheet.")
    p.add_argument("--rows", type=int, required=True, help="Number of rows in the sheet.")
    p.add_argument("--start", type=int, required=True, help="Starting numeric portrait ID.")
    p.add_argument("--output", default="assets/portraits/players/active", help="Output folder.")
    p.add_argument("--size", type=int, default=512, help="Final portrait size in pixels.")
    p.add_argument("--category", default="player")
    p.add_argument("--age-range", default="any")
    p.add_argument("--skin-tone", default="")
    p.add_argument("--ethnicity-group", default="")
    p.add_argument("--hair-style", default="")
    p.add_argument("--facial-hair", default="")
    p.add_argument("--accessories", default="none")
    p.add_argument("--expression", default="serious")
    p.add_argument("--body-type", default="any")
    p.add_argument("--position-bias", default="", help="Pipe-delimited positions, e.g. WR|CB|RB.")
    p.add_argument("--no-metadata", action="store_true", help="Slice images without updating metadata files.")
    return p.parse_args()


def main():
    args = parse_args()
    try:
        from PIL import Image
    except ImportError as exc:
        raise SystemExit("Pillow is required: python -m pip install pillow") from exc

    src = Path(args.input)
    out_dir = Path(args.output)
    if not out_dir.is_absolute():
        out_dir = ROOT / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    with Image.open(src) as img:
        cell_w = img.width // args.cols
        cell_h = img.height // args.rows
        if cell_w <= 0 or cell_h <= 0:
            raise SystemExit("Invalid sheet geometry.")
        records = []
        n = args.start
        for row in range(args.rows):
            for col in range(args.cols):
                portrait_id = f"player_portrait_{n:06d}"
                crop = img.crop((col * cell_w, row * cell_h, (col + 1) * cell_w, (row + 1) * cell_h))
                if crop.size != (args.size, args.size):
                    crop = crop.resize((args.size, args.size), Image.Resampling.LANCZOS)
                out_path = out_dir / f"{portrait_id}.png"
                crop.save(out_path, "PNG")
                try:
                    rel = "/" + out_path.relative_to(ROOT).as_posix()
                except ValueError:
                    rel = out_path.as_posix()
                records.append({
                    "portrait_id": portrait_id,
                    "file_path": rel,
                    "category": args.category,
                    "age_range": args.age_range,
                    "skin_tone": args.skin_tone,
                    "ethnicity_group": args.ethnicity_group,
                    "hair_style": args.hair_style,
                    "facial_hair": args.facial_hair,
                    "accessories": args.accessories,
                    "expression": args.expression,
                    "body_type": args.body_type,
                    "position_bias": args.position_bias,
                    "used": "false",
                })
                n += 1

    if not args.no_metadata:
        pa.append_records(records)
    print(f"Sliced {len(records)} portraits into {out_dir}")


if __name__ == "__main__":
    main()
