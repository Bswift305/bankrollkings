# Bankroll Kings — Social Content Generators

The scripts that produce the entire social library (stills + TikTok videos).
Preserved here so the content is reproducible. Outputs live in:

- **Stills (60):** `marketing/content_pack/` (1080×1350 PNG)
- **Videos (57):** `marketing/content_pack_video/` (1080×1920 MP4, ~7.6s, loop-ready)
- **Browsable index:** the "Bankroll Kings — Content Pack" artifact on claude.ai

## How it works

**Stills:** each generator writes a self-contained HTML card, then headless Chrome
screenshots it at 2× → PNG.

```
HTML (brand CSS) ──> Chrome --headless --screenshot (2x, 1080x1350) ──> PNG
```

**Videos:** `video_engine.py` animates the same cards. It renders ~62 build frames
(each frame = the HTML at a given progress `?p=`), then ffmpeg freezes the final
frame for 5s so the finished card is readable before it loops.

```
HTML + apply(p) ──> Chrome frames (1080x1920) ──> ffmpeg tpad (5s hold) ──> MP4
```

## The scripts

| Script | Produces |
|---|---|
| `video_engine.py` | **The main engine.** All 57 videos: intro, Start Here, proof, features, difference, myth, 22 proverbs. Declarative animation (fade / pop / slide / bar / count-up). |
| `gen_features.py` | 13 "Inside the App" feature stills |
| `gen_myths.py` | 6 "Myth or Money" stills |
| `gen_difference.py` | 5 "The Difference" stills (versus + $19.99 value) |
| `gen_howto.py` | 4 "Start Here" onboarding stills |
| `gen_proverbs.py` | 22 King's Proverbs stills |
| `build_pack.py` | Builds the Content Pack index page (`content_pack.html`) + copies stills into `content_pack/` |
| `render_video.py` | Original single-video prototype (superseded by `video_engine.py`) |

## Requirements

- Python 3 + Pillow (`pip install pillow`)
- Google Chrome (path hardcoded: `C:/Program Files/Google/Chrome/Application/chrome.exe`)
- ffmpeg on PATH (videos only)
- Mascot asset: `static/king-bankroll.webp` (used by intro + content pack cover)

## Run

```bash
# one video (or a subset)
python video_engine.py all vid_intro_01 vid_prov_01
# every video
python video_engine.py all
# preview final-frame stills without full render (fast)
python video_engine.py validate vid_intro_01
```

## Brand tokens (kept consistent everywhere)

- Ground `#070e14` · cyan `#2dd4bf` · gold `#ffce6a` · green `#4ed48a` · red `#ff6f7e`
- Display: heavy italic uppercase Helvetica Neue/Arial · mono: ui-monospace/Consolas
- Accent by pillar: betting = cyan, honesty/fantasy = gold, free game = green

## ⚠ Path note

These were authored in a temp scratchpad; several paths (input/output dirs, the
`SRC` roots) point at that scratchpad. Update the paths at the top of each script
before re-running from this location. The logic and content are all intact.

## Honesty rule (the brand's moat)

Every number in this library traces to real graded data or a real app feature.
Nothing is fabricated. Keep it that way — it's the whole differentiator.
