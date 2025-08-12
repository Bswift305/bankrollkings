import { createServerSupabase } from "@/lib/supabase/server";

type TeamMetric = {
  team_id: string;
  redzone_pct: number | null;
  goal_line_td_pct: number | null;
  third_down_stop_pct: number | null;
};

export async function listTeamMetrics() {
  const supabase = createServerSupabase();
  const { data, error } = await supabase
    .from("team_metrics") // TODO: match your schema
    .select("team_id, redzone_pct, goal_line_td_pct, third_down_stop_pct")
    .order("team_id", { ascending: true });

  if (error) throw new Error(error.message);
  return (data ?? []) as TeamMetric[];
}
