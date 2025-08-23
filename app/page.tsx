"use client";

import React, { useEffect, useMemo, useState } from "react";

// ---------------------------------------------
// Types
// ---------------------------------------------

type Tier = "top10" | "bottom10" | "mid";
type DefCat = "rush" | "pass" | "overall";
type Position = "RB" | "WR" | "TE" | "QB";

type LeaderboardRow = {
  player_id: string;
  full_name: string;
  total: number;
  per_game: number;
  games: number;
};

type HitRate = {
  attempts: number;
  hits: number;
  hit_rate_pct: number;
};

// ---------------------------------------------
// Utilities
// ---------------------------------------------

const isUUID = (v?: string) => !!v && /^(?:[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})$/i.test(v);

const cx = (...c: (string | false | undefined)[]) => c.filter(Boolean).join(" ");

const fetchJSON = async <T,>(url: string): Promise<T> => {
  const res = await fetch(url);
  const ct = res.headers.get("content-type") || "";
  if (!res.ok) {
    // Avoid dumping huge HTML into the UI
    let snippet = "";
    try { snippet = (await res.text()).slice(0, 240); } catch {}
    const msg = `${res.status} ${res.statusText} for ${url}` + (snippet && !snippet.startsWith("<") ? ` — ${snippet}` : "");
    throw new Error(msg);
  }
  if (!ct.includes("application/json")) {
    throw new Error(`Expected JSON but got ${ct || "unknown content type"} from ${url}`);
  }
  return res.json() as Promise<T>;
};

// Convert tri-state dropdown to query param
const boolParam = (s: "any" | "only" | "exclude"): boolean | null =>
  s === "any" ? null : s === "only" ? true : false;

// ---------------------------------------------
// FiltersBar
// ---------------------------------------------

type Filters = {
  position: Position;
  stat: "rush_yards" | "rec_yards" | "receptions" | "pass_yards";
  seasonFrom: number;
  seasonTo: number;
  defCat: DefCat;
  tier: Tier;
  prime: "any" | "only" | "exclude"; // tri-state -> null/true/false
  dome: "any" | "only" | "exclude";
  windy: "any" | "only" | "exclude";
  homeAway?: "home" | "away" | "any";
  playerUUID?: string; // For HitRateCard
  propType?:
    | "rush_yds"
    | "rec_yds"
    | "receptions"
    | "pass_yds"
    | "rush_tds"
    | "rec_tds"
    | "pass_tds";
};

const defaultFilters: Filters = {
  position: "RB",
  stat: "rush_yards",
  seasonFrom: new Date().getFullYear() - 2, // last 3 seasons by default
  seasonTo: new Date().getFullYear(),
  defCat: "rush",
  tier: "top10",
  prime: "any",
  dome: "any",
  windy: "any",
  homeAway: "any",
  playerUUID: "",
  propType: "rush_yds",
};

function FiltersBar({
  value,
  onChange,
}: {
  value: Filters;
  onChange: (f: Filters) => void;
}) {
  const [local, setLocal] = useState<Filters>(value);

  useEffect(() => setLocal(value), [value]);

  const update = (patch: Partial<Filters>) => {
    const next = { ...local, ...patch };
    setLocal(next);
    onChange(next);
  };

  return (
    <div className="grid gap-3 rounded-2xl border border-zinc-800 bg-zinc-900/60 p-4 shadow-lg">
      <div className="grid grid-cols-1 gap-3 md:grid-cols-3 lg:grid-cols-6">
        {/* Position */}
        <label className="flex flex-col gap-1">
          <span className="text-xs uppercase tracking-wide text-zinc-400">Position</span>
          <select
            className="rounded-xl border border-zinc-700 bg-zinc-900 p-2 text-zinc-100"
            value={local.position}
            onChange={(e) => update({ position: e.target.value as Position })}
          >
            {(["RB", "WR", "TE", "QB"] as Position[]).map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </label>

        {/* Stat (Leaderboard) */}
        <label className="flex flex-col gap-1">
          <span className="text-xs uppercase tracking-wide text-zinc-400">Leaderboard Stat</span>
          <select
            className="rounded-xl border border-zinc-700 bg-zinc-900 p-2 text-zinc-100"
            value={local.stat}
            onChange={(e) => update({ stat: e.target.value as Filters["stat"] })}
          >
            <option value="rush_yards">Rush Yards</option>
            <option value="rec_yards">Rec Yards</option>
            <option value="receptions">Receptions</option>
            <option value="pass_yards">Pass Yards</option>
          </select>
        </label>

        {/* Seasons */}
        <label className="flex flex-col gap-1">
          <span className="text-xs uppercase tracking-wide text-zinc-400">From Season</span>
          <input
            type="number"
            className="rounded-xl border border-zinc-700 bg-zinc-900 p-2 text-zinc-100"
            value={local.seasonFrom}
            onChange={(e) => update({ seasonFrom: Number(e.target.value) })}
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs uppercase tracking-wide text-zinc-400">To Season</span>
          <input
            type="number"
            className="rounded-xl border border-zinc-700 bg-zinc-900 p-2 text-zinc-100"
            value={local.seasonTo}
            onChange={(e) => update({ seasonTo: Number(e.target.value) })}
          />
        </label>

        {/* Defense Category & Tier */}
        <label className="flex flex-col gap-1">
          <span className="text-xs uppercase tracking-wide text-zinc-400">Defense Category</span>
          <select
            className="rounded-xl border border-zinc-700 bg-zinc-900 p-2 text-zinc-100"
            value={local.defCat}
            onChange={(e) => update({ defCat: e.target.value as DefCat })}
          >
            <option value="rush">Rush</option>
            <option value="pass">Pass</option>
            <option value="overall">Overall</option>
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs uppercase tracking-wide text-zinc-400">Defense Tier</span>
          <select
            className="rounded-xl border border-zinc-700 bg-zinc-900 p-2 text-zinc-100"
            value={local.tier}
            onChange={(e) => update({ tier: e.target.value as Tier })}
          >
            <option value="top10">Top 10</option>
            <option value="mid">Mid</option>
            <option value="bottom10">Bottom 10</option>
          </select>
        </label>
      </div>

      {/* Situational Toggles */}
      <div className="grid grid-cols-1 gap-3 md:grid-cols-3 lg:grid-cols-6">
        {(
          [
            { key: "prime", label: "Prime Time" },
            { key: "dome", label: "Dome" },
            { key: "windy", label: "Wind ≥ 15mph" },
          ] as const
        ).map(({ key, label }) => (
          <label key={key} className="flex flex-col gap-1">
            <span className="text-xs uppercase tracking-wide text-zinc-400">{label}</span>
            <select
              className="rounded-xl border border-zinc-700 bg-zinc-900 p-2 text-zinc-100"
              value={local[key]}
              onChange={(e) => update({ [key]: e.target.value as Filters[typeof key] } as any)}
            >
              <option value="any">Any</option>
              <option value="only">Only</option>
              <option value="exclude">Exclude</option>
            </select>
          </label>
        ))}

        <label className="flex flex-col gap-1">
          <span className="text-xs uppercase tracking-wide text-zinc-400">Home/Away</span>
          <select
            className="rounded-xl border border-zinc-700 bg-zinc-900 p-2 text-zinc-100"
            value={local.homeAway}
            onChange={(e) => update({ homeAway: e.target.value as Filters["homeAway"] })}
          >
            <option value="any">Any</option>
            <option value="home">Home</option>
            <option value="away">Away</option>
          </select>
        </label>

        {/* Player (UUID) + Prop Type for HitRateCard */}
        <label className="flex flex-col gap-1">
          <span className="text-xs uppercase tracking-wide text-zinc-400">Player UUID (for Hit Rate)</span>
          <input
            placeholder="00000000-0000-0000-0000-000000000000"
            className="rounded-xl border border-zinc-700 bg-zinc-900 p-2 text-zinc-100 placeholder-zinc-600"
            value={local.playerUUID}
            onChange={(e) => update({ playerUUID: e.target.value })}
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs uppercase tracking-wide text-zinc-400">Prop Type</span>
          <select
            className="rounded-xl border border-zinc-700 bg-zinc-900 p-2 text-zinc-100"
            value={local.propType}
            onChange={(e) => update({ propType: e.target.value as NonNullable<Filters["propType"]> })}
          >
            <option value="rush_yds">Rush Yards</option>
            <option value="rec_yds">Rec Yards</option>
            <option value="receptions">Receptions</option>
            <option value="pass_yds">Pass Yards</option>
            <option value="rush_tds">Rush TDs</option>
            <option value="rec_tds">Rec TDs</option>
            <option value="pass_tds">Pass TDs</option>
          </select>
        </label>
      </div>
    </div>
  );
}

// ---------------------------------------------
// Leaderboard
// ---------------------------------------------

function Leaderboard({ filters }: { filters: Filters }) {
  const [rows, setRows] = useState<LeaderboardRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  // ✅ FIXED: Correct API URL and parameter mapping
  const qs = useMemo(() => {
    const p = new URLSearchParams({
      position: filters.position,
      category: filters.defCat,        // ✅ API expects 'category', not 'defCat'
      defTier: filters.tier,           // ✅ API expects 'defTier', not 'tier'
      seasonFrom: String(filters.seasonFrom),
      seasonTo: String(filters.seasonTo),
      limit: String(50),
    });
    return `/api/situations?${p.toString()}`; // ✅ Correct URL
  }, [filters]);

  useEffect(() => {
    let mounted = true;
    setLoading(true);
    setError(null);
    fetchJSON<{ rows: LeaderboardRow[] }>(qs)
      .then((d) => mounted && setRows(d.rows || []))
      .catch((e) => mounted && setError(e.message))
      .finally(() => mounted && setLoading(false));
    return () => {
      mounted = false;
    };
  }, [qs]);

  return (
    <div className="rounded-2xl border border-zinc-800 bg-zinc-900/60 p-4 shadow-lg">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-lg font-semibold text-zinc-100">
          Leaderboard — {filters.position} vs {filters.defCat.toUpperCase()} {filters.tier}
        </h3>
        <span className="text-xs text-zinc-400">
          {filters.seasonFrom}-{filters.seasonTo}
        </span>
      </div>

      {loading && <div className="animate-pulse text-zinc-400">Loading…</div>}
      {error && (
        <div className="rounded-xl border border-red-800 bg-red-950/40 p-3 text-sm text-red-200">
          {error}
        </div>
      )}

      {!loading && !error && (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] table-fixed border-separate border-spacing-y-6">
            <thead className="text-left text-xs uppercase tracking-wide text-zinc-400">
              <tr>
                <th className="w-12 px-2">#</th>
                <th className="px-2">Player</th>
                <th className="w-24 px-2 text-right">Games</th>
                <th className="w-28 px-2 text-right">Total</th>
                <th className="w-28 px-2 text-right">Per Game</th>
              </tr>
            </thead>
            <tbody>
              {rows?.map((r, idx) => (
                <tr key={r.player_id} className="rounded-xl bg-zinc-950/60">
                  <td className="px-2 text-zinc-400">{idx + 1}</td>
                  <td className="px-2 font-medium text-zinc-100">{r.full_name}</td>
                  <td className="px-2 text-right text-zinc-200">{r.games}</td>
                  <td className="px-2 text-right text-zinc-200">{Math.round(r.total)}</td>
                  <td className="px-2 text-right text-zinc-100">{r.per_game.toFixed(2)}</td>
                </tr>
              ))}
              {!rows?.length && (
                <tr>
                  <td colSpan={5} className="px-2 text-center text-sm text-zinc-400">
                    No results for these filters.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------
// HitRateCard (unchanged - this API call was correct)
// ---------------------------------------------

function HitRateCard({ filters }: { filters: Filters }) {
  const [data, setData] = useState<HitRate | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const canQuery = isUUID(filters.playerUUID) && !!filters.propType;

  const qs = useMemo(() => {
    if (!canQuery) return null;
    const p = new URLSearchParams({
      playerId: filters.playerUUID!,
      propType: filters.propType!,
      seasonFrom: String(filters.seasonFrom),
      seasonTo: String(filters.seasonTo),
    });
    if (filters.defCat) p.set("defCat", filters.defCat);
    if (filters.tier) p.set("tier", filters.tier);
    const prime = boolParam(filters.prime);
    const dome = boolParam(filters.dome);
    const windy = boolParam(filters.windy);
    if (prime !== null) p.set("prime", String(prime));
    if (dome !== null) p.set("dome", String(dome));
    if (windy !== null) p.set("windy", String(windy));
    return `/api/props/hit-rate?${p.toString()}`;
  }, [filters, canQuery]);

  useEffect(() => {
    let mounted = true;
    if (!qs) {
      setData(null);
      return;
    }
    setLoading(true);
    setError(null);
    fetchJSON<{ rows: HitRate[] }>(qs)
      .then((d) => mounted && setData(d.rows?.[0] ?? null))
      .catch((e) => mounted && setError(e.message))
      .finally(() => mounted && setLoading(false));
    return () => {
      mounted = false;
    };
  }, [qs]);

  return (
    <div className="rounded-2xl border border-zinc-800 bg-zinc-900/60 p-4 shadow-lg">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-lg font-semibold text-zinc-100">Prop Hit Rate</h3>
        <span className="text-xs text-zinc-400">{filters.propType}</span>
      </div>

      {!isUUID(filters.playerUUID) && (
        <div className="mb-2 rounded-xl border border-amber-800 bg-amber-950/40 p-3 text-sm text-amber-200">
          Enter a valid Player UUID to compute hit rate.
        </div>
      )}

      {loading && <div className="animate-pulse text-zinc-400">Loading…</div>}
      {error && (
        <div className="rounded-xl border border-red-800 bg-red-950/40 p-3 text-sm text-red-200">
          {error}
        </div>
      )}

      {data && !error && !loading && (
        <div className="grid gap-4 md:grid-cols-3">
          <Stat label="Attempts" value={data.attempts} />
          <Stat label="Hits" value={data.hits} />
          <Stat label="Hit Rate" value={`${data.hit_rate_pct.toFixed(1)}%`} />
        </div>
      )}

      {!loading && !error && !data && isUUID(filters.playerUUID) && (
        <div className="text-sm text-zinc-400">No data for this player/prop with current filters.</div>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-950/60 p-4 text-center">
      <div className="text-xs uppercase tracking-wide text-zinc-400">{label}</div>
      <div className="mt-1 text-2xl font-semibold text-zinc-100">{value}</div>
    </div>
  );
}

// ---------------------------------------------
// Main Page Component
// ---------------------------------------------

export default function BKHomeExample() {
  const [filters, setFilters] = useState<Filters>(defaultFilters);

  return (
    <main className="mx-auto grid max-w-6xl gap-6 p-4 md:p-8">
      <header className="flex flex-col gap-2">
        <h1 className="text-2xl font-bold text-zinc-100">BankrollKings — Situational Edge</h1>
        <p className="text-sm text-zinc-400">
          Slice historical performance by defense tiers, weather, and venue to inform props, DFS, and fantasy decisions.
        </p>
      </header>

      <FiltersBar value={filters} onChange={setFilters} />

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <Leaderboard filters={filters} />
        </div>
        <div className="lg:col-span-1">
          <HitRateCard filters={filters} />
        </div>
      </div>
    </main>
  );
}
