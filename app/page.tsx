'use client';

import React, { useState, useEffect } from 'react';

interface PlayerData {
  player_name: string;
  team: string;
  position: string;
  games: number;
  total_yards: number;
  defense_tier: string;
  per_game?: number;
}

interface RawPlayerData {
  player_id: string;
  full_name: string;
  position: string;
  season: number;
  category: string;
  def_tier: string;
  team_abbr: string;
  total_yards: number;
  games: number;
  per_game: number;
}

const NFL_SITUATIONAL_ANALYSIS = () => {
  const [data, setData] = useState<PlayerData[]>([]);
  const [rawData, setRawData] = useState<any[]>([]);
  const [viewMode, setViewMode] = useState<'aggregated' | 'situational'>('aggregated');
  const [sortBy, setSortBy] = useState<'games' | 'total_yards' | 'per_game'>('total_yards');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [debugExpanded, setDebugExpanded] = useState(false);
  const [rawResponse, setRawResponse] = useState(null);
  
  // Advanced Filter States
  const [selectedPosition, setSelectedPosition] = useState('All Positions');
  const [selectedTeam, setSelectedTeam] = useState('All Teams');
  const [selectedDefenseTier, setSelectedDefenseTier] = useState('All Defense Tiers');
  const [selectedSituation, setSelectedSituation] = useState('All Situations');
  const [selectedHomeAway, setSelectedHomeAway] = useState('All Games');
  const [selectedGameType, setSelectedGameType] = useState('All Games');
  const [selectedWeather, setSelectedWeather] = useState('All Weather');
  const [selectedYear, setSelectedYear] = useState('2024');
  const [selectedWeek, setSelectedWeek] = useState('All Weeks');
  const [selectedMonth, setSelectedMonth] = useState('All Months');
  const [selectedOpponent, setSelectedOpponent] = useState('All Opponents');
  const [selectedGameResult, setSelectedGameResult] = useState('All Results');
  const [selectedTimeOfDay, setSelectedTimeOfDay] = useState('All Times');
  const [selectedSurface, setSelectedSurface] = useState('All Surfaces');
  const [selectedTemperature, setSelectedTemperature] = useState('All Temps');
  const [selectedDivision, setSelectedDivision] = useState('All Divisions');
  const [selectedConference, setSelectedConference] = useState('All Conferences');
  const [minYards, setMinYards] = useState('');
  const [maxYards, setMaxYards] = useState('');
  const [minGames, setMinGames] = useState('');
  const [selectedInjuryStatus, setSelectedInjuryStatus] = useState('All Status');
  const [selectedRookieVet, setSelectedRookieVet] = useState('All Experience');

  // Comprehensive Filter Options
  const positions = ['All Positions', 'RB', 'WR', 'TE', 'QB', 'FB', 'K', 'DST'];
  const teams = [
    'All Teams', 'Arizona', 'Atlanta', 'Baltimore', 'Buffalo', 'Carolina', 'Chicago', 'Cincinnati', 
    'Cleveland', 'Dallas', 'Denver', 'Detroit', 'Green Bay', 'Houston', 'Indianapolis', 'Jacksonville',
    'Kansas City', 'Las Vegas', 'LA Chargers', 'LA Rams', 'Miami', 'Minnesota', 'New England',
    'New Orleans', 'NY Giants', 'NY Jets', 'Philadelphia', 'Pittsburgh', 'San Francisco', 'Seattle',
    'Tampa Bay', 'Tennessee', 'Washington'
  ];
  const defenseTiers = ['All Defense Tiers', '🔥 Elite (Top 5)', '✅ Good (6-15)', '📊 Average (16-25)', '📉 Poor (26-32)'];
  const situations = [
    'All Situations', '🎯 Red Zone (0-20)', '🥅 Goal Line (0-5)', '3️⃣ 3rd Down', '4️⃣ 4th Down', 
    '⏰ 2-Min Drill', '🏃 Hurry Up', '💪 Short Yardage', '🎬 Play Action', '🏈 RPO', 
    '🎯 Target Share', '📍 Slot Formation', '📍 Outside Formation', '🔄 Motion Pre-Snap'
  ];
  const homeAwayOptions = ['All Games', '🏠 Home', '✈️ Away', '🆚 Division Rival', '🌟 Conference'];
  const gameTypes = ['All Games', '🌙 Prime Time', '☀️ Regular', '🏆 Playoff', '🎭 Divisional', '⭐ Marquee'];
  const weatherOptions = [
    'All Weather', '🏟️ Dome', '☀️ Clear', '🌧️ Rain', '❄️ Snow', '💨 Windy (15+ mph)', 
    '🌡️ Hot (75°F+)', '🧊 Cold (32°F-)', '🌫️ Fog/Overcast'
  ];
  const years = ['2024', '2023', '2022', '2021', '2020', '2019'];
  const weeks = ['All Weeks', 'Week 1', 'Week 2', 'Week 3', 'Week 4', 'Week 5', 'Week 6', 'Week 7', 'Week 8', 'Week 9', 'Week 10', 'Week 11', 'Week 12', 'Week 13', 'Week 14', 'Week 15', 'Week 16', 'Week 17', 'Week 18', 'Wild Card', 'Divisional', 'Conference', 'Super Bowl'];
  const months = ['All Months', 'September', 'October', 'November', 'December', 'January', 'February'];
  const opponents = ['All Opponents', ...teams.slice(1)];
  const gameResults = ['All Results', '✅ Win', '❌ Loss', '🎯 Close Game (±7)', '💥 Blowout (15+)', '⚡ Overtime'];
  const timesOfDay = ['All Times', '🌅 Early (1:00 PM)', '🌞 Afternoon (4:00 PM)', '🌙 Prime Time (8:00+ PM)', '🌃 Late Night'];
  const surfaces = ['All Surfaces', '🌱 Natural Grass', '🏟️ Artificial Turf', '🏠 Retractable Roof'];
  const temperatures = ['All Temps', '🔥 Hot (75°F+)', '🌡️ Warm (60-74°F)', '❄️ Cold (32-59°F)', '🧊 Freezing (<32°F)'];
  const divisions = ['All Divisions', 'AFC East', 'AFC North', 'AFC South', 'AFC West', 'NFC East', 'NFC North', 'NFC South', 'NFC West'];
  const conferences = ['All Conferences', 'AFC', 'NFC'];
  const injuryStatus = ['All Status', '✅ Healthy', '🟡 Questionable', '🟠 Doubtful', '❌ Out', '🔄 Return from IR'];
  const experience = ['All Experience', '🌟 Rookie', '👶 2nd Year', '💪 Veteran (3-7)', '👑 Elite Vet (8+)'];

  // Data aggregation and sorting function
  const aggregatePlayerData = (rawData: any[]): PlayerData[] => {
    let processedData: PlayerData[];
    
    if (viewMode === 'situational') {
      // Show situational breakdown by defense tier
      processedData = rawData.map(row => ({
        player_name: row.full_name || row.player_name,
        team: row.team_abbr || row.team,
        position: row.position,
        games: row.games,
        total_yards: row.total_yards,
        defense_tier: row.def_tier,
        per_game: row.per_game
      }));
    } else {
      // Aggregate across defense tiers for each individual player
      const playerMap = new Map<string, PlayerData>();
      
      rawData.forEach(row => {
        const playerName = row.full_name || row.player_name;
        const teamName = row.team_abbr || row.team;
        const key = `${playerName}-${teamName}`;
        
        if (playerMap.has(key)) {
          const existing = playerMap.get(key)!;
          existing.total_yards += (row.total_yards || 0);
          existing.games += (row.games || 0);
        } else {
          playerMap.set(key, {
            player_name: playerName,
            team: teamName,
            position: row.position,
            games: row.games || 0,
            total_yards: row.total_yards || 0,
            defense_tier: 'season_total'
          });
        }
      });
      
      // Calculate per_game averages
      processedData = Array.from(playerMap.values())
        .filter(player => player.player_name && player.player_name !== '') // Remove entries with no names
        .map(player => ({
          ...player,
          per_game: player.games > 0 ? player.total_yards / player.games : 0
        }));
    }
    
    // Apply sorting
    return processedData.sort((a, b) => {
      let aValue, bValue;
      
      switch (sortBy) {
        case 'games':
          aValue = a.games;
          bValue = b.games;
          break;
        case 'per_game':
          aValue = a.per_game || 0;
          bValue = b.per_game || 0;
          break;
        case 'total_yards':
        default:
          aValue = a.total_yards;
          bValue = b.total_yards;
          break;
      }
      
      return sortOrder === 'desc' ? bValue - aValue : aValue - bValue;
    });
  };

  const handleSort = (column: 'games' | 'total_yards' | 'per_game') => {
    if (sortBy === column) {
      // Toggle sort order if same column
      setSortOrder(sortOrder === 'desc' ? 'asc' : 'desc');
    } else {
      // New column, default to desc
      setSortBy(column);
      setSortOrder('desc');
    }
  };

  useEffect(() => {
    fetchData();
  }, [
    selectedPosition, selectedTeam, selectedDefenseTier, selectedSituation, selectedHomeAway, 
    selectedGameType, selectedWeather, selectedYear, selectedWeek, selectedMonth, selectedOpponent,
    selectedGameResult, selectedTimeOfDay, selectedSurface, selectedTemperature, selectedDivision,
    selectedConference, minYards, maxYards, minGames, selectedInjuryStatus, selectedRookieVet
  ]);

  useEffect(() => {
    // Re-aggregate and sort data when view mode or sorting changes
    if (rawData.length > 0) {
      const aggregatedData = aggregatePlayerData(rawData);
      setData(aggregatedData);
    }
  }, [viewMode, rawData, sortBy, sortOrder]);

  const fetchData = async () => {
    setLoading(true);
    setError(null);
    
    try {
      const params = new URLSearchParams();
      
      // Basic filters
      if (selectedPosition !== 'All Positions') params.append('position', selectedPosition);
      if (selectedTeam !== 'All Teams') params.append('team', selectedTeam);
      if (selectedDefenseTier !== 'All Defense Tiers') {
        const tierMap: { [key: string]: string } = {
          '🔥 Elite (Top 5)': 'top10',
          '✅ Good (6-15)': 'good', 
          '📊 Average (16-25)': 'middle',
          '📉 Poor (26-32)': 'bottom10'
        };
        params.append('defense_tier', tierMap[selectedDefenseTier]);
      }
      
      // Advanced filters - for future implementation
      if (selectedYear !== '2024') params.append('year', selectedYear);
      
      // Increase limit significantly for more players
      params.append('limit', '200');
      
      const response = await fetch(`/api/situations?${params.toString()}`);
      const result = await response.json();
      
      setRawResponse(result);
      
      if (response.ok && result.rows) {
        setRawData(result.rows);
        const aggregatedData = aggregatePlayerData(result.rows);
        setData(aggregatedData);
      } else {
        setError(`HTTP ${response.status}: ${result.error || 'Unknown error'}`);
        setData([]);
        setRawData([]);
      }
    } catch (err) {
      setError(`Network error: ${err instanceof Error ? err.message : 'Unknown error'}`);
      setData([]);
      setRawData([]);
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
    setSelectedYear('2024');
    setSelectedWeek('All Weeks');
    setSelectedMonth('All Months');
    setSelectedOpponent('All Opponents');
    setSelectedGameResult('All Results');
    setSelectedTimeOfDay('All Times');
    setSelectedSurface('All Surfaces');
    setSelectedTemperature('All Temps');
    setSelectedDivision('All Divisions');
    setSelectedConference('All Conferences');
    setMinYards('');
    setMaxYards('');
    setMinGames('');
    setSelectedInjuryStatus('All Status');
    setSelectedRookieVet('All Experience');
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

        {/* Advanced Filters Section */}
        <div className="max-w-7xl mx-auto mb-8">
          <div className="bg-black/40 backdrop-blur-sm border border-purple-500/20 rounded-2xl p-8 shadow-2xl">
            <div className="flex items-center justify-between mb-8">
              <div className="flex items-center gap-3">
                <span className="text-purple-400 text-2xl">🔍</span>
                <h2 className="text-3xl font-bold text-white">Advanced Research Filters</h2>
              </div>
              <button 
                onClick={clearAllFilters}
                className="px-6 py-3 bg-gradient-to-r from-red-500 to-pink-600 text-white rounded-xl font-semibold hover:from-red-600 hover:to-pink-700 transition-all duration-300 transform hover:scale-105 shadow-lg hover:shadow-red-500/25"
              >
                🔄 Clear All Filters
              </button>
            </div>
            
            {/* Primary Filters Row */}
            <div className="mb-8">
              <h3 className="text-purple-300 font-bold text-lg mb-4 flex items-center gap-2">
                <span className="text-xl">🎯</span>
                Core Filters
              </h3>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
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
            </div>

            {/* Temporal Filters Row */}
            <div className="mb-8">
              <h3 className="text-purple-300 font-bold text-lg mb-4 flex items-center gap-2">
                <span className="text-xl">📅</span>
                Time & Schedule Filters
              </h3>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
                <div className="space-y-2">
                  <label className="text-purple-300 font-semibold text-sm uppercase tracking-wide">Year</label>
                  <select 
                    value={selectedYear} 
                    onChange={(e) => setSelectedYear(e.target.value)}
                    className="w-full bg-black/60 border border-purple-500/30 text-white rounded-xl px-4 py-3 focus:border-purple-400 focus:ring-2 focus:ring-purple-400/20 transition-all hover:border-purple-400/50"
                  >
                    {years.map(year => (
                      <option key={year} value={year} className="bg-slate-800">{year}</option>
                    ))}
                  </select>
                </div>

                <div className="space-y-2">
                  <label className="text-purple-300 font-semibold text-sm uppercase tracking-wide">Week</label>
                  <select 
                    value={selectedWeek} 
                    onChange={(e) => setSelectedWeek(e.target.value)}
                    className="w-full bg-black/60 border border-purple-500/30 text-white rounded-xl px-4 py-3 focus:border-purple-400 focus:ring-2 focus:ring-purple-400/20 transition-all hover:border-purple-400/50"
                  >
                    {weeks.map(week => (
                      <option key={week} value={week} className="bg-slate-800">{week}</option>
                    ))}
                  </select>
                </div>

                <div className="space-y-2">
                  <label className="text-purple-300 font-semibold text-sm uppercase tracking-wide">Month</label>
                  <select 
                    value={selectedMonth} 
                    onChange={(e) => setSelectedMonth(e.target.value)}
                    className="w-full bg-black/60 border border-purple-500/30 text-white rounded-xl px-4 py-3 focus:border-purple-400 focus:ring-2 focus:ring-purple-400/20 transition-all hover:border-purple-400/50"
                  >
                    {months.map(month => (
                      <option key={month} value={month} className="bg-slate-800">{month}</option>
                    ))}
                  </select>
                </div>

                <div className="space-y-2">
                  <label className="text-purple-300 font-semibold text-sm uppercase tracking-wide">Time of Day</label>
                  <select 
                    value={selectedTimeOfDay} 
                    onChange={(e) => setSelectedTimeOfDay(e.target.value)}
                    className="w-full bg-black/60 border border-purple-500/30 text-white rounded-xl px-4 py-3 focus:border-purple-400 focus:ring-2 focus:ring-purple-400/20 transition-all hover:border-purple-400/50"
                  >
                    {timesOfDay.map(time => (
                      <option key={time} value={time} className="bg-slate-800">{time}</option>
                    ))}
                  </select>
                </div>
              </div>
            </div>

            {/* Game Context Filters Row */}
            <div className="mb-8">
              <h3 className="text-purple-300 font-bold text-lg mb-4 flex items-center gap-2">
                <span className="text-xl">🏈</span>
                Game Context Filters
              </h3>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
                <div className="space-y-2">
                  <label className="text-purple-300 font-semibold text-sm uppercase tracking-wide">Home/Away</label>
                  <select 
                    value={selectedHomeAway} 
                    onChange={(e) => setSelectedHomeAway(e.target.value)}
                    className="w-full bg-black/60 border border-purple-500/30 text-white rounded-xl px-4 py-3 focus:border-purple-400 focus:ring-2 focus:ring-purple-400/20 transition-all hover:border-purple-400/50"
                  >
                    {homeAwayOptions.map(option => (
                      <option key={option} value={option} className="bg-slate-800">{option}</option>
                    ))}
                  </select>
                </div>

                <div className="space-y-2">
                  <label className="text-purple-300 font-semibold text-sm uppercase tracking-wide">Game Type</label>
                  <select 
                    value={selectedGameType} 
                    onChange={(e) => setSelectedGameType(e.target.value)}
                    className="w-full bg-black/60 border border-purple-500/30 text-white rounded-xl px-4 py-3 focus:border-purple-400 focus:ring-2 focus:ring-purple-400/20 transition-all hover:border-purple-400/50"
                  >
                    {gameTypes.map(type => (
                      <option key={type} value={type} className="bg-slate-800">{type}</option>
                    ))}
                  </select>
                </div>

                <div className="space-y-2">
                  <label className="text-purple-300 font-semibold text-sm uppercase tracking-wide">Opponent</label>
                  <select 
                    value={selectedOpponent} 
                    onChange={(e) => setSelectedOpponent(e.target.value)}
                    className="w-full bg-black/60 border border-purple-500/30 text-white rounded-xl px-4 py-3 focus:border-purple-400 focus:ring-2 focus:ring-purple-400/20 transition-all hover:border-purple-400/50"
                  >
                    {opponents.map(opp => (
                      <option key={opp} value={opp} className="bg-slate-800">{opp}</option>
                    ))}
                  </select>
                </div>

                <div className="space-y-2">
                  <label className="text-purple-300 font-semibold text-sm uppercase tracking-wide">Game Result</label>
                  <select 
                    value={selectedGameResult} 
                    onChange={(e) => setSelectedGameResult(e.target.value)}
                    className="w-full bg-black/60 border border-purple-500/30 text-white rounded-xl px-4 py-3 focus:border-purple-400 focus:ring-2 focus:ring-purple-400/20 transition-all hover:border-purple-400/50"
                  >
                    {gameResults.map(result => (
                      <option key={result} value={result} className="bg-slate-800">{result}</option>
                    ))}
                  </select>
                </div>
              </div>
            </div>

            {/* Environmental Filters Row */}
            <div className="mb-8">
              <h3 className="text-purple-300 font-bold text-lg mb-4 flex items-center gap-2">
                <span className="text-xl">🌤️</span>
                Environmental Filters
              </h3>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
                <div className="space-y-2">
                  <label className="text-purple-300 font-semibold text-sm uppercase tracking-wide">Weather</label>
                  <select 
                    value={selectedWeather} 
                    onChange={(e) => setSelectedWeather(e.target.value)}
                    className="w-full bg-black/60 border border-purple-500/30 text-white rounded-xl px-4 py-3 focus:border-purple-400 focus:ring-2 focus:ring-purple-400/20 transition-all hover:border-purple-400/50"
                  >
                    {weatherOptions.map(weather => (
                      <option key={weather} value={weather} className="bg-slate-800">{weather}</option>
                    ))}
                  </select>
                </div>

                <div className="space-y-2">
                  <label className="text-purple-300 font-semibold text-sm uppercase tracking-wide">Surface</label>
                  <select 
                    value={selectedSurface} 
                    onChange={(e) => setSelectedSurface(e.target.value)}
                    className="w-full bg-black/60 border border-purple-500/30 text-white rounded-xl px-4 py-3 focus:border-purple-400 focus:ring-2 focus:ring-purple-400/20 transition-all hover:border-purple-400/50"
                  >
                    {surfaces.map(surface => (
                      <option key={surface} value={surface} className="bg-slate-800">{surface}</option>
                    ))}
                  </select>
                </div>

                <div className="space-y-2">
                  <label className="text-purple-300 font-semibold text-sm uppercase tracking-wide">Temperature</label>
                  <select 
                    value={selectedTemperature} 
                    onChange={(e) => setSelectedTemperature(e.target.value)}
                    className="w-full bg-black/60 border border-purple-500/30 text-white rounded-xl px-4 py-3 focus:border-purple-400 focus:ring-2 focus:ring-purple-400/20 transition-all hover:border-purple-400/50"
                  >
                    {temperatures.map(temp => (
                      <option key={temp} value={temp} className="bg-slate-800">{temp}</option>
                    ))}
                  </select>
                </div>

                <div className="space-y-2">
                  <label className="text-purple-300 font-semibold text-sm uppercase tracking-wide">Division</label>
                  <select 
                    value={selectedDivision} 
                    onChange={(e) => setSelectedDivision(e.target.value)}
                    className="w-full bg-black/60 border border-purple-500/30 text-white rounded-xl px-4 py-3 focus:border-purple-400 focus:ring-2 focus:ring-purple-400/20 transition-all hover:border-purple-400/50"
                  >
                    {divisions.map(division => (
                      <option key={division} value={division} className="bg-slate-800">{division}</option>
                    ))}
                  </select>
                </div>
              </div>
            </div>

            {/* Advanced Metrics Filters Row */}
            <div className="mb-8">
              <h3 className="text-purple-300 font-bold text-lg mb-4 flex items-center gap-2">
                <span className="text-xl">📊</span>
                Advanced Metrics & Player Status
              </h3>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
                <div className="space-y-2">
                  <label className="text-purple-300 font-semibold text-sm uppercase tracking-wide">Conference</label>
                  <select 
                    value={selectedConference} 
                    onChange={(e) => setSelectedConference(e.target.value)}
                    className="w-full bg-black/60 border border-purple-500/30 text-white rounded-xl px-4 py-3 focus:border-purple-400 focus:ring-2 focus:ring-purple-400/20 transition-all hover:border-purple-400/50"
                  >
                    {conferences.map(conf => (
                      <option key={conf} value={conf} className="bg-slate-800">{conf}</option>
                    ))}
                  </select>
                </div>

                <div className="space-y-2">
                  <label className="text-purple-300 font-semibold text-sm uppercase tracking-wide">Injury Status</label>
                  <select 
                    value={selectedInjuryStatus} 
                    onChange={(e) => setSelectedInjuryStatus(e.target.value)}
                    className="w-full bg-black/60 border border-purple-500/30 text-white rounded-xl px-4 py-3 focus:border-purple-400 focus:ring-2 focus:ring-purple-400/20 transition-all hover:border-purple-400/50"
                  >
                    {injuryStatus.map(status => (
                      <option key={status} value={status} className="bg-slate-800">{status}</option>
                    ))}
                  </select>
                </div>

                <div className="space-y-2">
                  <label className="text-purple-300 font-semibold text-sm uppercase tracking-wide">Experience</label>
                  <select 
                    value={selectedRookieVet} 
                    onChange={(e) => setSelectedRookieVet(e.target.value)}
                    className="w-full bg-black/60 border border-purple-500/30 text-white rounded-xl px-4 py-3 focus:border-purple-400 focus:ring-2 focus:ring-purple-400/20 transition-all hover:border-purple-400/50"
                  >
                    {experience.map(exp => (
                      <option key={exp} value={exp} className="bg-slate-800">{exp}</option>
                    ))}
                  </select>
                </div>
              </div>
            </div>

            {/* Range Filters Row */}
            <div>
              <h3 className="text-purple-300 font-bold text-lg mb-4 flex items-center gap-2">
                <span className="text-xl">🎯</span>
                Performance Range Filters
              </h3>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                <div className="space-y-2">
                  <label className="text-purple-300 font-semibold text-sm uppercase tracking-wide">Min Yards</label>
                  <input 
                    type="number" 
                    value={minYards} 
                    onChange={(e) => setMinYards(e.target.value)}
                    placeholder="e.g. 50"
                    className="w-full bg-black/60 border border-purple-500/30 text-white rounded-xl px-4 py-3 focus:border-purple-400 focus:ring-2 focus:ring-purple-400/20 transition-all hover:border-purple-400/50 placeholder-purple-400/50"
                  />
                </div>

                <div className="space-y-2">
                  <label className="text-purple-300 font-semibold text-sm uppercase tracking-wide">Max Yards</label>
                  <input 
                    type="number" 
                    value={maxYards} 
                    onChange={(e) => setMaxYards(e.target.value)}
                    placeholder="e.g. 200"
                    className="w-full bg-black/60 border border-purple-500/30 text-white rounded-xl px-4 py-3 focus:border-purple-400 focus:ring-2 focus:ring-purple-400/20 transition-all hover:border-purple-400/50 placeholder-purple-400/50"
                  />
                </div>

                <div className="space-y-2">
                  <label className="text-purple-300 font-semibold text-sm uppercase tracking-wide">Min Games</label>
                  <input 
                    type="number" 
                    value={minGames} 
                    onChange={(e) => setMinGames(e.target.value)}
                    placeholder="e.g. 3"
                    className="w-full bg-black/60 border border-purple-500/30 text-white rounded-xl px-4 py-3 focus:border-purple-400 focus:ring-2 focus:ring-purple-400/20 transition-all hover:border-purple-400/50 placeholder-purple-400/50"
                  />
                </div>
              </div>
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
                <div className="text-center">
                  <button 
                    onClick={() => handleSort('games')}
                    className="hover:text-white transition-colors flex items-center gap-1 mx-auto"
                  >
                    Games
                    {sortBy === 'games' && (
                      <span className="text-xs">{sortOrder === 'desc' ? '↓' : '↑'}</span>
                    )}
                  </button>
                </div>
                <div className="text-center">
                  <button 
                    onClick={() => handleSort('total_yards')}
                    className="hover:text-white transition-colors flex items-center gap-1 mx-auto"
                  >
                    Total
                    {sortBy === 'total_yards' && (
                      <span className="text-xs">{sortOrder === 'desc' ? '↓' : '↑'}</span>
                    )}
                  </button>
                </div>
                <div className="text-center">
                  <button 
                    onClick={() => handleSort('per_game')}
                    className="hover:text-white transition-colors flex items-center gap-1 mx-auto"
                  >
                    Per Game
                    {sortBy === 'per_game' && (
                      <span className="text-xs">{sortOrder === 'desc' ? '↓' : '↑'}</span>
                    )}
                  </button>
                </div>
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
                            {player.per_game ? player.per_game.toFixed(1) : (player.total_yards / player.games).toFixed(1)}
                          </span>
                          <div className="text-xs text-purple-400 uppercase tracking-wide">avg</div>
                        </div>
                      </div>
                      
                      {/* Defense Tier */}
                      <div className="text-center">
                        {viewMode === 'aggregated' ? (
                          <span className="inline-flex items-center px-3 py-2 bg-gradient-to-r from-purple-600/20 to-pink-600/20 rounded-full text-purple-300 font-bold text-sm border border-purple-500/30">
                            🏆 Season Total
                          </span>
                        ) : (
                          <span className={`inline-flex items-center px-3 py-2 bg-gradient-to-r ${getDefenseTierColor(player.defense_tier)} rounded-full text-white font-bold text-sm shadow-lg transform group-hover:scale-110 transition-all`}>
                            {getDefenseTierLabel(player.defense_tier)}
                          </span>
                        )}
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
              <h3 className="text-2xl font-bold text-white">Advanced Filter Integration</h3>
            </div>
            
            <div className="grid md:grid-cols-2 gap-8">
              <div>
                <h4 className="text-purple-300 font-bold text-lg mb-4 flex items-center gap-2">
                  <span className="text-xl">🎯</span>
                  Next API Enhancements:
                </h4>
                <ul className="space-y-3 text-purple-200">
                  <li className="flex items-start gap-3">
                    <div className="w-2 h-2 bg-yellow-400 rounded-full mt-2 flex-shrink-0"></div>
                    <span>Add year/week/month filtering to backend</span>
                  </li>
                  <li className="flex items-start gap-3">
                    <div className="w-2 h-2 bg-yellow-400 rounded-full mt-2 flex-shrink-0"></div>
                    <span>Implement weather/surface data integration</span>
                  </li>
                  <li className="flex items-start gap-3">
                    <div className="w-2 h-2 bg-yellow-400 rounded-full mt-2 flex-shrink-0"></div>
                    <span>Add opponent-specific matchup data</span>
                  </li>
                  <li className="flex items-start gap-3">
                    <div className="w-2 h-2 bg-yellow-400 rounded-full mt-2 flex-shrink-0"></div>
                    <span>Integrate injury status tracking</span>
                  </li>
                </ul>
              </div>
              
              <div>
                <h4 className="text-purple-300 font-bold text-lg mb-4 flex items-center gap-2">
                  <span className="text-xl">⚡</span>
                  Premium Features Ready:
                </h4>
                <ul className="space-y-3 text-purple-200">
                  <li className="flex items-start gap-3">
                    <div className="w-2 h-2 bg-green-400 rounded-full mt-2 flex-shrink-0"></div>
                    <span>Deep situational analysis (14 contexts)</span>
                  </li>
                  <li className="flex items-start gap-3">
                    <div className="w-2 h-2 bg-green-400 rounded-full mt-2 flex-shrink-0"></div>
                    <span>Environmental condition filtering</span>
                  </li>
                  <li className="flex items-start gap-3">
                    <div className="w-2 h-2 bg-green-400 rounded-full mt-2 flex-shrink-0"></div>
                    <span>Advanced performance range controls</span>
                  </li>
                  <li className="flex items-start gap-3">
                    <div className="w-2 h-2 bg-green-400 rounded-full mt-2 flex-shrink-0"></div>
                    <span>Professional betting platform UI</span>
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
