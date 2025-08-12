import { supabaseServer } from "../utils/supabaseServer";

export type TeamMetric = {
  id: number;
  team?: string | null;
};

export async function getTeamMetrics(limit = 5) {
  const { data, error } = await supabaseServer.from("team_metrics").select("*").limit(limit);
  if (error) throw new Error(`getTeamMetrics failed: ${error.message}`);
  return data as TeamMetric[];
}
