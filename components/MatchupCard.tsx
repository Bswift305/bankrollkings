// components/MatchupCard.tsx
"use client";
import { useEffect, useState } from "react";

export default function MatchupCard({ wr, cb, season, week }: { wr: string; cb: string; season?: string; week?: string; }) {
  const [rows, setRows] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const url = new URL("/api/matchups/wr-vs-cb", window.location.origin);
    url.searchParams.set("wr", wr);
    url.searchParams.set("cb", cb);
    if (season) url.searchParams.set("season", season);
    if (week) url.searchParams.set("week", week);

    setLoading(true);
    fetch(url.toString())
      .then(r => r.json())
      .then(r => setRows(r.data ?? []))
      .finally(() => setLoading(false));
  }, [wr, cb, season, week]);

  if (loading) return <div className="p-4">Loading…</div>;
  if (!rows.length) return <div className="p-4">No data for {wr} vs {cb}.</div>;

  const s = rows[0]; // latest row
  return (
    <div className="p-4 rounded-xl border">
      <div className="text-xl font-semibold">{wr} vs {cb}</div>
      <div className="text-sm text-gray-500">{s.offense_team} vs {s.defense_team} — Wk {s.week}, {s.season}</div>
      <div className="mt-3 grid grid-cols-4 gap-3">
        <Stat label="Targets" value={s.targets} />
        <Stat label="Receptions" value={s.receptions} />
        <Stat label="Yards" value={s.yards} />
        <Stat label="TDs" value={s.tds} />
        <Stat label="Avg Air Yds" value={Number(s.avg_air_yards)?.toFixed(1)} />
        <Stat label="Avg YAC" value={Number(s.avg_yac)?.toFixed(1)} />
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: any }) {
  return (
    <div className="p-3 rounded-lg border">
      <div className="text-xs text-gray-500">{label}</div>
      <div className="text-lg font-medium">{value ?? "—"}</div>
    </div>
  );
}
