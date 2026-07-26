"""NFL home-stadium coordinates and roof type.

Data only, no app import -- both fetch_nfl_weather.py and app.py use it. Keyed by
the full team name the odds/schedule feeds use (e.g. 'Buffalo Bills'). `wind_exposed`
is the only field the wind signal cares about: True for open-air fields, False for
domes and retractables (retractables are almost always closed in bad weather, so we
do not flag wind for them rather than guess the roof state).
"""

from __future__ import annotations

# (latitude, longitude, roof, wind_exposed)
NFL_STADIUMS = {
    'Arizona Cardinals': (33.528, -112.263, 'retractable', False),
    'Atlanta Falcons': (33.755, -84.401, 'retractable', False),
    'Baltimore Ravens': (39.278, -76.623, 'outdoor', True),
    'Buffalo Bills': (42.774, -78.787, 'outdoor', True),
    'Carolina Panthers': (35.226, -80.853, 'outdoor', True),
    'Chicago Bears': (41.862, -87.617, 'outdoor', True),
    'Cincinnati Bengals': (39.095, -84.516, 'outdoor', True),
    'Cleveland Browns': (41.506, -81.700, 'outdoor', True),
    'Dallas Cowboys': (32.748, -97.093, 'retractable', False),
    'Denver Broncos': (39.744, -105.020, 'outdoor', True),
    'Detroit Lions': (42.340, -83.046, 'dome', False),
    'Green Bay Packers': (44.501, -88.062, 'outdoor', True),
    'Houston Texans': (29.685, -95.411, 'retractable', False),
    'Indianapolis Colts': (39.760, -86.164, 'retractable', False),
    'Jacksonville Jaguars': (30.324, -81.637, 'outdoor', True),
    'Kansas City Chiefs': (39.049, -94.484, 'outdoor', True),
    'Las Vegas Raiders': (36.091, -115.184, 'dome', False),
    'Los Angeles Chargers': (33.953, -118.339, 'dome', False),   # SoFi (fixed roof)
    'Los Angeles Rams': (33.953, -118.339, 'dome', False),       # SoFi (fixed roof)
    'Miami Dolphins': (25.958, -80.239, 'outdoor', True),
    'Minnesota Vikings': (44.974, -93.258, 'dome', False),
    'New England Patriots': (42.091, -71.264, 'outdoor', True),
    'New Orleans Saints': (29.951, -90.081, 'dome', False),
    'New York Giants': (40.813, -74.074, 'outdoor', True),       # MetLife
    'New York Jets': (40.813, -74.074, 'outdoor', True),         # MetLife
    'Philadelphia Eagles': (39.901, -75.168, 'outdoor', True),
    'Pittsburgh Steelers': (40.447, -80.016, 'outdoor', True),
    'San Francisco 49ers': (37.403, -121.970, 'outdoor', True),
    'Seattle Seahawks': (47.595, -122.332, 'outdoor', True),
    'Tampa Bay Buccaneers': (27.976, -82.503, 'outdoor', True),
    'Tennessee Titans': (36.166, -86.771, 'outdoor', True),
    'Washington Commanders': (38.908, -76.864, 'outdoor', True),
}
