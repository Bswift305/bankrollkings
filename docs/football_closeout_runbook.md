# Football Closeout Runbook

Use this when you want a quick truth check on football without guessing.

## 1. Run the sport QC

```powershell
cd "C:\Users\Decatur\OneDrive\Documents\Kings of Bankrolls"
py qc_nfl_board.py
py qc_cfb_board.py
py qc_football_board.py
```

Or use:

```powershell
batch\QC_FOOTBALL.bat
```

## 2. Read the result the right way

- `No blocking NFL QC issues detected.` means NFL is healthy enough to use.
- `No blocking CFB QC issues detected.` means CFB is healthy enough to use.
- football can still be healthy even when `live game rows = 0` if the current season is out of window and the board is intentionally running from workbook, roster, portal, or historical layers.

## 3. NFL closeout standard

NFL is considered clean when:

- the workbook loads
- historical prop archive is non-zero
- historical game-line archive is non-zero
- main routes load:
  - `/sports/nfl`
  - `/sports/nfl/game-lines`
  - `/sports/nfl/totals`
  - `/sports/nfl/trends`
  - `/sports/nfl/props`
- at least one NFL matchup board route opens from the workbook
- the page tells the truth if live feeds are empty

## 4. CFB closeout standard

CFB is considered clean when:

- the current-season roster context is `ready`
- ESPN roster coverage is non-zero
- team signals are non-empty
- main routes load:
  - `/sports/ncaaf`
  - `/sports/ncaaf/game-lines`
  - `/sports/ncaaf/totals`
  - `/sports/ncaaf/trends`
  - `/sports/ncaaf/props`
- the page tells the truth if historical game-line datasets are still empty

## 5. Final visual sweep

After QC passes, spot-check:

- `/sports/nfl`
- `/sports/nfl/game-lines`
- `/sports/nfl/props`
- `/sports/ncaaf`
- `/sports/ncaaf/game-lines`

Look for:

- broken matchup links
- missing logos
- overlapping tables
- empty widgets that do not explain themselves
- fake “waiting” language when the board is actually operating from workbook/history layers
