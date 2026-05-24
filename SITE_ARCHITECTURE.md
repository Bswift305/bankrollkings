# 🏀 FLOOR PLAY ENGINE - Site Architecture
## Personal Analysis Platform → Future Web/Mobile App

---

## NAVIGATION STRUCTURE (Dropdown-Based)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  🏀 FLOOR PLAY ENGINE                                    [Date: Jan 9, 2026]│
├─────────────────────────────────────────────────────────────────────────────┤
│  [DASHBOARD] [PLAYERS ▼] [TEAMS ▼] [MATCHUPS ▼] [PROPS ▼] [TOOLS ▼] [DATA] │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 1. DASHBOARD (Home)
**Purpose:** Quick overview of tonight's action + top plays

### Layout:
```
┌──────────────────────────────────────────────────────────────────┐
│ TONIGHT'S SLATE                           [Filter: All Games ▼] │
├──────────────────────────────────────────────────────────────────┤
│ 🏀 TOR @ BOS  7:00pm  │  Total: 218.5  │  Spread: BOS -7.5      │
│ 🏀 PHI @ ORL  7:00pm  │  Total: 212.0  │  Spread: PHI -4.5      │
│ ...                                                              │
├──────────────────────────────────────────────────────────────────┤
│ 🔒 TOP LOCKS (80%+)           │  ⚠️ INJURY ALERTS              │
│ • Grayson Allen AST 2.5 (85%) │  • Jokic OUT - Knee            │
│ • Kelly Oubre PTS 8.5 (84%)   │  • SGA OUT - Ankle             │
│ • Grayson Allen PTS 11.5 (80%)│  • Rui Hachimura GTD - Calf    │
├──────────────────────────────────────────────────────────────────┤
│ 📊 QUICK STATS                │  🎯 SUGGESTED PARLAYS          │
│ Props Analyzed: 410           │  Parlay #1: 6 legs (Avg 72%)   │
│ Locks Found: 98               │  Parlay #2: 5 legs (Avg 74%)   │
│ Floor Plays: 150              │  [View All Parlays →]          │
└──────────────────────────────────────────────────────────────────┘
```

---

## 2. PLAYERS DROPDOWN

```
[PLAYERS ▼]
├── 🔍 Search Player
├── 📋 All Players (A-Z)
├── 🔥 Hot Players (Trending Up)
├── ❄️ Cold Players (Trending Down)
├── 🎯 High Volume (30+ MIN)
├── 📈 Breakout Candidates
└── ⭐ My Watchlist
```

### Player Profile Page:
```
┌─────────────────────────────────────────────────────────────────────────────┐
│ JAYLEN BROWN - Boston Celtics                              [Add to Watch ⭐]│
├─────────────────────────────────────────────────────────────────────────────┤
│ BASIC INFO                    │ TONIGHT'S MATCHUP                          │
│ Position: SF/SG               │ vs TOR @ Home                              │
│ Age: 28                       │ Game Time: 7:00 PM                         │
│ Status: ✅ HEALTHY            │ Spread: BOS -7.5 | Total: 218.5           │
├─────────────────────────────────────────────────────────────────────────────┤
│ STAT SELECTION: [Points ▼] [Rebounds ▼] [Assists ▼] [3PM ▼] [Combo ▼]     │
├─────────────────────────────────────────────────────────────────────────────┤
│                              POINTS ANALYSIS                                │
├─────────────────────────────────────────────────────────────────────────────┤
│ CURRENT LINE: 28.5           │ FLOOR (77%): 22.9                          │
│ SEASON AVG: 29.7             │ HIT RATE @ 28.5: 67.6% (23/34)             │
├─────────────────────────────────────────────────────────────────────────────┤
│ TIME PERIOD ANALYSIS                                                        │
│ ┌─────────────┬─────────┬─────────┬──────────┬─────────┐                   │
│ │ Period      │ Average │ Floor   │ Hit Rate │ Sample  │                   │
│ ├─────────────┼─────────┼─────────┼──────────┼─────────┤                   │
│ │ Season      │ 29.7    │ 22.9    │ 67.6%    │ 34      │                   │
│ │ Last 10     │ 31.2    │ 24.0    │ 80.0%    │ 10      │                   │
│ │ Last 5      │ 32.4    │ 25.0    │ 100%     │ 5       │                   │
│ │ Home        │ 30.8    │ 23.7    │ 76.5%    │ 17      │                   │
│ │ Away        │ 28.6    │ 22.0    │ 58.8%    │ 17      │                   │
│ │ vs TOR      │ 27.3    │ 21.0    │ 50.0%    │ 4       │                   │
│ │ B2B         │ 26.1    │ 20.1    │ 42.9%    │ 7       │                   │
│ │ 2+ Rest     │ 30.9    │ 23.8    │ 74.1%    │ 27      │                   │
│ └─────────────┴─────────┴─────────┴──────────┴─────────┘                   │
├─────────────────────────────────────────────────────────────────────────────┤
│ GAME LOG HEAT MAP (Last 30 Games)                                          │
│ [🟢32][🟢29][🔴25][🟢34][🟢31][🔴22][🟢30][🟢35][🔴27][🟢33]...           │
│  12/8  12/9 12/11 12/13 12/15 12/17 12/19 12/21 12/23 12/25               │
├─────────────────────────────────────────────────────────────────────────────┤
│ SITUATIONAL FACTORS                                                         │
│ ┌────────────────────────────────────────────────────────────────┐         │
│ │ ✅ 2 days rest (optimal)                                       │         │
│ │ ✅ Home game (+1.2 PPG at home)                                │         │
│ │ ⚠️ TOR ranks 8th in PTS allowed to SF                         │         │
│ │ ✅ No Tatum = +4.3 USG% increase                               │         │
│ │ ⚠️ Blowout risk - may see reduced 4Q minutes                  │         │
│ └────────────────────────────────────────────────────────────────┘         │
├─────────────────────────────────────────────────────────────────────────────┤
│ LINE FINDER                                                                 │
│ Find optimal line: [_____] → Hit Rate: [___]%                              │
│ ┌─────────────────────────────────────────────────────────────┐            │
│ │ Line    │ 24.5  │ 25.5  │ 26.5  │ 27.5  │ 28.5  │ 29.5    │            │
│ │ Hit %   │ 88.2% │ 85.3% │ 79.4% │ 73.5% │ 67.6% │ 55.9%   │            │
│ └─────────────────────────────────────────────────────────────┘            │
├─────────────────────────────────────────────────────────────────────────────┤
│ VERDICT: 🟡 LEAN OVER                                                       │
│ Line is at 96% of average. Recent form strong. Home boost helps.           │
│ Concern: Blowout potential could limit minutes.                            │
│                                               [Add to Parlay Builder 🎯]   │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. TEAMS DROPDOWN

```
[TEAMS ▼]
├── 📊 All Teams Overview
├── 🏠 Home Performance
├── ✈️ Road Performance  
├── ⚔️ Offensive Rankings
├── 🛡️ Defensive Rankings
├── 🏃 Pace Rankings
├── 📈 Trends (Hot/Cold)
├── 🤕 Injury Impact
└── 🔍 Search Team
```

### Team Profile Page:
```
┌─────────────────────────────────────────────────────────────────────────────┐
│ BOSTON CELTICS                                          [Tonight: vs TOR]  │
├─────────────────────────────────────────────────────────────────────────────┤
│ TEAM STATS                    │ RANKINGS                                   │
│ Record: 28-12                 │ Offense: 3rd (118.2)                       │
│ Home: 16-4                    │ Defense: 5th (108.7)                       │
│ Away: 12-8                    │ Pace: 8th (101.2)                          │
│ ATS: 22-18                    │ Net Rating: 2nd (+9.5)                     │
├─────────────────────────────────────────────────────────────────────────────┤
│ PROP PERFORMANCE BY POSITION                                               │
│ ┌──────────┬─────────┬─────────┬─────────┬─────────┬─────────┐            │
│ │ Position │ PTS     │ REB     │ AST     │ 3PM     │ STL     │            │
│ ├──────────┼─────────┼─────────┼─────────┼─────────┼─────────┤            │
│ │ PG       │ 22nd    │ 28th    │ 5th     │ 12th    │ 18th    │  ← Allowed │
│ │ SG       │ 8th     │ 15th    │ 20th    │ 3rd     │ 22nd    │            │
│ │ SF       │ 12th    │ 10th    │ 8th     │ 6th     │ 14th    │            │
│ │ PF       │ 5th     │ 3rd     │ 25th    │ 18th    │ 9th     │            │
│ │ C        │ 15th    │ 7th     │ 30th    │ 28th    │ 11th    │            │
│ └──────────┴─────────┴─────────┴─────────┴─────────┴─────────┘            │
│ (Lower = allows more of that stat)                                         │
├─────────────────────────────────────────────────────────────────────────────┤
│ ACTIVE ROSTER & PROPS                                                      │
│ [View Full Roster ▼]                                                       │
│ ┌─────────────────┬───────┬───────┬───────┬───────┬───────┬───────┐       │
│ │ Player          │ MIN   │ PTS   │ REB   │ AST   │ 3PM   │ Status│       │
│ ├─────────────────┼───────┼───────┼───────┼───────┼───────┼───────┤       │
│ │ Jaylen Brown    │ 33.9  │ 29.7  │ 6.4   │ 4.9   │ 2.2   │ ✅    │       │
│ │ Derrick White   │ 32.1  │ 17.2  │ 3.8   │ 5.1   │ 3.1   │ ✅    │       │
│ │ Payton Pritchard│ 28.4  │ 16.8  │ 2.9   │ 5.2   │ 3.4   │ ✅    │       │
│ │ Jayson Tatum    │  0.0  │  ---  │  ---  │  ---  │  ---  │ OUT   │       │
│ └─────────────────┴───────┴───────┴───────┴───────┴───────┴───────┘       │
├─────────────────────────────────────────────────────────────────────────────┤
│ INJURY IMPACT ANALYSIS                                                      │
│ Without Jayson Tatum (15 games):                                           │
│ • Jaylen Brown: +4.3 PPG, +1.2 RPG, +0.8 APG                              │
│ • Derrick White: +2.1 PPG, +0.5 APG                                        │
│ • Payton Pritchard: +3.8 PPG, +1.1 APG                                     │
│ • Team Pace: -1.8 possessions/game                                         │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. MATCHUPS DROPDOWN

```
[MATCHUPS ▼]
├── 🎮 Tonight's Games
│   ├── TOR @ BOS
│   ├── PHI @ ORL
│   ├── NOP @ WAS
│   ├── LAC @ BKN
│   ├── OKC @ MEM
│   ├── ATL @ DEN
│   ├── NYK @ PHX
│   ├── SAC @ GSW
│   ├── HOU @ POR
│   └── MIL @ LAL
├── 📅 Tomorrow's Games
├── 📆 Weekly Schedule
├── 🔥 High Total Games (220+)
├── 🧊 Low Total Games (<210)
├── 📊 Best Pace-Up Matchups
└── 🛡️ Tough Defensive Matchups
```

### Matchup Analysis Page:
```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         TOR @ BOS - 7:00 PM                                │
│                    TD Garden | ESPN | Spread: BOS -7.5                     │
├─────────────────────────────────────────────────────────────────────────────┤
│ TORONTO RAPTORS          │ VS │          BOSTON CELTICS                    │
│ Record: 15-25            │    │          Record: 28-12                     │
│ Away: 6-14               │    │          Home: 16-4                        │
│ Off Rtg: 108.2 (22nd)    │    │          Off Rtg: 118.2 (3rd)             │
│ Def Rtg: 115.1 (28th)    │    │          Def Rtg: 108.7 (5th)             │
│ Pace: 99.8 (15th)        │    │          Pace: 101.2 (8th)                │
├─────────────────────────────────────────────────────────────────────────────┤
│ VEGAS LINES              │ GAME ENVIRONMENT                               │
│ Spread: BOS -7.5         │ Projected Pace: 100.5                          │
│ Total: 218.5             │ Projected Possessions: 98                      │
│ TOR Implied: 105.5       │ Blowout Probability: 35%                       │
│ BOS Implied: 113.0       │ Competitive Game Prob: 45%                     │
├─────────────────────────────────────────────────────────────────────────────┤
│ KEY INJURIES                                                               │
│ TOR: Brandon Ingram (GTD-Thumb), Scottie Barnes (Q-Knee)                  │
│ BOS: Jayson Tatum (OUT-Achilles)                                          │
├─────────────────────────────────────────────────────────────────────────────┤
│ HEAD-TO-HEAD THIS SEASON (2 games)                                         │
│ Game 1: BOS 118 - TOR 102 │ Brown: 28p/7r │ Barrett: 22p/5r              │
│ Game 2: TOR 108 - BOS 115 │ Brown: 31p/5r │ Barrett: 19p/8r              │
├─────────────────────────────────────────────────────────────────────────────┤
│ 🎯 TOP PROP PLAYS THIS MATCHUP                                             │
│ ┌─────────────────┬──────┬───────┬────────┬──────────────────────────┐    │
│ │ Player          │ Prop │ Line  │ Hit %  │ Edge                     │    │
│ ├─────────────────┼──────┼───────┼────────┼──────────────────────────┤    │
│ │ Jaylen Brown    │ PTS  │ 28.5  │ 67.6%  │ 🟡 Slight value          │    │
│ │ RJ Barrett      │ 3PM  │ 1.5   │ 68.2%  │ 🟢 Good value            │    │
│ │ Derrick White   │ AST  │ 5.5   │ 62.1%  │ 🔴 Line too high         │    │
│ │ Payton Pritchard│ 3PM  │ 2.5   │ 71.4%  │ 🟢 Strong play           │    │
│ └─────────────────┴──────┴───────┴────────┴──────────────────────────┘    │
│                                              [Analyze All Props →]         │
├─────────────────────────────────────────────────────────────────────────────┤
│ POSITIONAL MATCHUP EDGES                                                   │
│ TOR Guards vs BOS: BOS allows 24th most PTS to guards → OVER lean         │
│ TOR Forwards vs BOS: BOS allows 5th fewest to forwards → UNDER lean       │
│ BOS Guards vs TOR: TOR allows 3rd most PTS to guards → OVER lean          │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 5. PROPS DROPDOWN

```
[PROPS ▼]
├── 🔒 Locks (80%+)
├── 💪 Strong Plays (70-79%)
├── 📉 Floor Plays (Line < 77%)
├── 🔥 Heat Maps
│   ├── Points
│   ├── Rebounds
│   ├── Assists
│   ├── 3-Pointers
│   ├── Steals
│   └── Blocks
├── 📊 By Stat Category
│   ├── Points Props
│   ├── Rebounds Props
│   ├── Assists Props
│   ├── 3PM Props
│   ├── Steals Props
│   ├── Blocks Props
│   └── Combo Props (PRA, PR, PA)
├── 🎯 By Confidence Level
├── 📈 Line Movement Tracker
├── 💰 Value Finder (Edge Calculator)
└── 🔄 Correlation Finder
```

### Props Hub Page:
```
┌─────────────────────────────────────────────────────────────────────────────┐
│ PROP ANALYSIS HUB                                    [Tonight: 410 Props]  │
├─────────────────────────────────────────────────────────────────────────────┤
│ FILTERS:                                                                    │
│ [Stat ▼] [Team ▼] [Game ▼] [Min Hit% ▼] [Min Games ▼] [Status ▼]          │
├─────────────────────────────────────────────────────────────────────────────┤
│ QUICK VIEW TABS:                                                           │
│ [All Props] [Locks 🔒] [Strong 💪] [Floor 📉] [Avoid 🚫]                   │
├─────────────────────────────────────────────────────────────────────────────┤
│ RESULTS: 98 Locks Found                              [Export Excel 📥]     │
│ ┌────────────────┬──────┬─────────────┬──────┬───────┬───────┬──────────┐ │
│ │ Player         │ Team │ Matchup     │ Stat │ Line  │ Avg   │ Hit %    │ │
│ ├────────────────┼──────┼─────────────┼──────┼───────┼───────┼──────────┤ │
│ │ Grayson Allen  │ PHX  │ NYK @ PHX   │ AST  │ 2.5   │ 4.0   │ 85.0% 🔒│ │
│ │ Kelly Oubre Jr.│ PHI  │ PHI @ ORL   │ PTS  │ 8.5   │ 15.6  │ 84.6% 🔒│ │
│ │ Grayson Allen  │ PHX  │ NYK @ PHX   │ PTS  │ 11.5  │ 15.7  │ 80.0% 🔒│ │
│ │ ...            │      │             │      │       │       │          │ │
│ └────────────────┴──────┴─────────────┴──────┴───────┴───────┴──────────┘ │
│ [← Prev] Page 1 of 10 [Next →]                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│ CLICK ROW TO EXPAND:                                                        │
│ ┌─────────────────────────────────────────────────────────────────────────┐│
│ │ Grayson Allen AST 2.5                                                   ││
│ │ Season: 4.0 avg | L5: 4.4 avg | L10: 4.2 avg | vs NYK: 3.5 avg         ││
│ │ Heat Map: [🟢][🟢][🟢][🟢][🔴][🟢][🟢][🟢][🟢][🟢]                      ││
│ │ Factors: ✅ Home, ✅ 2 days rest, ⚠️ NYK 12th in AST allowed           ││
│ │                                              [Add to Parlay 🎯]         ││
│ └─────────────────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 6. TOOLS DROPDOWN

```
[TOOLS ▼]
├── 🎯 Parlay Builder
├── 📊 Correlation Analyzer
├── 🧮 Expected Value Calculator
├── 📈 Line Movement Tracker
├── 🔄 What-If Scenarios
├── 📉 Regression Finder
├── 🎰 Odds Converter
├── 💰 Bankroll Manager
├── 📋 Bet Tracker
└── ⚙️ Settings
```

### Parlay Builder:
```
┌─────────────────────────────────────────────────────────────────────────────┐
│ 🎯 PARLAY BUILDER                                                          │
├─────────────────────────────────────────────────────────────────────────────┤
│ DIVERSIFICATION RULES:                     │ CURRENT PARLAY                │
│ ☑️ Max 1 prop per player                  │ ┌─────────────────────────────┐│
│ ☑️ Max 3 props per game                   │ │ 1. Grayson Allen AST 2.5    ││
│ ☑️ Exclude B2B teams                      │ │    Hit: 85% | Edge: +12%    ││
│ ☑️ Min 70% hit rate                       │ │ 2. Kelly Oubre PTS 8.5      ││
│ ☐ Same game parlay mode                   │ │    Hit: 84% | Edge: +8%     ││
│                                            │ │ 3. [Add Leg...]             ││
├────────────────────────────────────────────┤ │                             ││
│ AVAILABLE PROPS (Filtered)                 │ │ ─────────────────────────── ││
│ ┌────────────────────────────────────────┐ │ │ PARLAY STATS:               ││
│ │ [+] Rui Hachimura PTS 8.5 (77.8%)     │ │ │ Combined Hit: 71.4%         ││
│ │ [+] Mikal Bridges 3PM 1.5 (73.0%)     │ │ │ Correlation: Low ✅         ││
│ │ [+] Reed Sheppard 3PM 1.5 (70.6%)     │ │ │ Legs: 2 of 6                ││
│ │ [+] Ryan Rollins AST 4.5 (70.3%)      │ │ │                             ││
│ │ ...                                    │ │ │ [Clear All] [Save Parlay]  ││
│ └────────────────────────────────────────┘ │ └─────────────────────────────┘│
├─────────────────────────────────────────────────────────────────────────────┤
│ CORRELATION WARNINGS:                                                       │
│ ⚠️ Adding Brown PTS + Brown REB = High correlation (same player)           │
│ ⚠️ Adding 2 BOS players = Moderate correlation (same game script)          │
│ ✅ Grayson Allen + Kelly Oubre = Low correlation (different games)         │
├─────────────────────────────────────────────────────────────────────────────┤
│ SUGGESTED COMPLETIONS:                                                      │
│ Based on your current legs, consider adding:                                │
│ • Jamal Murray 3PM 2.5 (60.0%) - Different game, low correlation           │
│ • Myles Turner 3PM 1.5 (67.6%) - Different game, MIL @ LAL                 │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Correlation Analyzer:
```
┌─────────────────────────────────────────────────────────────────────────────┐
│ 🔄 CORRELATION ANALYZER                                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│ SAME PLAYER CORRELATIONS:                                                   │
│ ┌─────────────────────────────────────────────────────────────────────────┐│
│ │ Player: [Jaylen Brown ▼]                                                ││
│ │                                                                         ││
│ │           PTS    REB    AST    3PM    STL                              ││
│ │ PTS       1.00   0.42   0.38   0.67   0.12                             ││
│ │ REB       0.42   1.00   0.21   0.18   0.15                             ││
│ │ AST       0.38   0.21   1.00   0.25   0.22                             ││
│ │ 3PM       0.67   0.18   0.25   1.00   0.08                             ││
│ │ STL       0.12   0.15   0.22   0.08   1.00                             ││
│ │                                                                         ││
│ │ 💡 High correlation: PTS ↔ 3PM (0.67) - When 3s fall, points follow   ││
│ └─────────────────────────────────────────────────────────────────────────┘│
├─────────────────────────────────────────────────────────────────────────────┤
│ TEAMMATE CORRELATIONS:                                                      │
│ When Brown scores 30+:                                                      │
│ • White PTS: -2.1 avg (inverse correlation)                                │
│ • Pritchard 3PM: +0.4 avg (positive - pace related)                        │
├─────────────────────────────────────────────────────────────────────────────┤
│ GAME SCRIPT CORRELATIONS:                                                   │
│ In blowouts (15+ point games):                                             │
│ • Starters minutes: -6.2 avg                                               │
│ • Bench PTS: +8.4 avg                                                      │
└─────────────────────────────────────────────────────────────────────────────┘
```

### What-If Scenarios:
```
┌─────────────────────────────────────────────────────────────────────────────┐
│ 🔄 WHAT-IF SCENARIO BUILDER                                                │
├─────────────────────────────────────────────────────────────────────────────┤
│ SCENARIO: [Scottie Barnes OUT ▼]                                           │
├─────────────────────────────────────────────────────────────────────────────┤
│ HISTORICAL DATA (12 games without Barnes):                                  │
│ ┌────────────────┬──────────┬──────────┬───────────┐                       │
│ │ Player         │ Normal   │ W/O Barnes│ Change   │                       │
│ ├────────────────┼──────────┼──────────┼───────────┤                       │
│ │ RJ Barrett PTS │ 19.5     │ 23.8     │ +4.3 📈  │                       │
│ │ RJ Barrett AST │ 4.2      │ 6.1      │ +1.9 📈  │                       │
│ │ Quickley PTS   │ 16.5     │ 19.2     │ +2.7 📈  │                       │
│ │ Team Pace      │ 99.8     │ 97.2     │ -2.6 📉  │                       │
│ └────────────────┴──────────┴──────────┴───────────┘                       │
│                                                                             │
│ PROP ADJUSTMENTS:                                                           │
│ • RJ Barrett PTS 19.5 → Adjusted 77% floor: 18.3 (was 15.0)               │
│ • Consider: Barrett PTS OVER if Barnes is ruled OUT                        │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 7. DATA DROPDOWN / SETTINGS

```
[DATA ▼]
├── 📥 Import Props (CSV/Paste)
├── 📥 Update Game Logs
├── 📥 Update Injuries
├── 📥 Update Schedule
├── 📤 Export Analysis
├── 🔄 Refresh All Data
├── 📊 Data Status Dashboard
└── ⚙️ Settings
    ├── Floor Percentage (default 77%)
    ├── Min Hit Rate Threshold
    ├── Min Games Sample Size
    ├── Timezone
    ├── Theme (Dark/Light)
    └── Notifications
```

---

## DATA REQUIREMENTS

### Required Data Files:
```
/data
├── /gamelogs
│   └── NBA_GameLogs.csv       ← Player box scores (30+ days)
├── /props
│   └── NBA_Props.csv          ← Today's betting lines
├── /injuries
│   └── NBA_Injuries.csv       ← Current injury report
├── /schedules
│   └── NBA_Schedule.csv       ← Game schedule
├── /rosters
│   └── NBA_Rosters.csv        ← Team rosters
├── /defense
│   └── NBA_DefenseRanks.csv   ← Position defense rankings
├── /vegas
│   └── NBA_Lines.csv          ← Spreads & totals
└── /historical
    └── NBA_Results.csv        ← Past bet results tracking
```

### Calculated Metrics:
- Hit Rate @ Line (season, L10, L5, home, away, vs team, B2B)
- Floor Value (77% of average)
- Edge % (how far line is from floor)
- Trend Direction (UP/DOWN/FLAT)
- Correlation Coefficients
- Expected Value
- Blowout Probability
- Minutes Projection

---

## FUTURE MOBILE APP STRUCTURE

```
┌─────────────────────────────────┐
│ 🏀 FLOOR PLAY                   │
├─────────────────────────────────┤
│ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐│
│ │Home │ │Props│ │Build│ │More ││
│ │ 🏠  │ │ 📊  │ │ 🎯  │ │ ≡   ││
│ └─────┘ └─────┘ └─────┘ └─────┘│
└─────────────────────────────────┘

HOME: Tonight's locks, alerts, quick stats
PROPS: Full prop browser with filters
BUILD: Parlay builder
MORE: Players, Teams, Tools, Settings
```

---

## DEVELOPMENT PHASES

### Phase 1: Core Engine (Current)
- [x] Game log analysis
- [x] Hit rate calculations
- [x] Floor calculations
- [x] Heat map generation
- [x] Excel export

### Phase 2: Web Dashboard (Next)
- [ ] Flask routes for all pages
- [ ] Dropdown navigation
- [ ] Player search & profiles
- [ ] Team profiles
- [ ] Matchup pages
- [ ] Props hub with filters

### Phase 3: Advanced Tools
- [ ] Parlay builder with correlation
- [ ] Line movement tracking
- [ ] What-if scenarios
- [ ] EV calculator
- [ ] Bet tracker

### Phase 4: Data Automation
- [ ] Auto-scrape game logs
- [ ] Auto-update injuries
- [ ] Line movement alerts
- [ ] Push notifications

### Phase 5: Mobile App
- [ ] React Native or Flutter
- [ ] Push notifications
- [ ] Quick bet slip builder
- [ ] Widget for locks

---

## SHARP BETTOR CHECKLIST
Everything a sharp considers - all available on site:

### Player Level:
- [ ] Season average
- [ ] Last 5/10 game average
- [ ] Home vs Away splits
- [ ] vs Opponent history
- [ ] B2B performance
- [ ] Rest day impact
- [ ] Minutes trend
- [ ] Usage rate changes
- [ ] Injury status
- [ ] Hot/cold streak

### Team Level:
- [ ] Offensive rating
- [ ] Defensive rating
- [ ] Pace
- [ ] Position defense rankings
- [ ] Injury impact on teammates
- [ ] Home/away splits
- [ ] ATS record

### Game Level:
- [ ] Vegas total (pace indicator)
- [ ] Spread (blowout risk)
- [ ] Implied team totals
- [ ] Pace matchup
- [ ] Rest advantage
- [ ] Travel factors

### Line Level:
- [ ] Current line vs floor
- [ ] Hit rate at line
- [ ] Line movement
- [ ] Alternate lines
- [ ] Correlation with other props
- [ ] SGP considerations

---

*Document Version: 1.0*
*Last Updated: January 9, 2026*
