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
        <h1 classN
