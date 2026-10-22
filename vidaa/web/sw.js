// Same-origin cache: the home and its photos open instantly and keep working offline.
const CACHE = 'calm-home-v1';
const SHELL = [
  './',
  'index.html',
  'fonts.css',
  'apps.json',
  'wallpapers/credits.json',
  'js/main.js',
  'js/focus.js',
  'js/launch.js',
  'js/clock.js',
  'js/wallpaper.js',
];

self.addEventListener('install', (event) => event.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL))));
self.addEventListener('activate', (event) =>
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))),
  ),
);
self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== 'GET' || url.origin !== location.origin) return;
  event.respondWith(
    caches.open(CACHE).then(async (cache) => {
      const cached = await cache.match(event.request);
      const fresh = fetch(event.request)
        .then((response) => {
          if (response.ok) cache.put(event.request, response.clone());
          return response;
        })
        .catch(() => cached);
      return cached || fresh;
    }),
  );
});
