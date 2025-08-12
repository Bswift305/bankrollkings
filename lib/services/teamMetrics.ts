import { createServerSupabase } from "@/lib/supabase/server";
import { orderOrFallback } from "@/lib/db/safeOrder";

type TeamMetric = {
  team_id: string;
  redzone_pct: number | null;
  goal_line_td_pct: number | null;
  third_down_stop_pct: number | null;
};

// <-- this is the named export your route expects
export async function listTeamMetrics() {
  const supabase = createServerSupabase();

  const base = supabase
    .from("team_metrics") // TODO: match your schema/table
    .select("team_id, redzone_pct, goal_line_td_pct, third_down_stop_pct");

  const { data, error } = await orderOrFallback<TeamMetric>(base, ["team_id"]);
  if (error) throw new Error(error.message);
  return data;
}
