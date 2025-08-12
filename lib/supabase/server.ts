import { createClient } from '@supabase/supabase-js';
export function createServerSupabase() {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const anon = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  const service = process.env.SUPABASE_SERVICE_ROLE;
  if (!url) throw new Error('Missing NEXT_PUBLIC_SUPABASE_URL');
  if (!anon && !service) throw new Error('Missing SUPABASE key');
  return createClient(url, service ?? anon!, {
    auth: { persistSession: false, autoRefreshToken: false },
  });
}
app/api/ping/route.ts
import { NextResponse } from 'next/server';
export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
export async function GET() {
  return NextResponse.json({ ok: true, pong: true });
}
app/api/matchups/wr-vs-cb/route.ts
import { NextRequest, NextResponse } from 'next/server';
export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
export async function GET(req: NextRequest) {
  const sp = req.nextUrl.searchParams;
  return NextResponse.json({ ok: true, wr: sp.get('wr'), cb: sp.get('cb'), season: sp.get('season') });
}
