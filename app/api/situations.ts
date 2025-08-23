import { LeaderboardResponse, APIError } from '@/types/api';

interface LeaderboardParams {
  defCat?: string;
  tier?: string;
  limit?: number;
  offset?: number;
}

export async function getLeaderboard(
  params: LeaderboardParams = {}
): Promise<LeaderboardResponse> {
  const searchParams = new URLSearchParams();
  
  // Map parameters consistently
  if (params.defCat) searchParams.set('defCat', params.defCat);
  if (params.tier) searchParams.set('tier', params.tier);
  if (params.limit) searchParams.set('limit', params.limit.toString());
  if (params.offset) searchParams.set('offset', params.offset.toString());

  const response = await fetch(
    `/api/situations/leaderboard?${searchParams.toString()}`,
    {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
      },
    }
  );

  if (!response.ok) {
    const errorData: APIError = await response.json();
    throw new Error(errorData.error || 'Failed to fetch leaderboard');
  }

  return response.json();
}
