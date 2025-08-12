// lib/services/consensusBets.ts
import { createServerSupabase } from "@/lib/supabase/server";

type ConsensusBet = Record<string, any>;

export async function listConsensusBets(opts: { limit?: number }) {
  const limit = Math.max(1, Math.min(opts.limit ?? 50, 200));
  const supabase = createServerSupabase();

  const { data, error } = await supabase
    .from("consensus_bets") // TODO: change to your actual table name if different
    .select("*")
    .limit(limit);

  if (error) throw new Error(error.message);
  return (data ?? []) as ConsensusBet[];
}
