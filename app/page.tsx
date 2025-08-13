import Link from "next/link";

export default function HomePage() {
  return (
    <main style={{ padding: 24, maxWidth: 960, margin: "0 auto" }}>
      <h1 style={{ fontSize: 32, fontWeight: 700 }}>BankrollKings</h1>
      <p style={{ marginTop: 12 }}>
        API checks:{" "}
        <Link href="/api/health">/api/health</Link>{" "}
        | <Link href="/api/team-metrics">/api/team-metrics</Link>{" "}
        | <Link href="/api/ping">/api/ping</Link>{" "}
        | <Link href="/api/consensus-bets?limit=5">/api/consensus-bets</Link>
      </p>
    </main>
  );
}

