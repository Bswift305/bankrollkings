// app/page.tsx
export default function Home() {
  const links = [
    "/api/health",
    "/api/ping",
    "/api/team-metrics",
    "/api/consensus-bets?limit=20",
    "/api/events?limit=20",
    "/api/game-scripts?limit=20",
    "/api/injuries?limit=20",
    "/api/odds-history?limit=20",
    "/api/pbp-2024?limit=10",
    "/api/player-stats?limit=10",
    "/api/power-ratings?limit=10",
    "/api/props-lines?limit=10",
    "/api/user-watchlist?limit=10",
    "/api/weather?limit=10",
    "/api/matchups/wr-vs-cb?wr=TestWR&cb=TestCB&season=2024",
  ];
  return (
    <main style={{ padding: 24 }}>
      <h1>BankrollKings</h1>
      <p>API checks:</p>
      <ul>
        {links.map((href) => (
          <li key={href}>
            <a href={href}>{href}</a>
          </li>
        ))}
      </ul>
    </main>
  );
}


