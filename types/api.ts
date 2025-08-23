export interface LeaderboardEntry {
  id: string;
  player_name: string;
  position: string;
  team: string;
  total: number; // Standardized field name
  total_yards?: number; // Keep for backward compatibility
  attempts: number;
  avg_per_attempt: number;
  category: string;
  def_tier: string;
  created_at: string;
  updated_at: string;
}

export interface LeaderboardResponse {
  data: LeaderboardEntry[];
  total: number;
  limit: number;
  offset: number;
  filters?: {
    category?: string;
    defTier?: string;
  };
}

export interface APIError {
  error: string;
  message?: string;
  details?: any;
}
