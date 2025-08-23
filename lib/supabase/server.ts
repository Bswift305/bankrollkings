import { createClient } from "@supabase/supabase-js";

/** Server-side Supabase client. Configure in Vercel env vars. */
export function createServerSupabase() {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const anon = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  const service = process.env.SUPABASE_SERVICE_ROLE_KEY; // ✅ Fixed: Match .env.example

  if (!url) throw new Error("Missing NEXT_PUBLIC_SUPABASE_URL");
  if (!anon && !service) throw new Error("Missing SUPABASE key");

  return createClient(url, service ?? anon!, {
    auth: { persistSession: false, autoRefreshToken: false },
  });
}
