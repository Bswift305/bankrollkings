#!/usr/bin/env python3
"""
🏀 NBA FLOOR PLAY PARLAY BUILDER
================================
Reads: Floor_Props_Dec31.xlsx (YOUR local data)
Outputs: Tiered parlays with 4th leg highlighted

NO API CALLS - Uses your local files only

Place in: C:/Users/Decatur/NBA Floor Play
Run: python floor_parlay_builder.py
"""

import pandas as pd
from datetime import datetime
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
import os

# ============================================================
# CONFIGURATION
# ============================================================
DATE_STR = datetime.now().strftime("%Y-%m-%d")
DATE_DISPLAY = datetime.now().strftime("%B %d, %Y")

# File paths - UPDATE THESE IF NEEDED
INPUT_FILE = "Floor_Props_Dec31.xlsx"  # Your props file
OUTPUT_FILE = f"Parlays_{datetime.now().strftime('%b%d')}.xlsx"

# Parlay settings
TOTAL_PARLAYS = 25
LEGS_PER_PARLAY = 20
ROTATION_START = 4  # 4th leg is the rotation position

# Floor Play Requirements
# IMPORTANT: Props must be -200 to -400 odds (66%-80% implied probability)
# This should be filtered in your Floor_Props file BEFORE running this script
# The "80%+ Plays" sheet should only contain props in this odds range

# Styling
HEADER_FILL = PatternFill('solid', fgColor='1F4E79')
HEADER_FONT = Font(bold=True, color='FFFFFF')
LOCK_FILL = PatternFill('solid', fgColor='2ECC71')      # Green - LOCK
STRONG_FILL = PatternFill('solid', fgColor='F1C40F')    # Yellow - STRONG
ROTATION_FILL = PatternFill('solid', fgColor='FF6B6B')  # Red - 4th leg to save
THIN_BORDER = Border(
    left=Side(style='thin'), right=Side(style='thin'),
    top=Side(style='thin'), bottom=Side(style='thin')
)

print("=" * 60)
print(f"🏀 NBA FLOOR PLAY PARLAY BUILDER")
print(f"📅 {DATE_DISPLAY}")
print("=" * 60)

# ============================================================
# LOAD YOUR DATA
# ============================================================
print(f"\n📂 Loading: {INPUT_FILE}")

if not os.path.exists(INPUT_FILE):
    print(f"❌ File not found: {INPUT_FILE}")
    print(f"   Make sure you're running from: C:\\Users\\Decatur\\NBA Floor Play")
    exit(1)

# Read the 80%+ plays (already filtered)
df_plays = pd.read_excel(INPUT_FILE, sheet_name='80%+ Plays')
print(f"   ✅ Loaded {len(df_plays)} qualifying props")

# Read all props for reference
df_all = pd.read_excel(INPUT_FILE, sheet_name='All Props')
print(f"   ✅ Loaded {len(df_all)} total props")

# ============================================================
# CATEGORIZE PROPS
# ============================================================
print("\n📊 Categorizing props...")

# Tier 1: LOCKS (100% L5 hit rate)
locks = df_plays[df_plays['Hit% L5'] == '100.0%'].copy()
print(f"   🔒 LOCKS (100% L5): {len(locks)}")

# Tier 2: STRONG (80%+ L5)
strong = df_plays[
    (df_plays['Hit% L5'] != '100.0%') & 
    (df_plays['Verdict'].str.contains('STRONG|LOCK', na=False))
].copy()
print(f"   ✅ STRONG: {len(strong)}")

# Tier 3: Everything else that qualified
others = df_plays[
    ~df_plays.index.isin(locks.index) & 
    ~df_plays.index.isin(strong.index)
].copy()
print(f"   📋 OTHER: {len(others)}")

# ============================================================
# BUILD PARLAYS
# ============================================================
print(f"\n🎲 Building {TOTAL_PARLAYS} parlays...")

# Combine all qualifying props
all_qualifying = pd.concat([locks, strong, others]).reset_index(drop=True)

# Ensure we have enough props
if len(all_qualifying) < LEGS_PER_PARLAY:
    print(f"⚠️ Only {len(all_qualifying)} qualifying props, need {LEGS_PER_PARLAY}")
    print("   Reducing legs per parlay...")
    LEGS_PER_PARLAY = min(len(all_qualifying), 20)

# Build parlay structure
parlays = []

for parlay_num in range(1, TOTAL_PARLAYS + 1):
    parlay_legs = []
    
    # Legs 1-3: Always LOCKS (core foundation)
    core_locks = locks.head(3)
    for i, (_, row) in enumerate(core_locks.iterrows(), 1):
        parlay_legs.append({
            'leg': i,
            'player': row['Player'],
            'team': row['Team'],
            'stat': row['Stat'],
            'line': row['Line'],
            'hit_l5': row['Hit% L5'],
            'hit_l10': row['Hit% L10'],
            'verdict': row['Verdict'],
            'is_rotation': False
        })
    
    used_players = {leg['player'] for leg in parlay_legs}

    # Leg 4: ROTATION LEG (different for each parlay)
    rotation_candidates = all_qualifying[~all_qualifying['Player'].isin(used_players)]
    if rotation_candidates.empty:
        rotation_candidates = all_qualifying

    rotation_idx = (parlay_num - 1) % len(rotation_candidates)
    rotation_row = rotation_candidates.iloc[rotation_idx]
    parlay_legs.append({
        'leg': 4,
        'player': rotation_row['Player'],
        'team': rotation_row['Team'],
        'stat': rotation_row['Stat'],
        'line': rotation_row['Line'],
        'hit_l5': rotation_row['Hit% L5'],
        'hit_l10': rotation_row['Hit% L10'],
        'verdict': rotation_row['Verdict'],
        'is_rotation': True  # HIGHLIGHTED
    })
    
    # Legs 5+: Fill with remaining props
    remaining_needed = LEGS_PER_PARLAY - 4
    used_players.add(rotation_row['Player'])
    
    fill_idx = 0
    leg_num = 5
    while len(parlay_legs) < LEGS_PER_PARLAY and fill_idx < len(all_qualifying):
        row = all_qualifying.iloc[fill_idx]
        
        # Avoid duplicate players in same parlay (diversification)
        if row['Player'] not in used_players:
            parlay_legs.append({
                'leg': leg_num,
                'player': row['Player'],
                'team': row['Team'],
                'stat': row['Stat'],
                'line': row['Line'],
                'hit_l5': row['Hit% L5'],
                'hit_l10': row['Hit% L10'],
                'verdict': row['Verdict'],
                'is_rotation': False
            })
            used_players.add(row['Player'])
            leg_num += 1
        
        fill_idx += 1
    
    parlays.append({
        'parlay_num': parlay_num,
        'legs': parlay_legs
    })

print(f"   ✅ Built {len(parlays)} parlays")

# ============================================================
# CREATE OUTPUT EXCEL
# ============================================================
print(f"\n📝 Creating output: {OUTPUT_FILE}")

wb = Workbook()

# === SHEET 1: Parlay Summary ===
ws_summary = wb.active
ws_summary.title = "Parlay_Summary"

# Header
ws_summary['A1'] = f"NBA FLOOR PLAY PARLAYS - {DATE_DISPLAY}"
ws_summary['A1'].font = Font(bold=True, size=14)
ws_summary.merge_cells('A1:H1')

ws_summary['A2'] = "🔴 RED = 4th Leg (Rotation Position - SAVE THIS LEG when rebuilding)"
ws_summary['A2'].font = Font(italic=True, color='FF0000')
ws_summary.merge_cells('A2:H2')

# Column headers
headers = ['Parlay #', 'Leg', 'Player', 'Team', 'Stat', 'Line', 'Hit% L5', 'Verdict']
for col, header in enumerate(headers, 1):
    cell = ws_summary.cell(row=4, column=col, value=header)
    cell.font = HEADER_FONT
    cell.fill = HEADER_FILL
    cell.border = THIN_BORDER
    cell.alignment = Alignment(horizontal='center')

# Data rows
row_num = 5
for parlay in parlays:
    for leg in parlay['legs']:
        ws_summary.cell(row=row_num, column=1, value=parlay['parlay_num']).border = THIN_BORDER
        ws_summary.cell(row=row_num, column=2, value=leg['leg']).border = THIN_BORDER
        ws_summary.cell(row=row_num, column=3, value=leg['player']).border = THIN_BORDER
        ws_summary.cell(row=row_num, column=4, value=leg['team']).border = THIN_BORDER
        ws_summary.cell(row=row_num, column=5, value=leg['stat']).border = THIN_BORDER
        ws_summary.cell(row=row_num, column=6, value=leg['line']).border = THIN_BORDER
        ws_summary.cell(row=row_num, column=7, value=leg['hit_l5']).border = THIN_BORDER
        ws_summary.cell(row=row_num, column=8, value=leg['verdict']).border = THIN_BORDER
        
        # Highlight rotation leg (4th)
        if leg['is_rotation']:
            for col in range(1, 9):
                ws_summary.cell(row=row_num, column=col).fill = ROTATION_FILL
        elif '🔥' in str(leg['verdict']):
            for col in range(1, 9):
                ws_summary.cell(row=row_num, column=col).fill = LOCK_FILL
        
        row_num += 1

# Adjust column widths
col_widths = [10, 6, 25, 6, 6, 8, 10, 12]
for i, width in enumerate(col_widths, 1):
    ws_summary.column_dimensions[get_column_letter(i)].width = width

# === SHEET 2: Quick Reference (4th Legs Only) ===
ws_rotation = wb.create_sheet("4th_Legs_To_Save")

ws_rotation['A1'] = "4TH LEG QUICK REFERENCE - SAVE THESE WHEN REBUILDING"
ws_rotation['A1'].font = Font(bold=True, size=12)
ws_rotation.merge_cells('A1:F1')

headers2 = ['Parlay #', 'Player', 'Team', 'Stat', 'Line', 'Hit% L5']
for col, header in enumerate(headers2, 1):
    cell = ws_rotation.cell(row=3, column=col, value=header)
    cell.font = HEADER_FONT
    cell.fill = HEADER_FILL
    cell.border = THIN_BORDER

row_num = 4
for parlay in parlays:
    rotation_leg = [l for l in parlay['legs'] if l['is_rotation']][0]
    ws_rotation.cell(row=row_num, column=1, value=parlay['parlay_num']).border = THIN_BORDER
    ws_rotation.cell(row=row_num, column=2, value=rotation_leg['player']).border = THIN_BORDER
    ws_rotation.cell(row=row_num, column=3, value=rotation_leg['team']).border = THIN_BORDER
    ws_rotation.cell(row=row_num, column=4, value=rotation_leg['stat']).border = THIN_BORDER
    ws_rotation.cell(row=row_num, column=5, value=rotation_leg['line']).border = THIN_BORDER
    ws_rotation.cell(row=row_num, column=6, value=rotation_leg['hit_l5']).border = THIN_BORDER
    
    for col in range(1, 7):
        ws_rotation.cell(row=row_num, column=col).fill = ROTATION_FILL
    
    row_num += 1

# === SHEET 3: All Qualifying Props ===
ws_all = wb.create_sheet("All_Qualifying")

# Write headers
all_cols = list(df_plays.columns)
for col, header in enumerate(all_cols, 1):
    cell = ws_all.cell(row=1, column=col, value=header)
    cell.font = HEADER_FONT
    cell.fill = HEADER_FILL
    cell.border = THIN_BORDER

# Write data
for row_idx, (_, row) in enumerate(df_plays.iterrows(), 2):
    for col_idx, col_name in enumerate(all_cols, 1):
        cell = ws_all.cell(row=row_idx, column=col_idx, value=row[col_name])
        cell.border = THIN_BORDER

# Save
wb.save(OUTPUT_FILE)
print(f"   ✅ Saved: {OUTPUT_FILE}")

# ============================================================
# SUMMARY
# ============================================================
print("\n" + "=" * 60)
print("📊 SUMMARY")
print("=" * 60)
print(f"Total Qualifying Props: {len(all_qualifying)}")
print(f"  🔒 LOCKS: {len(locks)}")
print(f"  ✅ STRONG: {len(strong)}")
print(f"  📋 OTHER: {len(others)}")
print(f"\nParlays Built: {len(parlays)}")
print(f"Legs Per Parlay: {LEGS_PER_PARLAY}")
print(f"\n🔴 4th Leg = Rotation Position (highlighted in red)")
print(f"   Save these legs when rebuilding after a miss")

print("\n🔥 TOP LOCKS (100% L5):")
for _, row in locks.head(10).iterrows():
    print(f"   • {row['Player']} {row['Stat']} {row['Line']} ({row['Hit% L5']})")

print(f"\n📁 Output saved to: {OUTPUT_FILE}")
print("\nGood luck! 🍀")
