// app/page.tsx
// BankrollKings — Phase 1 NFL Dashboard (server component)
// - Black/red/gray theme with four widgets: Props, Consensus, Injuries, Weather
// - Fetches from your existing API routes with no caching
// - Avoids typedRoutes issues by using <a> for raw JSON API links

import React from "react";
import Link from "next/link";

export const metadata = {
  title: "BankrollKings – NFL Dashboard",
  description: "NFL props, consensus, injuries, and weather in one place.",
};

// ---------- Types ----------
type ApiResp<T = unknown> = { ok: boolean; data?: T; error?: string };

// ---------- Helpers ----------
async function get<T>(path: string): Promise<T | null> {
  try {
    const res = await fetch(path, { cache: "no-store" });
    const json = (await res.json()) as ApiResp<T> | T;
    if (json && typeof json === "object" && "ok" in (json as any)) {
      const r = json as ApiResp<T>;
      if (r.ok) return (r.data ?? null) as T | null;
      console.error(`[API ERROR] ${path}:`, r.error);
      return null;
    }
    return json as T;
  } catch (e) {
    console.error(`[FETCH FAIL] ${path}:`, e);
    return null;
  }
}

function cn(...classes: Array<string | false | null | undefined>) {
  return classes.filter(Boolean).join(" ");
}

// ---------- UI Shell ----------
function Nav() {
  return (
    <header className="sticky top-0 z-50 border-b border-neutral-800 bg-black/70 backdrop-blur">
      <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-3">
        <Link href="/" className="group inline-flex items-center gap-2">
          <div className="h-8 w-8 rounded bg-red-600 group-hover:bg-red-500" />
          <span className="text-lg font-semibold tracking-wide text-white">
            Bankroll<span className="text-red-500">Kings</span>
          </span>
        </Link>
        <nav className="flex items-center gap-4 text-sm">
          <a className="text-neutral-300 hover:text-white" href="#props">Props</a>
          <a className="text-neutral-300 hover:text-white" href="#consensus">Consensus</a>
          <a className="text-neutral-300 hover:text-white" href="#injuries">Injuries</a>
          <a className="text-neutral-300 hover:text-white" href="#weather">Weather</a>
        </nav>
      </div>
    </header>
  );
}

function Hero() {
  return (
    <section className="bg-gradient-to-b from-black via-neutral-950 to-black">
      <div className="mx-auto max-w-7xl px-4 py-10 md:py-14">
        <div className="flex flex-col items-start gap-6 md:flex-row md:items-center md:justify-between">
          <div>
            <h1 className="text-3xl font-bold tracking-tight text-white md:text-4xl">
              Data that <span className="text-red-500">Wins</span>
            </h1>
            <p className="mt-2 max-w-2xl text-sm text-neutral-300 md:text-base">
              NFL props, fantasy edges, spreads, consensus, injuries & weather — fast, factual, organized.
            </p>
          </div>
          <div className="flex gap-3">
            <a
              href="#props"
              className="rounded-xl border border-red-600 bg-red-600 px-4 py-2 text-sm font-medium text-white hover:border-red-500 hover:bg-red-500"
            >
              NFL Props
            </a>
            <a
              href="#consensus"
              className="rounded-xl border border-neutral-800 px-4 py-2 text-sm font-medium text-white hover:border-neutral-700"
            >
              Consensus Bets
            </a>
          </div>
        </div>
      </div>
    </section>
  );
}

function Section({
  id,
  title,
  subtitle,
  children,
}: {
  id: string;
  title: string;
  subtitle?: string;
  children: React.ReactNode;
}) {
  const apiHref = `/api/${id.replace("-", "")}`;
  return (
    <section id={id} className="mx-auto max-w-7xl px-4 py-6 md:py-8">
      <div className="mb-4 flex items-end justify-between">
        <div>
          <h2 className="text-xl font-semibold text-white md:text-2xl">{title}</h2>
          {subtitle && <p className="mt-1 text-sm text-neutral-400">{subtitle}</p>}
        </div>
        {/* Use <a> so typedRoutes doesn’t complain about dynamic template */}
        <a href={apiHref} className="text-xs text-neutral-400 hover:text-neutral-200">
          API
        </a>
      </div>
      {children}
    </section>
  );
}

function WidgetCard({
  title,
  children,
  footer,
}: {
  title: string;
  children: React.ReactNode;
  footer?: React.ReactNode;
}) {
  return (
    <div className="rounded-2xl border border-neutral-800 bg-neutral-950/80 p-4 shadow-xl shadow-black/40">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-neutral-200">{title}</h3>
      </div>
      <div>{children}</div>
      {footer && (
        <div className="mt-3 border-t border-neutral-900 pt-3 text-xs text-neutral-400">{footer}</div>
      )}
    </div>
  );
}

// ---------- Widgets (server components) ----------
async function OddsPropsWidget() {
  const props = await get<any[]>("/api/props-lines?limit=10");
  return (
    <WidgetCard title="Props & Odds (Top 10)">
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        {(props ?? []).slice(0, 10).map((p: any, i: number) => (
          <div
            key={i}
            className="flex items-center justify-between rounded-xl border border-neutral-800 bg-black/40 p-3"
          >
            <div className="min-w-0">
              <div className="truncate text-sm font-medium text-white">
                {p?.player ?? "Player"}{" "}
                <span className="text-neutral-400">{p?.market ?? "Prop"}</span>
              </div>
              <div className="text-xs text-neutral-400">
                {p?.team ?? "Team"} · {p?.opponent ?? "Opp"}
              </div>
            </div>
            <div className="text-right">
              <div className="text-sm font-semibold text-red-400">{p?.line ?? "-"}</div>
              <div className="text-xs text-neutral-500">{p?.book ?? "book"}</div>
            </div>
          </div>
        ))}
      </div>
      {(props ?? []).length === 0 && (
        <div className="mt-3 text-right text-xs text-neutral-500">
          No props found. Check /api/props-lines data.
        </div>
      )}
    </WidgetCard>
  );
}

async function ConsensusWidget() {
  const data = await get<any[]>("/api/consensus-bets?limit=10");
  return (
    <WidgetCard title="Consensus Bets (Public %)">
      <div className="divide-y divide-neutral-900">
        {(data ?? []).map((row: any, i: number) => (
          <div key={i} className="flex items-center justify-between py-3">
            <div className="min-w-0">
              <div className="truncate text-sm text-white">{row?.matchup ?? "Matchup"}</div>
              <div className="text-xs text-neutral-500">{row?.market ?? "Spread/Total/ML"}</div>
            </div>
            <div className="text-right">
              <div className="text-sm font-semibold text-white">
                {typeof row?.public_pct === "number" ? `${Math.round(row.public_pct)}%` : "-"}
              </div>
              <div
                className={cn(
                  "text-xs",
                  typeof row?.edge === "number" && row.edge > 0 ? "text-green-400" : "text-neutral-500"
                )}
              >
                edge
              </div>
            </div>
          </div>
        ))}
      </div>
      {(data ?? []).length === 0 && (
        <div className="pt-2 text-xs text-neutral-500">No consensus data yet.</div>
      )}
    </WidgetCard>
  );
}

async function InjuriesWidget() {
  const data = await get<any[]>("/api/injuries?limit=10");
  return (
    <WidgetCard title="Injury Radar (Last 10)">
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        {(data ?? []).map((row: any, i: number) => (
          <div key={i} className="rounded-xl border border-neutral-800 bg-black/40 p-3">
            <div className="text-sm font-medium text-white">{row?.player ?? "Player"}</div>
            <div className="text-xs text-neutral-400">
              {row?.team ?? "Team"} · {row?.position ?? "Pos"}
            </div>
            <div className="mt-1 text-xs text-neutral-400">{row?.status ?? "Status"}</div>
          </div>
        ))}
      </div>
      {(data ?? []).length === 0 && (
        <div className="pt-2 text-xs text-neutral-500">No injury rows found.</div>
      )}
    </WidgetCard>
  );
}

async function WeatherWidget() {
  const data = await get<any[]>("/api/weather?limit=10");
  const flagged = (data ?? []).filter((r: any) => {
    const wind = Number(r?.wind_mph ?? r?.wind ?? 0);
    const temp = Number(r?.temp_f ?? r?.temperature ?? 999);
    const rainy = r?.conditions && String(r.conditions).toLowerCase().includes("rain");
    return wind >= 15 || temp <= 32 || temp >= 95 || rainy;
  });
  const rows = flagged.length > 0 ? flagged : data ?? [];
  return (
    <WidgetCard title="Weather Watch (Impact Games)">
      <div className="divide-y divide-neutral-900">
        {rows.map((r: any, i: number) => (
          <div key={i} className="flex items-center justify-between py-3">
            <div>
              <div className="text-sm text-white">{r?.matchup ?? r?.game ?? "Game"}</div>
              <div className="text-xs text-neutral-500">{r?.stadium ?? r?.location ?? "Location"}</div>
            </div>
            <div className="text-right">
              <div className="text-xs text-neutral-400">Wind: {r?.wind_mph ?? r?.wind ?? "-"} mph</div>
              <div className="text-xs text-neutral-400">Temp: {r?.temp_f ?? r?.temperature ?? "-"}°F</div>
            </div>
          </div>
        ))}
      </div>
      {(rows ?? []).length === 0 && (
        <div className="pt-2 text-xs text-neutral-500">No weather rows found.</div>
      )}
    </WidgetCard>
  );
}

// ---------- Page ----------
export default async function Home() {
  return (
    <div className="min-h-screen bg-black">
      <Nav />
      <Hero />

      <main className="mx-auto max-w-7xl px-4 pb-20">
        <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
          {/* Left column */}
          <div className="space-y-6">
            <Section id="props" title="Props & Odds" subtitle="Player markets & quick edges">
              {/* @ts-expect-error Server Component */}
              <OddsPropsWidget />
            </Section>

            <Section id="injuries" title="Injuries" subtitle="Skill positions first">
              {/* @ts-expect-error Server Component */}
              <InjuriesWidget />
            </Section>
          </div>

          {/* Right column */}
          <div className="space-y-6">
            <Section id="consensus" title="Consensus" subtitle="Public % vs. market">
              {/* @ts-expect-error Server Component */}
              <ConsensusWidget />
            </Section>

            <Section id="weather" title="Weather" subtitle="Games with potential impact">
              {/* @ts-expect-error Server Component */}
              <WeatherWidget />
            </Section>
          </div>
        </div>
      </main>

      <footer className="border-t border-neutral-900 bg-black/80">
        <div className="mx-auto flex max-w-7xl flex-col items-center justify-between gap-3 px-4 py-6 text-xs text-neutral-500 md:flex-row">
          <div>© {new Date().getFullYear()} BankrollKings. All rights reserved.</div>
          <div className="flex gap-4">
            <a href="/api/health" className="hover:text-neutral-300">Health</a>
            <a href="/api/ping" className="hover:text-neutral-300">Ping</a>
            <a href="mailto:contact@bankrollkings.com" className="hover:text-neutral-300">Contact</a>
          </div>
        </div>
      </footer>
    </div>
  );
}
