import { NextRequest, NextResponse } from "next/server";
import { listPowerRatings } from "@/lib/services/powerRatings";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  try {
    const data = await listPowerRatings(req.nextUrl.searchParams);
    return NextResponse.json({ ok: true, data });
  } catch (e: any) {
    return NextResponse.json({ ok: false, error: e?.message ?? "Unknown error" }, { status: 500 });
  }
}

