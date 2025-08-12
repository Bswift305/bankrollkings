import { createServerSupabase } from "@/lib/supabase/server";
import { getLimitFromSearchParams } from "@/lib/http/params";

type EventRow = Record<string, any>; // adjust to your schema

export async function listEvents(sp: URLSearchParams) {
  const limit = getLimitFromSearchParams(sp, 50, 200);
  const supabase = createServerSupabase();

  const { data, error } = await supabase
    .from("events") // TODO: replace with your actual table name
    .select("*")
    .order("id", { ascending: false })
    .limit(limit);

  if (error) throw new Error(error.message);
  return (data ?? []) as EventRow[];
}
