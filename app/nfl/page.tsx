'use client';

import Link from 'next/link';

export default function NFLPage() {
  return (
    <div className="p-8 max-w-7xl mx-auto">
      <div className="mb-8">
        <h1 className="text-4xl font-bold text-gray-900 mb-4">
          NFL Analysis Hub
        </h1>
        <p className="text-xl text-gray-600">
          Advanced prop betting insights and ATS analysis for the NFL
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        <Link 
          href="/nfl/situational" 
          className="bg-white rounded-lg shadow-md p-6 hover:shadow-lg transition-shadow"
        >
          <h3 className="text-lg font-semibold text-gray-900 mb-2">
            Situational Analysis
          </h3>
          <p className="text-gray-600">
            Player performance by game situation and defense tier
          </p>
        </Link>

        <div className="bg-gray-100 rounded-lg shadow-md p-6 opacity-75">
          <h3 className="text-lg font-semibold text-gray-600 mb-2">
            Prop Betting Trends
          </h3>
          <p className="text-gray-500">
            Coming soon - Historical prop hit rates and line movement
          </p>
        </div>

        <div className="bg-gray-100 rounded-lg shadow-md p-6 opacity-75">
          <h3 className="text-lg font-semibold text-gray-600 mb-2">
            Matchup Analysis
          </h3>
          <p className="text-gray-500">
            Coming soon - WR vs CB and RB vs defense breakdowns
          </p>
        </div>
      </div>
    </div>
  );
}
