const CACHE = 'lifey-shell-v4aff4eb9ffe0';
const SHELL = [
  './',
  './index.html',
  './manifest.webmanifest',
  './styles.css',
  './preferences.css',
  './capture.css',
  './capture-calendar.css',
  './dashboard-layout.css',
  './task-card.css',
  './spotify-card.css',
  './settings-panels.css',
  './projects-card.css',
  './media-card.css',
  './habits-card.css',
  './location-card.css',
  './calendar-card.css',
  './mobile.css',
  './app.js',
  './js/actions.js',
  './js/api.js',
  './js/features/capture/capture.js',
  './js/features/capture/controller.js',
  './js/features/habits/habits.js',
  './js/features/location/controller.js',
  './js/features/location/location.js',
  './js/features/preferences/controller.js',
  './js/features/projects/controller.js',
  './js/integrations/spotify.js',
  './js/parsers.js',
  './js/renderers.js',
  './js/state.js',
  './lifey-icon.svg'
];

self.addEventListener('install', event => event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(SHELL)).then(() => self.skipWaiting())));
self.addEventListener('activate', event => event.waitUntil(
  caches.keys()
    .then(keys => Promise.all(keys.filter(key => key !== CACHE).map(key => caches.delete(key))))
    .then(() => self.clients.claim())
));
self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET') return;
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin || url.pathname.startsWith('/api/')) return;
  event.respondWith(fetch(event.request).then(response => {
    if (response.ok) caches.open(CACHE).then(cache => cache.put(event.request, response.clone()));
    return response;
  }).catch(() => caches.match(event.request).then(cached => cached || caches.match('./index.html'))));
});
