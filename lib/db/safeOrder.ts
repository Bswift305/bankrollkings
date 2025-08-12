// lib/db/safeOrder.ts
// Tries columns in order; if a column doesn't exist, it retries without failing the whole request.
export async function orderOrFallback<T = any>(
  baseQuery: any,                // Supabase query builder
  candidates: string[],          // e.g. ["created_at", "updated_at", "id"]
  opts: { ascending?: boolean } = { ascending: false }
): Promise<{ data: T[]; error: any }> {
  for (const col of candidates) {
    const { data, error } = await baseQuery.order(col, { ascending: !!opts.ascending });
    if (!error) return { data: (data ?? []) as T[], error: null };
    if (!/column .* does not exist/i.test(error.message)) {
      // Real error — bubble up
      return { data: [], error };
    }
  }
  // No candidates worked → just run without ordering
  const { data, error } = await baseQuery;
  return { data: (data ?? []) as T[], error };
}
