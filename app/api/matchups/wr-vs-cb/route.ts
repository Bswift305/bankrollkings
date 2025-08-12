// app/api/matchups/wr-vs-cb/route.ts
import { NextRequest, NextResponse } from 'next/server';
import { createServerSupabase } from '@/lib/supabase/server'; // see tsconfig step below

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(req: NextRequest) {
  const sp = req.nextUrl.searchParams;
  const wr = sp.get('wr');
  const cb = sp.get('cb');
  const season = sp.get('season');

  const supabase = createServerSupabase();

  // TEMP: prove it builds/returns. Replace with your real query next.
  return NextResponse.json({ ok: true, route: 'wr-vs-cb', wr, cb, season });
}
