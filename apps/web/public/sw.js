const CACHE = 'mega-cerebro-shell-v1';
self.addEventListener('install', event => { event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(['/offline.html', '/icon-192.png', '/icon-512.png']))); self.skipWaiting(); });
self.addEventListener('activate', event => { event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(key => key !== CACHE).map(key => caches.delete(key))))); self.clients.claim(); });
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);
  if (event.request.method !== 'GET' || url.origin !== self.location.origin || url.pathname.startsWith('/api/') || url.pathname.startsWith('/ws/')) return;
  if (event.request.mode === 'navigate') event.respondWith(fetch(event.request).catch(() => caches.match('/offline.html')));
});
