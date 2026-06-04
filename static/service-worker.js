const BK_CACHE = 'bankroll-kings-shell-v1';
const SHELL_ASSETS = [
  '/static/css/bk-theme.css',
  '/static/brand-latest-logo-thumb.webp',
  '/static/brand-latest-logo.webp',
  '/static/logos/leagues/nba.svg',
  '/static/logos/leagues/mlb.svg',
  '/static/logos/leagues/nfl.svg',
  '/static/logos/leagues/wnba.svg'
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

  event.respondWith(
    caches.match(request).then(cached => {
      const fresh = fetch(request).then(response => {
        if (response && response.ok) {
          const copy = response.clone();
          caches.open(BK_CACHE).then(cache => cache.put(request, copy));
        }
        return response;
      }).catch(() => cached);
      return cached || fresh;
    })
  );
});
