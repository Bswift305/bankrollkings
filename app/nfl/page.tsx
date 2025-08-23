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

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 mb-8">
        <Link 
          href="/nfl/situational" 
          className="bg-white rounded-lg shadow-md p-6 hover:shadow-lg transition-shadow border border-gray-200 hover:border-blue-300"
        >
          <div className="flex items-center mb-4">
            <div className="bg-blue-100 rounded-lg p-3">
              <span className="text-2xl">📊</span>
            </div>
            <h3 className="text-lg font-semibold text-gray-900 ml-3">
              Situational Analysis
            </h3>
          </div>
          <p className="text-gray-600">
            Player performance by game situation, weather, and defense tier
          </p>
        </Link>

        <Link 
          href="/nfl/props" 
          className="bg-white rounded-lg shadow-md p-6 hover:shadow-lg transition-shadow border border-gray-200 hover:border-green-300"
        >
          <div className="flex items-center mb-4">
            <div className="bg-green-100 rounded-lg p-3">
              <span className="text-2xl">🎯</span>
            </div>
            <h3 className="text-lg font-semibold text-gray-900 ml-3">
              Prop Betting Trends
            </h3>
          </div>
          <p className="text-gray-600">
            Historical prop hit rates and line movement analysis
          </p>
        </Link>

        <Link 
          href="/nfl/matchups" 
          className="bg-white rounded-lg shadow-md p-6 hover:shadow-lg transition-shadow border border-gray-200 hover:border-purple-300"
        >
          <div className="flex items-center mb-4">
            <di
