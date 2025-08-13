import { NextRequest, NextResponse } from "next/server";
import { listInjuries } from "@/lib/services/injuries";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  try {
    const data = await listInjuries(req.nextUrl.searchParams);
    return NextResponse.json({ ok: true, data });
  } catch (err: any) {
    return NextResponse.json({ ok: false, error: err?.message ?? "Unknown error" }, { status: 500 });
  }
}
