#!/usr/bin/env python3
"""
🏀 FLOOR PLAY ANALYZER v1.0
=============================================
Processes YOUR data - NO API calls

Methodology:
- Target: 70%+ hit rate
- Minimum: 10 games played
- Samples: Full Season, Last 10, Last 5
- Enhancements: Consensus, Trend, Home/Away, B2B, Minutes, Consistency
"""

import statistics
from datetime import datetime

# ============================================================
# CONFIGURATION
# ============================================================
TARGET_HIT_RATE = 70
MIN_GAMES_PLAYED = 10

print("=" * 60)
print("🏀 FLOOR PLAY ANALYZER v1.0")
print(f"📅 Date: {datetime.now().strftime('%Y-%m-%d')}")
print(f"🎯 Target: {TARGET_HIT_RATE}%+ hit rate")
print(f"📊 Minimum games: {MIN_GAMES_PLAYED}")
print("=" * 60)

# ============================================================
# CORE CALCULATION FUNCTIONS
# ============================================================
def calculate_hit_rate(values, line):
    """Calculate what % of games exceeded the line"""
    if not values:
        return 0, 0, 0
    games_over = sum(1 for v in values if v > line)
    hit_rate = round(games_over / len(values) * 100, 1)
    return hit_rate, games_over, len(values)

def calculate_trend(full_rate, l10_rate, l5_rate):
    """Determine trend direction"""
    if l5_rate > full_rate + 5:
        return "↑ RISING"
    elif l5_rate < full_rate - 5:
        return "↓ FALLING"
    else:
        return "→ STABLE"

def get_consensus(full_rate, l10_rate, l5_rate, target=TARGET_HIT_RATE):
    """Determine consensus strength"""
    hits = sum([full_rate >= target, l10_rate >= target, l5_rate >= target])
    if hits == 3:
        return "🔒 LOCK"
    elif hits == 2:
        return "✅ STRONG"
    elif hits == 1:
        return "⚠️ MEDIUM"
    else:
        return "❌ WEAK"

def analyze_prop(player, prop_type, line, game_values, is_home=True, is_b2b=False):
    """
    Analyze a single prop
    
    Args:
        player: Player name
        prop_type: points, rebounds, assists, etc
        line: The betting line
        game_values: List of stat values [oldest to newest]
        is_home: Home game?
        is_b2b: Back to back?
    """
    if len(game_values) < MIN_GAMES_PLAYED:
        return {
            "player": player,
            "error": f"Only {len(game_values)} games (need {MIN_GAMES_PLAYED}+)",
            "qualifies": False
        }
    
    # Calculate hit rates
    full_rate, full_over, full_total = calculate_hit_rate(game_values, line)
    
    l10_values = game_values[-10:] if len(game_values) >= 10 else game_values
    l10_rate, l10_over, l10_total = calculate_hit_rate(l10_values, line)
    
    l5_values = game_values[-5:] if len(game_values) >= 5 else game_values
    l5_rate, l5_over, l5_total = calculate_hit_rate(l5_values, line)
    
    # Stats
    avg = round(sum(game_values) / len(game_values), 1)
    std_dev = round(statistics.stdev(game_values), 2) if len(game_values) > 1 else 0
    
    # Trend and consensus
    trend = calculate_trend(full_rate, l10_rate, l5_rate)
    consensus = get_consensus(full_rate, l10_rate, l5_rate)
    
    # Consistency score
    if std_dev < (avg * 0.2):
        consistency = "HIGH"
    elif std_dev < (avg * 0.35):
        consistency = "MEDIUM"
    else:
        consistency = "LOW"
    
    # Flags
    flags = []
    if is_b2b:
        flags.append("🔄 B2B")
    if not is_home:
        flags.append("✈️ AWAY")
    if l5_rate < l10_rate - 10:
        flags.append("📉 RECENT DIP")
    if consistency == "LOW":
        flags.append("⚠️ HIGH VARIANCE")
    
    # Does it qualify?
    qualifies = consensus in ["🔒 LOCK", "✅ STRONG"]
    
    return {
        "player": player,
        "prop": prop_type.upper(),
        "line": line,
        "qualifies": qualifies,
        "full_season": {"rate": full_rate, "over": full_over, "total": full_total},
        "last_10": {"rate": l10_rate, "over": l10_over, "total": l10_total},
        "last_5": {"rate": l5_rate, "over": l5_over, "total": l5_total},
        "average": avg,
        "std_dev": std_dev,
        "consensus": consensus,
        "trend": trend,
        "consistency": consistency,
        "flags": flags,
        "recent_values": game_values[-5:]
    }

def print_result(r):
    """Print formatted result"""
    if "error" in r:
        print(f"\n❌ {r['player']}: {r['error']}")
        return
    
    status = "✅" if r["qualifies"] else "❌"
    print(f"\n{status} {r['player']} - {r['prop']} O/U {r['line']}")
    print(f"   Full: {r['full_season']['rate']}% ({r['full_season']['over']}/{r['full_season']['total']})")
    print(f"   L10:  {r['last_10']['rate']}% ({r['last_10']['over']}/{r['last_10']['total']})")
    print(f"   L5:   {r['last_5']['rate']}% ({r['last_5']['over']}/{r['last_5']['total']})")
    print(f"   Avg: {r['average']} | StdDev: {r['std_dev']} | {r['consistency']} consistency")
    print(f"   {r['consensus']} | {r['trend']}")
    if r["flags"]:
        print(f"   Flags: {' '.join(r['flags'])}")
    print(f"   Last 5 games: {r['recent_values']}")

def find_optimal_line(game_values, target_rate=TARGET_HIT_RATE):
    """Find the line that achieves target hit rate"""
    if len(game_values) < MIN_GAMES_PLAYED:
        return None
    sorted_vals = sorted(game_values)
    index = int(len(sorted_vals) * (1 - target_rate / 100))
    optimal = sorted_vals[index] - 0.5
    return round(optimal * 2) / 2

# ============================================================
# YOUR DATA GOES HERE
# ============================================================
"""
FORMAT:
{
    "player": "Player Name",
    "prop": "points",  # points, rebounds, assists, threes, pra, etc
    "line": 24.5,
    "values": [18, 22, 25, 19, 28, 21, 24, 17, 30, 22, 26, 20],  # oldest to newest
    "is_home": True,
    "is_b2b": False
}
"""

props_to_analyze = [
    # === PASTE YOUR DATA BELOW ===
    
    # Example:
    # {
    #     "player": "Trae Young",
    #     "prop": "points",
    #     "line": 24.5,
    #     "values": [28, 22, 31, 19, 25, 27, 33, 21, 29, 24, 26, 30],
    #     "is_home": True,
    #     "is_b2b": False
    # },
    
    # === END DATA ===
]

# ============================================================
# RUN ANALYSIS
# ============================================================
if props_to_analyze:
    results = []
    qualifying = []
    
    for prop in props_to_analyze:
        result = analyze_prop(
            player=prop["player"],
            prop_type=prop["prop"],
            line=prop["line"],
            game_values=prop["values"],
            is_home=prop.get("is_home", True),
            is_b2b=prop.get("is_b2b", False)
        )
        results.append(result)
        print_result(result)
        
        if result.get("qualifies"):
            qualifying.append(result)
            # Show optimal line
            optimal = find_optimal_line(prop["values"])
            if optimal and optimal != prop["line"]:
                print(f"   💡 Optimal line for 70%: {optimal}")
    
    # Summary
    print("\n" + "=" * 60)
    print("📊 SUMMARY")
    print("=" * 60)
    print(f"Analyzed: {len(results)}")
    print(f"Qualifying (70%+): {len(qualifying)}")
    
    if qualifying:
        print("\n🔒 FLOOR PLAYS:")
        for q in qualifying:
            print(f"   • {q['player']} {q['prop']} O{q['line']} - {q['consensus']} - {q['trend']}")
else:
    print("\n⚠️ No data to analyze.")
    print("Add your props to the 'props_to_analyze' list in this script.")
    print("\nOr paste your Covers data and I'll format it for you.")
