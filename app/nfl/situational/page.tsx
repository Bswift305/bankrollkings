'use client';

import { useState, useEffect } from 'react';

interface SituationalData {
  id: string;
  player_name: string;
  position: string;
  team: string;
  situation: string;
  total: number;
  total_yards?: number; // backup field
  attempts: number;
  avg_per_attempt: number;
  games: number;
  weather_condition?: string;
  home_away: 'HOME' | 'AWAY';
  prime_time: boolean;
  def_tier: string;
  opponent_team?: string;
  week?: number;
  season?: number;
}

interface Filters {
  position: string;
  situation: string;
  defTier: string;
  homeAway: string;
  primeTime: string;
  team: string;
  weather: string;
}

export default function NFLSituationalPage() {
  const [data, setData] = useState<SituationalData[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [rawApiResponse, setRawApiResponse] = useState<any>(null); // Debug
  
  const [filters, setFilters] = useState({
  position: 'WR',
  category: 'pass',
  defTier: '',
  homeAway: '',
  primeTime: '',
  season: '2024',
  team: '',        // ✅ Add this line
  weather: ''      // ✅ Add this line too
});

  useEffect(() => {
    fetchSituationalData();
  }, [filters]);

  const fetchSituationalData = async () => {
    try {
      setLoading(true);
      setError(null);
      
      const searchParams = new URLSearchParams();
      
      // Map frontend filters to API parameters
      Object.entries(filters).forEach(([key, value]) => {
        if (value) {
          // Map some parameters for backend compatibility
          if (key === 'defTier') {
            searchParams.set('tier', value);
          } else if (key === 'position') {
            searchParams.set('defCat', value); // Assuming this maps to position
          } else {
            searchParams.set(key, value);
          }
        }
      });

      console.log('Fetching with params:', searchParams.toString());
      
      const response = await fetch(`/api/situations/leaderboard?${searchParams.toString()}`);
      
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }
      
      const result = await response.json();
      console.log('Raw API Response:', result); // Debug log
      
      setRawApiResponse(result); // Store for debugging
      
      if (result.data && Array.isArray(result.data)) {
        // Transform data to ensure we have the right fields
        const transformedData = result.data.map((item: any) => ({
          ...item,
          total: item.total || item.total_yards || 0,
          team: item.team || item.team_abbr || item.team_name || 'N/A',
          games: item.games || item.game_count || 1,
          avg_per_attempt: item.avg_per_attempt || (item.total / Math.max(item.attempts, 1)) || 0
        }));
        
        setData(transformedData);
      } else {
        setData([]);
      }
    } catch (error) {
      console.error('Failed to fetch situational data:', error);
      setError(error instanceof Error ? error.message : 'Failed to fetch data');
    } finally {
      setLoading(false);
    }
  };

  // Debug component - remove in production
  const DebugPanel = () => (
    <div className="bg-gray-100 rounded-lg p-4 mb-6">
      <h3 className="font-semibold mb-2">🔍 Debug Info:</h3>
      <details>
        <summary className="cursor-pointer text-sm text-blue-600 hover:text-blue-800">
          View Raw API Response (Click to expand)
        </summary>
        <pre className="mt-2 text-xs bg-white p-3 rounded overflow-auto max-h-40 border">
          {JSON.stringify(rawApiResponse, null, 2)}
        </pre>
      </details>
      <p className="text-xs text-gray-600 mt-2">
        This shows exactly what your API is returning so we can fix data mapping issues
      </p>
    </div>
  );

  return (
    <div className="p-8 max-w-7xl mx-auto">
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-gray-900 mb-2">
          NFL Situational Analysis
        </h1>
        <p className="text-gray-600">
          Advanced player vs defense matchup analysis for prop betting insights
        </p>
      </div>

      {/* Debug Panel - helps us see what data we're getting */}
      <DebugPanel />

      {/* Enhanced Filters */}
      <div className="bg-white rounded-lg shadow-md p-6 mb-8">
        <h2 className="text-lg font-semibold mb-4">🔍 Filter Matchups</h2>
        
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-4">
          {/* Position Filter */}
          <select
            value={filters.position}
            onChange={(e) => setFilters(prev => ({ ...prev, position: e.target.value }))}
            className="border border-gray-300 rounded-md px-3 py-2 text-sm"
          >
            <option value="">All Positions</option>
            <option value="RB">RB</option>
            <option value="WR">WR</option>
            <option value="TE">TE</option>
            <option value="QB">QB</option>
          </select>

          {/* Team Filter */}
          <select
            value={filters.team}
            onChange={(e) => setFilters(prev => ({ ...prev, team: e.target.value }))}
            className="border border-gray-300 rounded-md px-3 py-2 text-sm"
          >
            <option value="">All Teams</option>
            <option value="BUF">Buffalo</option>
            <option value="MIA">Miami</option>
            <option value="NE">New England</option>
            <option value="NYJ">NY Jets</option>
            <option value="BAL">Baltimore</option>
            <option value="CIN">Cincinnati</option>
            <option value="CLE">Cleveland</option>
            <option value="PIT">Pittsburgh</option>
            <option value="HOU">Houston</option>
            <option value="IND">Indianapolis</option>
            <option value="JAX">Jacksonville</option>
            <option value="TEN">Tennessee</option>
            <option value="DEN">Denver</option>
            <option value="KC">Kansas City</option>
            <option value="LV">Las Vegas</option>
            <option value="LAC">LA Chargers</option>
          </select>

          {/* Defense Tier Filter */}
          <select
            value={filters.defTier}
            onChange={(e) => setFilters(prev => ({ ...prev, defTier: e.target.value }))}
            className="border border-gray-300 rounded-md px-3 py-2 text-sm"
          >
            <option value="">All Defense Tiers</option>
            <option value="elite">🔥 Elite</option>
            <option value="good">✅ Good</option>
            <option value="average">📊 Average</option>
            <option value="poor">📉 Poor</option>
          </select>

          {/* Situation Filter */}
          <select
            value={filters.situation}
            onChange={(e) => setFilters(prev => ({ ...prev, situation: e.target.value }))}
            className="border border-gray-300 rounded-md px-3 py-2 text-sm"
          >
            <option value="">All Situations</option>
            <option value="RED_ZONE">🎯 Red Zone</option>
            <option value="THIRD_DOWN">3️⃣ 3rd Down</option>
            <option value="GOAL_LINE">🏁 Goal Line</option>
            <option value="TWO_MINUTE">⏰ 2-Min Drill</option>
            <option value="FOURTH_DOWN">4️⃣ 4th Down</option>
          </select>

          {/* Home/Away Filter */}
          <select
            value={filters.homeAway}
            onChange={(e) => setFilters(prev => ({ ...prev, homeAway: e.target.value }))}
            className="border border-gray-300 rounded-md px-3 py-2 text-sm"
          >
            <option value="">🏠 Home/Away</option>
            <option value="HOME">🏠 Home</option>
            <option value="AWAY">✈️ Away</option>
          </select>

          {/* Prime Time Filter */}
          <select
            value={filters.primeTime}
            onChange={(e) => setFilters(prev => ({ ...prev, primeTime: e.target.value }))}
            className="border border-gray-300 rounded-md px-3 py-2 text-sm"
          >
            <option value="">All Games</option>
            <option value="true">🌙 Prime Time</option>
            <option value="false">☀️ Regular</option>
          </select>

          {/* Weather Filter */}
          <select
            value={filters.weather}
            onChange={(e) => setFilters(prev => ({ ...prev, weather: e.target.value }))}
            className="border border-gray-300 rounded-md px-3 py-2 text-sm"
          >
            <option value="">🌤️ All Weather</option>
            <option value="DOME">🏟️ Dome</option>
            <option value="CLEAR">☀️ Clear</option>
            <option value="RAIN">🌧️ Rain</option>
            <option value="SNOW">❄️ Snow</option>
            <option value="WIND">💨 Windy</option>
          </select>
        </div>

        <button
          onClick={() => setFilters({
            position: '', situation: '', defTier: '', homeAway: '', 
            primeTime: '', team: '', weather: ''
          })}
          className="mt-4 px-4 py-2 bg-gray-200 text-gray-700 rounded-md hover:bg-gray-300 text-sm"
        >
          🔄 Clear All Filters
        </button>
      </div>

      {/* Error Display */}
      {error && (
        <div className="bg-red-50 border border-red-200 rounded-md p-4 mb-6">
          <p className="text-red-600">❌ Error: {error}</p>
        </div>
      )}

      {/* Results Table */}
      <div className="bg-white rounded-lg shadow-md overflow-hidden">
        <div className="px-6 py-4 border-b border-gray-200 bg-gray-50">
          <h2 className="text-lg font-semibold">📊 Performance Leaderboard</h2>
          <p className="text-sm text-gray-600 mt-1">
            {data.length} players found • Situational matchup analysis
          </p>
        </div>
        
        {loading ? (
          <div className="p-8 text-center">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600 mx-auto"></div>
            <p className="mt-2 text-gray-600">Loading matchup data...</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    #
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Player
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Team
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Pos
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Games
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Total
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Per Game
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Def Tier
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    H/A
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {data.length > 0 ? (
                  data.map((player, index) => (
                    <tr key={player.id || index} className="hover:bg-gray-50">
                      <td className="px-4 py-4 whitespace-nowrap text-sm text-gray-500">
                        {index + 1}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap">
                        <div className="text-sm font-medium text-gray-900">
                          {player.player_name}
                        </div>
                        <div className="text-xs text-gray-500">
                          vs {player.def_tier} DEF
                        </div>
                      </td>
                      <td className="px-4 py-4 whitespace-nowrap">
                        <span className="inline-flex px-2 py-1 text-xs font-semibold rounded bg-blue-100 text-blue-800">
                          {player.team || 'N/A'}
                        </span>
                      </td>
                      <td className="px-4 py-4 whitespace-nowrap text-sm text-gray-500">
                        {player.position}
                      </td>
                      <td className="px-4 py-4 whitespace-nowrap text-sm text-gray-900">
                        {player.games || 1}
                      </td>
                      <td className="px-4 py-4 whitespace-nowrap text-sm text-gray-900 font-semibold">
                        {player.total || 0}
                      </td>
                      <td className="px-4 py-4 whitespace-nowrap text-sm text-gray-900">
                        {((player.total || 0) / Math.max(player.games || 1, 1)).toFixed(1)}
                      </td>
                      <td className="px-4 py-4 whitespace-nowrap">
                        <span className={`inline-flex px-2 py-1 text-xs font-semibold rounded-full ${
                          player.def_tier === 'elite' ? 'bg-red-100 text-red-800' :
                          player.def_tier === 'good' ? 'bg-yellow-100 text-yellow-800' :
                          player.def_tier === 'average' ? 'bg-blue-100 text-blue-800' :
                          'bg-green-100 text-green-800'
                        }`}>
                          {player.def_tier}
                        </span>
                      </td>
                      <td className="px-4 py-4 whitespace-nowrap text-sm text-gray-500">
                        {player.home_away === 'HOME' ? '🏠' : player.home_away === 'AWAY' ? '✈️' : '-'}
                      </td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan={9} className="px-6 py-8 text-center text-gray-500">
                      {loading ? 'Loading...' : 'No data available for current filters'}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Debug Panel - helps us see what data we're getting */}
      <div className="bg-gray-100 rounded-lg p-4 mb-6">
        <h3 className="font-semibold mb-2">🔍 Debug Info:</h3>
        <details>
          <summary className="cursor-pointer text-sm text-blue-600 hover:text-blue-800">
            View Raw API Response (Click to expand)
          </summary>
          <pre className="mt-2 text-xs bg-white p-3 rounded overflow-auto max-h-40 border">
            {JSON.stringify(rawApiResponse, null, 2)}
          </pre>
        </details>
        <p className="text-xs text-gray-600 mt-2">
          This shows exactly what your API is returning so we can fix data mapping issues
        </p>
      </div>

      {/* Enhanced Quick Stats */}
      {data.length > 0 && (
        <div className="mt-8 grid grid-cols-1 md:grid-cols-4 gap-6">
          <div className="bg-white rounded-lg shadow-md p-6 border-l-4 border-blue-500">
            <h3 className="text-sm font-medium text-gray-600 mb-1">TOP PERFORMER</h3>
            <p className="text-xl font-bold text-blue-600">
              {data[0]?.player_name}
            </p>
            <p className="text-sm text-gray-500">
              {data[0]?.total} total yards • {data[0]?.team}
            </p>
          </div>
          
          <div className="bg-white rounded-lg shadow-md p-6 border-l-4 border-green-500">
            <h3 className="text-sm font-medium text-gray-600 mb-1">PLAYERS ANALYZED</h3>
            <p className="text-xl font-bold text-green-600">
              {data.length}
            </p>
            <p className="text-sm text-gray-500">
              In current filter set
            </p>
          </div>

          <div className="bg-white rounded-lg shadow-md p-6 border-l-4 border-purple-500">
            <h3 className="text-sm font-medium text-gray-600 mb-1">AVG PERFORMANCE</h3>
            <p className="text-xl font-bold text-purple-600">
              {data.length > 0 ? 
                (data.reduce((sum, p) => sum + (p.total || 0), 0) / data.length).toFixed(1) : 
                '0.0'
              }
            </p>
            <p className="text-sm text-gray-500">
              Yards per game
            </p>
          </div>

          <div className="bg-white rounded-lg shadow-md p-6 border-l-4 border-orange-500">
            <h3 className="text-sm font-medium text-gray-600 mb-1">BEST MATCHUP</h3>
            <p className="text-xl font-bold text-orange-600">
              vs {data.find(p => p.total && p.total > 0)?.def_tier || 'N/A'}
            </p>
            <p className="text-sm text-gray-500">
              Defense tier performing
            </p>
          </div>
        </div>
      )}

      {/* Action Items for Next Steps */}
      <div className="mt-8 bg-yellow-50 border border-yellow-200 rounded-lg p-6">
        <h3 className="text-lg font-semibold text-yellow-800 mb-3">🚧 Next Development Steps</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
          <div>
            <h4 className="font-medium text-yellow-700 mb-2">Data Issues to Fix:</h4>
            <ul className="space-y-1 text-yellow-600">
              <li>• Add team names to database/API response</li>
              <li>• Fix total yards calculation (showing 0s)</li>
              <li>• Add more situational contexts</li>
              <li>• Implement weather data integration</li>
            </ul>
          </div>
          <div>
            <h4 className="font-medium text-yellow-700 mb-2">Features to Add:</h4>
            <ul className="space-y-1 text-yellow-600">
              <li>• WR vs CB specific matchups</li>
              <li>• Defense-specific filtering</li>
              <li>• Historical trend analysis</li>
              <li>• Prop line suggestions</li>
            </ul>
          </div>
        </div>
      </div>
    </div>
  );
}
