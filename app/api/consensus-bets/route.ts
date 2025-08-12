import { NextRequest, NextResponse } from "next/server";
import { getLimitFromSearchParams } from "@/lib/http/params";
import { listConsensusBets } from "@/lib/services/consensusBets";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  try {
    const limit = getLimitFromSearchParams(req.nextUrl.searchParams, 50, 200);
    const data = await listConsensusBets({ limit });
    return NextResponse.json({ ok: true, data });
  } catch (err: any) {
    return NextResponse.json({ ok: false, error: err?.message ?? "Unknown error" }, { status: 500 });
  }
}
```ts
import { NextRequest, NextResponse } from "next/server";
import { getLimitFromSearchParams } from "@/lib/http/params";
import { listConsensusBets } from "@/lib/services/consensusBets";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  try {
    const limit = getLimitFromSearchParams(req.nextUrl.searchParams, 50, 200);
    const data = await listConsensusBets({ limit });
    return NextResponse.json({ ok: true, data });
  } catch (err: any) {
    return NextResponse.json({ ok: false, error: err?.message ?? "Unknown error" }, { status: 500 });
  }
}
