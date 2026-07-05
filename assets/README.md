# Franchise Kings Portrait Assets

Generated portraits live here and are served by the app at `/assets/...`.

- `portraits/players/active`: assigned player thumbnails
- `portraits/players/rookies`: rookie/prospect pool
- `portraits/players/free_agents`: free-agent pool
- `portraits/players/retired`: retired player archive
- `portraits/coaches`, `portraits/owners`, `portraits/gms`, `portraits/scouts`,
  `portraits/agents`, `portraits/media`: non-player portrait pools
- `sheets/raw`: generated sprite sheets awaiting slicing
- `sheets/processed`: sprite sheets after slicing
- `metadata/portraits.csv` and `metadata/portraits.json`: portrait tags
- `scripts/slice_sheets.py`: slices grid sheets into 512x512 PNGs
- `scripts/assign_portraits.py`: assigns portrait IDs to franchise saves

Do not manually crop portraits. Generate single 512x512 images or clean grids
and slice them with the script.
