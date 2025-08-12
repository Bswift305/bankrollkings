import { createServerSupabase } from "@/lib/supabase/server";
import { getLimitFromSearchParams } from "@/lib/http/params";
import { orderOrFallback } from "@/lib/db/safeOrder";

type EventRow = Record<string, any>;

export async function listEvents(sp: URLSearchParams) {
  const limit = getLimitFromSearchParams(sp, 50, 200);
  const supabase = createServerSupabase();

  const base = supabase.from("events").select("*").limit(limit);
  const { data, error } = await orderOrFallback<EventRow>(
    base,
    ["event_time", "created_at", "updated_at", "id"]
  );
  if (error) throw new Error(error.message);
  return data;
}


