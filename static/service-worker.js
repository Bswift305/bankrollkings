const BK_CACHE = 'bankroll-kings-shell-v5';
const SHELL_ASSETS = [
  '/static/css/bk-theme.css',
  '/static/brand-latest-logo-thumb.webp',
  '/static/brand-latest-logo.webp',
  '/static/logos/leagues/nba.svg',
  '/static/logos/leagues/mlb.svg',
  '/static/logos/leagues/nfl.svg',
  '/static/logos/leagues/wnba.svg',
  '/static/logos/leagues/home.png',
  '/static/logos/leagues/settings.png',
  '/static/logos/leagues/glossary.png'
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(BK_CACHE)
      .then(cache => cache.addAll(SHELL_ASSETS))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys => Promise.all(
      keys.filter(key => key !== BK_CACHE).map(key => caches.delete(key))
    )).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', event => {
  const request = event.request;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);
  const isShellAsset = url.origin === self.location.origin && (
    url.pathname.startsWith('/static/css/') ||
    url.pathname.startsWith('/static/logos/') ||
    url.pathname.includes('brand-latest-logo')
  );

  if (!isShellAsset) return;

  // Stale-while-revalidate: serve the cached copy instantly for speed, but
  // always revalidate against the network in the background and refresh the
  // cache. The revalidation uses cache: 'no-cache' so it sends a conditional
  // request to the server (304 when unchanged, 200 with new bytes when the
  // file changed) INSTEAD of being pinned by the 12h HTTP max-age. Net effect:
  // a same-filename asset swap (e.g. a league logo) is picked up automatically
  // on the next load -- no cache-version bump or ?v= query needed.
  event.respondWith(
    caches.open(BK_CACHE).then(cache =>
      cache.match(request).then(cached => {
        const network = fetch(request, { cache: 'no-cache' }).then(response => {
          if (response && response.ok) {
            cache.put(request, response.clone());
          }
          return response;
        }).catch(() => cached);
        return cached || network;
      })
    )
  );
});
