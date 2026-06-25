# -*- coding: utf-8 -*-
"""
Prop Betting Pointers Engine
============================

Teaches the user *while they bet*. Every prop page surfaces:

  1. Universal pointers  — apply to every sport.
  2. Sport-specific checks — only relevant to that sport.
  3. A sport profile      — Opportunity / Winner reliability / Best market type /
                            Main trap, so the user knows what they're walking into.

Baseline truth we never hide: props and parlays usually carry more sportsbook
hold than standard sides/totals, and that hold compounds as parlay legs are
added. A prop is only beatable when the *number is wrong, the role is clear, and
the market hasn't already corrected*. Sources the framing leans on:
  - SportsLine prop guide: https://www.sportsline.com/guides/props/
  - OddsJam hold calculator: https://oddsjam.com/betting-calculators/hold
  - Unabated hold calculator: https://unabated.com/betting-calculators/hold-calculator
"""

BASELINE = (
    "Props carry more book hold than sides/totals, and that hold compounds with "
    "every parlay leg. A prop is only worth it when the number is wrong, the role "
    "is clear, and the market hasn't already corrected."
)

# Shown on every prop page, every sport.
UNIVERSAL = [
    "Role beats name — don't bet a famous player if the role is unstable.",
    "Minutes / snaps / usage matter more than raw talent.",
    "The best prop is often boring.",
    "Don't chase a line after it moves.",
    "Avoid props tied to uncertain injury news — unless that uncertainty IS your edge.",
    "Never bet an Over just because the player is hot.",
    "Unders are uncomfortable but often where the value lives.",
    "Don't parlay weak props just to make them exciting.",
    "Check the line, not just the projection.",
    "A good pass saves bankroll.",
]

# Per-sport profile + checks. Keys match the app's sport_key values.
# opp / rel scales: "Highest" > "High" > "Medium-High" > "Medium" > "Variable".
_SPORTS = {
    "nba": {
        "label": "NBA",
        "opportunity": "Highest",
        "reliability": "High",
        "best_market": "Minutes & usage props (PTS/REB/AST when minutes are stable)",
        "main_trap": "The 'star on national TV' Over tax",
        "why": "Daily games, clear injury/news impact, measurable usage shifts, and books that can lag on role changes.",
        "best_types": [
            "Points / rebounds / assists when minutes are stable",
            "Rebounds when the opponent's shot profile supports it",
            "Assists when usage and teammate availability align",
            "Unders after an inflated recent hot streak",
        ],
        "checks": [
            "Check minutes first.",
            "Check usage with injured teammates out.",
            "Check pace and blowout risk.",
            "Beware the 'star on national TV' Over tax.",
            "Late injury news can create the best edges.",
        ],
    },
    "wnba": {
        "label": "WNBA",
        "opportunity": "High",
        "reliability": "Medium-High",
        "best_market": "Minutes-based points/rebounds; assists for high-usage guards",
        "main_trap": "Thin market depth and worse limits/availability",
        "why": "Good data edges and less public attention, but fewer games and lower market depth.",
        "best_types": [
            "Minutes-based points / rebounds",
            "Assist props for high-usage guards",
            "Unders when books overreact to one hot game",
        ],
        "checks": [
            "Rotation stability matters.",
            "Small roster changes matter more than casual bettors realize.",
            "Books may be softer, but limits and availability can be worse.",
        ],
    },
    "nfl": {
        "label": "NFL",
        "opportunity": "Medium",
        "reliability": "Medium-High",
        "best_market": "Volume props (receptions, attempts, carries) when game script is clear",
        "main_trap": "Public star-Over bias, especially in prime time",
        "why": "Fewer games but massive public bias — and great data when game script is readable.",
        "best_types": [
            "Receiving yards / receptions tied to matchup",
            "QB attempts / completions tied to game script",
            "RB rushing attempts / yards tied to spread and O-line",
            "Kicker props in weather / pace spots",
        ],
        "checks": [
            "Game script is king.",
            "Weather matters.",
            "Offensive-line injuries matter.",
            "The public loves star Overs.",
            "Prime-time props are dangerous — everyone wants action.",
        ],
    },
    "ncaaf": {
        "label": "College Football",
        "opportunity": "Medium",
        "reliability": "Medium",
        "best_market": "QB rush/pass & RB workload props in scheme mismatches",
        "main_trap": "Depth-chart uncertainty and blowouts killing Overs",
        "why": "Edges can be strong when data is clean, but depth-chart volatility is real.",
        "best_types": [
            "QB rushing / passing in scheme mismatches",
            "RB workload props in run-heavy systems",
            "Team-total-adjacent props when a tempo mismatch exists",
        ],
        "checks": [
            "Scheme matters more than name.",
            "Blowouts can kill Overs.",
            "Pace and play volume matter.",
            "Depth-chart uncertainty is dangerous.",
            "Smaller schools can offer softer numbers — if the data is clean.",
        ],
    },
    "mlb": {
        "label": "MLB",
        "opportunity": "High",
        "reliability": "Medium-High (pitchers)",
        "best_market": "Pitcher strikeouts and outs recorded",
        "main_trap": "Batter variance — one swing makes a bad process look good",
        "why": "Massive daily volume, but high variance — best when focused on pitcher props.",
        "best_types": [
            "Pitcher strikeouts",
            "Pitcher outs recorded",
            "Batter total bases in specific matchup spots",
            "Walks / earned runs where umpire, weather, and context support it",
        ],
        "checks": [
            "Pitcher props are usually cleaner than hitter props.",
            "Batter props are volatile.",
            "Umpire, weather, park, lineup, and bullpen all matter.",
            "Don't overreact to batter hot streaks.",
            "One swing can make a bad process look good.",
        ],
    },
    "ncaamb": {
        "label": "College Basketball",
        "opportunity": "Variable (high early-season & conference mismatches)",
        "reliability": "Medium",
        "best_market": "Star usage props; rebounds in tempo/miss-heavy matchups",
        "main_trap": "Foul trouble and blowout risk",
        "why": "Can be excellent in early-season and mismatch spots, but prop availability and data consistency vary.",
        "best_types": [
            "Star usage props",
            "Rebounds in tempo / miss-heavy matchups",
            "Points for teams with short rotations",
        ],
        "checks": [
            "Rotation data is everything.",
            "Foul-trouble risk is higher.",
            "Blowout risk matters.",
            "Early season can be softer.",
            "Conference play changes roles.",
        ],
    },
}
# Women's college hoops shares the CBB playbook.
_SPORTS["ncaawb"] = dict(_SPORTS["ncaamb"], label="Women's College Basketball")


def get_prop_pointers(sport_key):
    """Return the pointers payload for a prop page, or None if the sport is unknown
    (so the template can simply skip the card)."""
    key = (sport_key or "").strip().lower()
    sport = _SPORTS.get(key)
    if not sport:
        return None
    return {
        "baseline": BASELINE,
        "universal": UNIVERSAL,
        "sport": sport,
    }
