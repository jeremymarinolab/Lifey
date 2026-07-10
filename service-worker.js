const ASSET_VERSION = 'e1e195171f95';
const CACHE = `lifey-shell-v${ASSET_VERSION}`;
// Generated from index.html, imported JS modules, and manifest.webmanifest.
const SHELL = [
  './',
  './index.html',
  './manifest.webmanifest',
  './LifeyLocation/Assets.xcassets/AppIcon.appiconset/LifeyLogo-20@2x.png',
  './LifeyLocation/Assets.xcassets/AppIcon.appiconset/LifeyLogo-29@2x.png',
  './LifeyLocation/Assets.xcassets/AppIcon.appiconset/LifeyLogo-40@2x.png',
  './LifeyLocation/Assets.xcassets/AppIcon.appiconset/LifeyLogo-60@2x.png',
  './LifeyLocation/Assets.xcassets/AppIcon.appiconset/LifeyLogo-60@3x.png',
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
  './suggestions-card.css',
  './mobile.css',
  './app.js',
  './js/actions.js',
  './js/api.js',
  './js/app-updates.js',
  './js/features/calendar/calendar.js',
  './js/features/capture/capture.js',
  './js/features/capture/controller.js',
  './js/features/habits/habits.js',
  './js/features/location/controller.js',
  './js/features/location/location.js',
  './js/features/location/render.js',
  './js/renderers.js',
  './js/ui/components.js',
  './js/ui/controls.js',
  './js/features/media/render.js',
  './js/ui/config.js',
  './js/features/preferences/controller.js',
  './js/features/projects/controller.js',
  './js/features/projects/render.js',
  './js/features/tasks/render.js',
  './js/integrations/spotify.js',
  './js/parsers.js',
  './js/state.js',
  './LifeyLocation/Assets.xcassets/AppIcon.appiconset/LifeyLogo-1024.png'
];

self.addEventListener('install', event => event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(SHELL)).then(() => self.skipWaiting())));
self.addEventListener('activate', event => event.waitUntil(
  caches.keys()
    .then(keys => Promise.all(keys.filter(key => key !== CACHE).map(key => caches.delete(key))))
    .then(() => self.clients.claim())
    .then(() => self.clients.matchAll({ type: 'window', includeUncontrolled: true }))
    .then(clients => clients.forEach(client => client.postMessage({ type: 'LIFEY_ACTIVATED', version: ASSET_VERSION })))
));
self.addEventListener('message', event => {
  if (event.data?.type === 'LIFEY_GET_VERSION') event.source?.postMessage({ type: 'LIFEY_VERSION', version: ASSET_VERSION });
});
self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET') return;
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin || url.pathname.startsWith('/api/')) return;
  event.respondWith(fetch(event.request).then(response => {
    if (response.ok) caches.open(CACHE).then(cache => cache.put(event.request, response.clone()));
    return response;
  }).catch(() => caches.match(event.request).then(cached => cached || caches.match('./index.html'))));
});
