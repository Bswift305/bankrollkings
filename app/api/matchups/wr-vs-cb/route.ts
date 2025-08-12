import { NextRequest, NextResponse } from 'next/server';
export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
export async function GET(req: NextRequest) {
  const sp = req.nextUrl.searchParams;
  return NextResponse.json({ ok: true, wr: sp.get('wr'), cb: sp.get('cb'), season: sp.get('season') });
