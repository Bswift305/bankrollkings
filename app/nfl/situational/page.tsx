'use client';

import { useState, useEffect } from 'react';

interface SituationalData {
  id: string;
  player_name: string;
  position: string;
  team: string;
  situation: string;
  total: number;
  attempts: number;
  avg_per_attempt: number;
  weather_condition?: string;
  home_away: 'HOME' | 'AWAY';
  prime_time: boolean;
  def_tier: string;
}

export default function NFLSituationalPage() {
  const [data, setData] = useState<SituationalData[]>([]);
  const [loading, setLoading] = useState(true);
  const [filters, setFilters] = useState({
    position: '',
    situation: '',
    defTier: '',
    homeAway: '',
    primeTime: ''
  });

  useEffect(() => {
    fetchSituationalData();
  }, [filters]);

  const fetchSituationalData = async () => {
    try {
      setLoading(true);
      const searchParams = new URLSearchParams();
      
      Object.entries(filters).forEach(([key, value]) => {
        if (value) searchParams.set(key, value);
      });

      const response = await fetch(`/api/situations/leaderboard?${searchParams.toString()}`);
      const result = await response.json();
      
      if (result.data) {
        setData(result.data);
      }
    } catch (error) {
      console.error('Failed to fetch situational data:', error);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="p-8 max-w-7xl mx-auto">
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-gray-900 mb-2">
          NFL Situational Analysis
        </h1>
        <p className="text-gray-600">
          Player performance breakdown by game situation, defense tier, and conditions
        </p>
      </div>

      {/* Filters */}
      <div className="bg-white rounded-lg shadow-md p-6 mb-8">
        <h2 className="text-lg font-semibold mb-4">Filters</h2>
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
          <select
            value={filters.position}
            onChange={(e) => setFilters(prev => ({ ...prev, position: e.target.value }))}
            className="border border-gray-300 rounded-md px-3 py-2"
          >
            <option value="">All Positions</option>
            <option value="RB">RB</option>
            <option value="WR">WR</option>
            <option value="TE">TE</option>
            <option value="QB">QB</option>
          </select>

          <select
            value={filters.situation}
            onChange={(e) => setFilters(prev => ({ ...prev, situation: e.target.value }))}
            className="border border-gray-300 rounded-md px-3 py-2"
          >
            <option value="">All Situations</option>
            <option value="RED_ZONE">Red Zone</option>
            <option value="THIRD_DOWN">3rd Down</option>
            <option value="GOAL_LINE">Goal Line</option>
            <option value="TWO_MINUTE">2-Minute Drill</option>
          </select>

          <select
            value={filters.defTier}
            onChange={(e) => setFilters(prev => ({ ...prev, defTier: e.target.value }))}
            className="border border-gray-300 rounded-md px-3 py-2"
          >
            <option value="">All Defense Tiers</option>
            <option value="elite">Elite</option>
            <option value="good">Good</option>
            <option value="average">Average</option>
            <option value="poor">Poor</option>
          </select>

          <select
            value={filters.homeAway}
            onChange={(e) => setFilters(prev => ({ ...prev, homeAway: e.target.value }))}
            className="border border-gray-300 rounded-md px-3 py-2"
          >
            <option value="">Home/Away</option>
            <option value="HOME">Home</option>
            <option value="AWAY">Away</option>
          </select>

          <select
            value={filters.primeTime}
            onChange={(e) => setFilters(prev => ({ ...prev, primeTime: e.target.value }))}
            className="border border-gray-300 rounded-md px-3 py-2"
          >
            <option value="">All Games</option>
            <option value="true">Prime Time</option>
            <option value="false">Regular Games</option>
          </select>
        </div>
      </div>

      {/* Results Table */}
      <div className="bg-white rounded-lg shadow-md overflow-hidden">
        <div className="px-6 py-4 border-b border-gray-200">
          <h2 className="text-lg font-semibold">Performance Leaderboard</h2>
        </div>
        
        {loading ? (
          <div className="p-8 text-center">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600 mx-auto"></div>
            <p className="mt-2 text-gray-600">Loading situational data...</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Player
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Position
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Team
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Total Yards
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Attempts
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Avg/Attempt
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Def Tier
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    H/A
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {data.length > 0 ? (
                  data.map((player) => (
                    <tr key={player.id} className="hover:bg-gray-50">
                      <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">
                        {player.player_name}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                        {player.position}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                        {player.team}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900 font-semibold">
                        {player.total}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                        {player.attempts}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                        {player.avg_per_attempt.toFixed(1)}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap">
                        <span className={`inline-flex px-2 py-1 text-xs font-semibold rounded-full ${
                          player.def_tier === 'elite' ? 'bg-red-100 text-red-800' :
                          player.def_tier === 'good' ? 'bg-yellow-100 text-yellow-800' :
                          player.def_tier === 'average' ? 'bg-blue-100 text-blue-800' :
                          'bg-green-100 text-green-800'
                        }`}>
                          {player.def_tier}
                        </span>
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                        {player.home_away}
                      </td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan={8} className="px-6 py-8 text-center text-gray-500">
                      No data available for current filters
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Quick Stats Summary */}
      {data.length > 0 && (
        <div className="mt-8 grid grid-cols-1 md:grid-cols-3 gap-6">
          <div className="bg-white rounded-lg shadow-md p-6">
            <h3 className="text-lg font-semibold text-gray-900 mb-2">Top Performer</h3>
            <p className="text-2xl font-bold text-blue-600">
              {data[0]?.player_name}
            </p>
            <p className="text-sm text-gray-600">
              {data[0]?.total} total yards
            </p>
          </div>
          
          <div className="bg-white rounded-lg shadow-md p-6">
            <h3 className="text-lg font-semibold text-gray-900 mb-2">Players Analyzed</h3>
            <p className="text-2xl font-bold text-green-600">
              {data.length}
            </p>
            <p className="text-sm text-gray-600">
              In current filter set
            </p>
          </div>

          <div className="bg-white rounded-lg shadow-md p-6">
            <h3 className="text-lg font-semibold text-gray-900 mb-2">Avg Performance</h3>
            <p className="text-2xl font-bold text-purple-600">
              {(data.reduce((sum, p) => sum + p.avg_per_attempt, 0) / data.length).toFixed(1)}
            </p>
            <p className="text-sm text-gray-600">
              Yards per attempt
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
