import { createServerSupabase } from "@/lib/supabase/server";
import { getLimitFromSearchParams } from "@/lib/http/params";

type EventRow = Record<string, any>; // adjust to your schema

export async function listEvents(sp: URLSearchParams) {
  const limit = getLimitFromSearchParams(sp, 50, 200);
  const supabase = createServerSupabase();

  // TODO: replace "events" and selected columns with your actual schema
  const { data, error } = await supabase
    .from("events")
    .select("*")
    .order("id", { ascending: false })
    .limit(limit);

  if (error) throw new Error(error.message);
  return (data ?? []) as EventRow[];
}
