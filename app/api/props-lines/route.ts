import { NextRequest, NextResponse } from "next/server";
import { listPropsLines } from "@/lib/services/propsLines"; // <-- note the 'Props'

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  try {
    const data = await listPropsLines(req.nextUrl.searchParams);
    return NextResponse.json({ ok: true, data });
  } catch (err: any) {
    return NextResponse.json(
      { ok: false, error: err?.message ?? "Unknown error" },
      { status: 500 }
    );
  }
}

