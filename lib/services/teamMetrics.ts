import { orderOrFallback } from "@/lib/db/safeOrder";
// ...
const base = supabase.from("team_metrics").select("team_id, redzone_pct, goal_line_td_pct, third_down_stop_pct");
const { data, error } = await orderOrFallback(base, ["team_id"]);

