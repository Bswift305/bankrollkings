'use client';

import React, { useState, useEffect } from 'react';
// Using emoji icons instead of lucide-react for compatibility

const NFL_SITUATIONAL_ANALYSIS = () => {
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [debugExpanded, setDebugExpanded] = useState(false);
  const [rawResponse, setRawResponse] = useState(null);
  
  // Filter states
  const [selectedPosition, setSelectedPosition] = useState('All Positions');
  const [selectedTeam, setSelectedTeam] = useState('All Teams');
  const [selectedDefenseTier, setSelectedDefenseTier] = useState('All Defense Tiers');
  const [selectedSituation, setSelectedSituation] = useState('All Situations');
  const [selectedHomeAway, setSelectedHomeAway] = useState('All Games');
  const [selectedGameType, setSelectedGameType] = useState('All Games');
  const [selectedWeather, setSelectedWeather] = useState('All Weather');

  // Filter options
  const positions = ['All Positions', 'RB', 'WR', 'TE', 'QB'];
  const teams = ['All Teams', 'Buffalo', 'Miami', 'New England', 'NY Jets', 'Baltimore', 'Cincinnati', 'Cleveland', 'Pittsburgh', 'Houston', 'Indianapolis', 'Jacksonville', 'Tennessee', 'Denver', 'Kansas City', 'Las Vegas', 'LA Chargers'];
  const defenseTiers = ['All Defense Tiers', '🔥 Elite', '✅ Good', '📊 Average', '📉 Poor'];
  const situations = ['All Situations', '🎯 Red Zone', '3️⃣ 3rd Down', '🏁 Goal Line', '⏰ 2-Min Drill', '4️⃣ 4th Down'];
  const homeAwayOptions = ['🏠 Home/Away', '🏠 Home', '✈️ Away'];
  const gameTypes = ['All Games', '🌙 Prime Time', '☀️ Regular'];
  const weatherOptions = ['🌤️ All Weather', '🏟️ Dome', '☀️ Clear', '🌧️ Rain', '❄️ Snow', '💨 Windy'];

  useEffect(() => {
    fetchData();
  }, [selectedPosition, selectedTeam, selectedDefenseTier, selectedSituation, selectedHomeAway, selectedGameType, selectedWeather]);

  const fetchData = async () => {
    setLoading(true);
    setError(null);
    
    try {
      const params = new URLSearchParams();
      
      if (selectedPosition !== 'All Positions') params.append('position', selectedPosition);
      if (selectedTeam !== 'All Teams') params.append('team', selectedTeam);
      if (selectedDefenseTier !== 'All Defense Tiers') {
        const tierMap: { [key: string]: string } = {
          '🔥 Elite': 'elite',
          '✅ Good': 'good', 
          '📊 Average': 'average',
          '📉 Poor': 'poor'
        };
        params.append('defense_tier', tierMap[selectedDefenseTier]);
      }
      
      const response = await fetch(`/api/situations?${params.toString()}`);
      const result = await response.json();
      
      setRawResponse(result);
      
      if (response.ok && result.rows) {
        setData(result.rows);
      } else {
        setError(`HTTP ${response.status}: ${result.error || 'Unknown error'}`);
        setData([]);
      }
    } catch (err) {
      setError(`Network error: ${err instanceof Error ? err.message : 'Unknown error'}`);
      setData([]);
      setRawResponse(null);
    } finally {
      setLoading(false);
    }
  };

  const clearAllFilters = () => {
    setSelectedPosition('All Positions');
    setSelectedTeam('All Teams');
    setSelectedDefenseTier('All Defense Tiers');
    setSelectedSituation('All Situations');
    setSelectedHomeAway('All Games');
    setSelectedGameType('All Games');
    setSelectedWeather('All Weather');
  };

  const getDefenseTierColor = (tier: string) => {
    const colors: { [key: string]: string } = {
      'top10': 'from-red-500 to-pink-600',
      'bottom10': 'from-green-400 to-emerald-500',
      'middle': 'from-yellow-400 to-orange-500'
    };
    return colors[tier] || 'from-gray-400 to-gray-500';
  };

  const getDefenseTierLabel = (tier: string) => {
    const labels: { [key: string]: string } = {
      'top10': '🔥 Elite',
      'bottom10': '📉 Poor', 
      'middle': '📊 Average'
    };
    return labels[tier] || tier;
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-purple-900 to-slate-900">
      {/* Animated Background */}
      <div className="absolute inset-0 overflow-hidden">
        <div className="absolute -inset-10 opacity-20">
          <div className="absolute top-0 -left-4 w-72 h-72 bg-purple-500 rounded-full mix-blend-multiply filter blur-xl animate-pulse"></div>
          <div className="absolute top-0 -right-4 w-72 h-72 bg-blue-500 rounded-full mix-blend-multiply filter blur-xl animate-pulse animation-delay-2000"></div>
          <div className="absolute -bottom-8 left-20 w-72 h-72 bg-pink-500 rounded-full mix-blend-multiply filter blur-xl animate-pulse animation-delay-4000"></div>
        </div>
      </div>

      <div className="relative z-10 px-4 py-8">
        {/* Header */}
        <div className="text-center mb-12">
          <div className="inline-flex items-center gap-3 mb-4">
            <div className="p-3 bg-gradient-to-r from-purple-600 to-pink-600 rounded-xl shadow-lg">
              <span className="text-2xl">📈</span>
            </div>
            <h1 className="text-5xl font-black bg-gradient-to-r from-purple-400 via-pink-400 to-blue-400 bg-clip-text text-transparent">
              BANKROLLKINGS
            </h1>
          </div>
          <p className="text-xl text-purple-200 font-light">
            Advanced player vs defense matchup analysis for prop betting insights
          </p>
          <div className="mt-4 inline-flex items-center gap-2 px-4 py-2 bg-black/30 backdrop-blur-sm rounded-full border border-purple-500/20">
            <div className="w-2 h-2 bg-green-400 rounded-full animate-pulse"></div>
            <span className="text-green-400 text-sm font-medium">LIVE DATA</span>
          </div>
        </div>

        {/* Debug Panel */}
        <div className="max-w-7xl mx-auto mb-8">
          <div className="bg-black/40 backdrop-blur-sm border border-purple-500/20 rounded-2xl p-6 shadow-2xl">
            <button 
              onClick={() => setDebugExpanded(!debugExpanded)}
              className="flex items-center gap-3 text-purple-300 hover:text-purple-200 transition-colors group"
            >
              <span className="text-purple-400 text-xl">⚡</span>
              <span className="font-semibold">Debug Info: View Raw API Response</span>
              <span className="text-xs bg-purple-500/20 px-2 py-1 rounded-full">
                {debugExpanded ? 'Hide' : 'Click to expand'}
              </span>
            </button>
            
            {debugExpanded && (
              <div className="mt-4 p-4 bg-black/60 rounded-xl border border-green-500/20">
                <div className="text-green-400 font-mono text-sm whitespace-pre-wrap max-h-64 overflow-auto">
                  {rawResponse ? JSON.stringify(rawResponse, null, 2) : 'null'}
                </div>
                <p className="text-green-300 text-xs mt-2 font-medium">
                  This shows exactly what your API is returning so we can fix data mapping issues
                </p>
              </div>
            )}
          </div>
        </div>

        {/* Filters Section */}
        <div className="max-w-7xl mx-auto mb-8">
          <div className="bg-black/40 backdrop-blur-sm border border-purple-500/20 rounded-2xl p-8 shadow-2xl">
              <div className="flex items-center gap-3 mb-6">
              <span className="text-purple-400 text-2xl">🔍</span>
              <h2 className="text-2xl font-bold text-white">Filter Matchups</h2>
            </div>
            
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
              {/* Position Filter */}
              <div className="space-y-2">
                <label className="text-purple-300 font-semibold text-sm uppercase tracking-wide">Position</label>
                <select 
                  value={selectedPosition} 
                  onChange={(e) => setSelectedPosition(e.target.value)}
                  className="w-full bg-black/60 border border-purple-500/30 text-white rounded-xl px-4 py-3 focus:border-purple-400 focus:ring-2 focus:ring-purple-400/20 transition-all hover:border-purple-400/50"
                >
                  {positions.map(pos => (
                    <option key={pos} value={pos} className="bg-slate-800">{pos}</option>
                  ))}
                </select>
              </div>

              {/* Team Filter */}
              <div className="space-y-2">
                <label className="text-purple-300 font-semibold text-sm uppercase tracking-wide">Team</label>
                <select 
                  value={selectedTeam} 
                  onChange={(e) => setSelectedTeam(e.target.value)}
                  className="w-full bg-black/60 border border-purple-500/30 text-white rounded-xl px-4 py-3 focus:border-purple-400 focus:ring-2 focus:ring-purple-400/20 transition-all hover:border-purple-400/50"
                >
                  {teams.map(team => (
                    <option key={team} value={team} className="bg-slate-800">{team}</option>
                  ))}
                </select>
              </div>

              {/* Defense Tier Filter */}
              <div className="space-y-2">
                <label className="text-purple-300 font-semibold text-sm uppercase tracking-wide">Defense Tier</label>
                <select 
                  value={selectedDefenseTier} 
                  onChange={(e) => setSelectedDefenseTier(e.target.value)}
                  className="w-full bg-black/60 border border-purple-500/30 text-white rounded-xl px-4 py-3 focus:border-purple-400 focus:ring-2 focus:ring-purple-400/20 transition-all hover:border-purple-400/50"
                >
                  {defenseTiers.map(tier => (
                    <option key={tier} value={tier} className="bg-slate-800">{tier}</option>
                  ))}
                </select>
              </div>

              {/* Situations Filter */}
              <div className="space-y-2">
                <label className="text-purple-300 font-semibold text-sm uppercase tracking-wide">Situations</label>
                <select 
                  value={selectedSituation} 
                  onChange={(e) => setSelectedSituation(e.target.value)}
                  className="w-full bg-black/60 border border-purple-500/30 text-white rounded-xl px-4 py-3 focus:border-purple-400 focus:ring-2 focus:ring-purple-400/20 transition-all hover:border-purple-400/50"
                >
                  {situations.map(situation => (
                    <option key={situation} value={situation} className="bg-slate-800">{situation}</option>
                  ))}
                </select>
              </div>
            </div>

            <div className="mt-6 flex justify-end">
              <button 
                onClick={clearAllFilters}
                className="px-6 py-3 bg-gradient-to-r from-red-500 to-pink-600 text-white rounded-xl font-semibold hover:from-red-600 hover:to-pink-700 transition-all duration-300 transform hover:scale-105 shadow-lg hover:shadow-red-500/25"
              >
                🔄 Clear All Filters
              </button>
            </div>
          </div>
        </div>

        {/* Results Section */}
        <div className="max-w-7xl mx-auto">
          {error && (
            <div className="mb-8 p-6 bg-red-500/10 backdrop-blur-sm border border-red-500/20 rounded-2xl shadow-2xl">
              <div className="flex items-center gap-3">
                <div className="p-2 bg-red-500/20 rounded-lg">
                  <span className="text-2xl">🎯</span>
                </div>
                <div>
                  <h3 className="text-red-400 font-bold text-lg">System Alert</h3>
                  <p className="text-red-300">{error}</p>
                </div>
              </div>
            </div>
          )}

          <div className="bg-black/40 backdrop-blur-sm border border-purple-500/20 rounded-2xl shadow-2xl overflow-hidden">
            {/* Performance Header */}
            <div className="bg-gradient-to-r from-purple-600/20 to-pink-600/20 p-8 border-b border-purple-500/20">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-4">
                  <div className="p-3 bg-gradient-to-r from-purple-600 to-pink-600 rounded-xl shadow-lg">
                    <span className="text-2xl">🏆</span>
                  </div>
                  <div>
                    <h2 className="text-3xl font-black text-white mb-2">Performance Leaderboard</h2>
                    <div className="flex items-center gap-4 text-purple-200">
                      <span className="font-semibold">{data.length} players found</span>
                      <span>•</span>
                      <span>Situational matchup analysis</span>
                    </div>
                  </div>
                </div>
                <div className="hidden md:flex items-center gap-6">
                  <div className="text-center">
                    <div className="text-2xl font-bold text-green-400">{data.length}</div>
                    <div className="text-xs text-purple-300 uppercase tracking-wide">Active Players</div>
                  </div>
                  <div className="text-center">
                    <div className="text-2xl font-bold text-blue-400">LIVE</div>
                    <div className="text-xs text-purple-300 uppercase tracking-wide">Data Feed</div>
                  </div>
                </div>
              </div>
            </div>

            {/* Table Header */}
            <div className="bg-black/60 px-8 py-4 border-b border-purple-500/10">
              <div className="grid grid-cols-8 gap-4 text-purple-300 text-sm font-bold uppercase tracking-wider">
                <div className="text-center">#</div>
                <div>Player</div>
                <div className="text-center">Team</div>
                <div className="text-center">Pos</div>
                <div className="text-center">Games</div>
                <div className="text-center">Total</div>
                <div className="text-center">Per Game</div>
                <div className="text-center">Def Tier</div>
              </div>
            </div>

            {/* Table Body */}
            <div className="divide-y divide-purple-500/10">
              {loading ? (
                <div className="p-12 text-center">
                  <div className="inline-flex items-center gap-4">
                    <div className="w-8 h-8 border-4 border-purple-500/30 border-t-purple-500 rounded-full animate-spin"></div>
                    <span className="text-purple-300 text-lg font-medium">Loading elite matchups...</span>
                  </div>
                </div>
              ) : data.length === 0 ? (
                <div className="p-12 text-center">
                  <div className="inline-flex flex-col items-center gap-4">
                    <div className="p-4 bg-purple-500/10 rounded-2xl">
                      <span className="text-4xl">🎯</span>
                    </div>
                    <div>
                      <h3 className="text-xl font-bold text-white mb-2">No Matchups Found</h3>
                      <p className="text-purple-300">Adjust your filters to find player matchups</p>
                    </div>
                  </div>
                </div>
              ) : (
                data.map((player, index) => (
                  <div key={`${player.player_name}-${index}`} 
                       className="group hover:bg-purple-500/5 transition-all duration-300 hover:scale-[1.01] hover:shadow-lg hover:shadow-purple-500/10">
                    <div className="grid grid-cols-8 gap-4 px-8 py-6 items-center">
                      {/* Rank */}
                      <div className="text-center">
                        <div className="inline-flex items-center justify-center w-10 h-10 bg-gradient-to-r from-purple-600 to-pink-600 rounded-full shadow-lg group-hover:shadow-purple-500/50 transition-all">
                          <span className="text-white font-bold">{index + 1}</span>
                        </div>
                      </div>
                      
                      {/* Player Name */}
                      <div>
                        <div className="font-bold text-white text-lg group-hover:text-purple-300 transition-colors">
                          {player.player_name}
                        </div>
                      </div>
                      
                      {/* Team */}
                      <div className="text-center">
                        <span className="inline-flex items-center px-3 py-1 bg-gradient-to-r from-blue-600/20 to-purple-600/20 rounded-full border border-blue-500/30 text-blue-300 font-bold text-sm">
                          {player.team}
                        </span>
                      </div>
                      
                      {/* Position */}
                      <div className="text-center">
                        <span className="inline-flex items-center px-3 py-1 bg-gradient-to-r from-green-600/20 to-emerald-600/20 rounded-full border border-green-500/30 text-green-300 font-bold text-sm">
                          {player.position}
                        </span>
                      </div>
                      
                      {/* Games */}
                      <div className="text-center">
                        <span className="text-white font-bold text-lg">{player.games}</span>
                      </div>
                      
                      {/* Total Yards */}
                      <div className="text-center">
                        <div className="flex flex-col items-center gap-1">
                          <span className="text-2xl font-black text-transparent bg-gradient-to-r from-yellow-400 to-orange-500 bg-clip-text">
                            {player.total_yards}
                          </span>
                          <div className="text-xs text-purple-400 uppercase tracking-wide">yards</div>
                        </div>
                      </div>
                      
                      {/* Per Game */}
                      <div className="text-center">
                        <div className="flex flex-col items-center gap-1">
                          <span className="text-xl font-bold text-cyan-400">
                            {(player.total_yards / player.games).toFixed(1)}
                          </span>
                          <div className="text-xs text-purple-400 uppercase tracking-wide">avg</div>
                        </div>
                      </div>
                      
                      {/* Defense Tier */}
                      <div className="text-center">
                        <span className={`inline-flex items-center px-3 py-2 bg-gradient-to-r ${getDefenseTierColor(player.defense_tier)} rounded-full text-white font-bold text-sm shadow-lg transform group-hover:scale-110 transition-all`}>
                          {getDefenseTierLabel(player.defense_tier)}
                        </span>
                      </div>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>

        {/* Development Notes */}
        <div className="max-w-7xl mx-auto mt-12">
          <div className="bg-black/40 backdrop-blur-sm border border-purple-500/20 rounded-2xl p-8 shadow-2xl">
            <div className="flex items-center gap-3 mb-6">
              <div className="p-2 bg-gradient-to-r from-orange-500 to-red-600 rounded-lg">
                <span className="text-white text-xl">🔧</span>
              </div>
              <h3 className="text-2xl font-bold text-white">Next Development Steps</h3>
            </div>
            
            <div className="grid md:grid-cols-2 gap-8">
              <div>
                <h4 className="text-purple-300 font-bold text-lg mb-4 flex items-center gap-2">
                  <span className="text-xl">🎯</span>
                  Data Issues to Fix:
                </h4>
                <ul className="space-y-3 text-purple-200">
                  <li className="flex items-start gap-3">
                    <div className="w-2 h-2 bg-red-400 rounded-full mt-2 flex-shrink-0"></div>
                    <span>Add team names to database/API response</span>
                  </li>
                  <li className="flex items-start gap-3">
                    <div className="w-2 h-2 bg-red-400 rounded-full mt-2 flex-shrink-0"></div>
                    <span>Fix total yards calculation (showing 0s)</span>
                  </li>
                  <li className="flex items-start gap-3">
                    <div className="w-2 h-2 bg-red-400 rounded-full mt-2 flex-shrink-0"></div>
                    <span>Add more situational contexts</span>
                  </li>
                  <li className="flex items-start gap-3">
                    <div className="w-2 h-2 bg-red-400 rounded-full mt-2 flex-shrink-0"></div>
                    <span>Implement weather data integration</span>
                  </li>
                </ul>
              </div>
              
              <div>
                <h4 className="text-purple-300 font-bold text-lg mb-4 flex items-center gap-2">
                  <span className="text-xl">⚡</span>
                  Features to Add:
                </h4>
                <ul className="space-y-3 text-purple-200">
                  <li className="flex items-start gap-3">
                    <div className="w-2 h-2 bg-green-400 rounded-full mt-2 flex-shrink-0"></div>
                    <span>WR vs CB specific matchups</span>
                  </li>
                  <li className="flex items-start gap-3">
                    <div className="w-2 h-2 bg-green-400 rounded-full mt-2 flex-shrink-0"></div>
                    <span>Defense-specific filtering</span>
                  </li>
                  <li className="flex items-start gap-3">
                    <div className="w-2 h-2 bg-green-400 rounded-full mt-2 flex-shrink-0"></div>
                    <span>Historical trend analysis</span>
                  </li>
                  <li className="flex items-start gap-3">
                    <div className="w-2 h-2 bg-green-400 rounded-full mt-2 flex-shrink-0"></div>
                    <span>Prop line suggestions</span>
                  </li>
                </ul>
              </div>
            </div>
          </div>
        </div>
      </div>

      <style jsx>{`
        .animation-delay-2000 {
          animation-delay: 2s;
        }
        .animation-delay-4000 {
          animation-delay: 4s;
        }
      `}</style>
    </div>
  );
};

export default NFL_SITUATIONAL_ANALYSIS;
