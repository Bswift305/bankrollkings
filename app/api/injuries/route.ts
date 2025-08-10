import { NextRequest, NextResponse } from "next/server";
import { getLimitFromSearchParams } from "../../../backend/utils/http";
import { listInjuries } from "../../../backend/services/injuries";

export async function GET(req: NextRequest) {
  try {
    const limit = getLimitFromSearchParams(req.nextUrl.searchParams);
    const data = await listInjuries(limit);
    return NextResponse.json({ ok: true, data });
  } catch (e: any) {
    return NextResponse.json(
      { ok: false, error: e?.message ?? "Unknown error" },
      { status: 500 }
    );
  }
}
