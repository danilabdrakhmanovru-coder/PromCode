// Service Worker для «ПромКод»
// Стратегия: stale-while-revalidate для статики, network-only для /api/*

const CACHE_VERSION = 'nasledie-v25';
const STATIC_CACHE = `${CACHE_VERSION}-static`;
const RUNTIME_CACHE = `${CACHE_VERSION}-runtime`;

// Файлы, которые кешируем сразу при установке
const PRECACHE_URLS = [
  '/',
  '/static/css/styles.css',
  '/static/js/app.js',
  '/static/js/map.js',
  '/static/js/site3d.js',
  '/static/manifest.json',
  '/static/icon.svg',
  '/static/icon-maskable.svg',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(STATIC_CACHE)
      .then((cache) => cache.addAll(PRECACHE_URLS).catch(() => {
        // Не падаем, если какой-то ресурс недоступен
        return Promise.resolve();
      }))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys
          .filter((key) => !key.startsWith(CACHE_VERSION))
          .map((key) => caches.delete(key))
      ))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const { request } = event;

  // Только GET-запросы
  if (request.method !== 'GET') return;

  const url = new URL(request.url);

  // API-запросы всегда идут в сеть (свежие данные)
  if (url.pathname.startsWith('/api/')) {
    return;
  }

  // Внешние домены (Leaflet тайлы, 2GIS, шрифты) — network-first
  if (url.origin !== self.location.origin) {
    event.respondWith(
      fetch(request)
        .then((response) => {
          // Кешируем только успешные ответы шрифтов и CDN
          if (response.ok && (url.host.includes('fonts.g') || url.host.includes('cdnjs'))) {
            const clone = response.clone();
            caches.open(RUNTIME_CACHE).then((c) => c.put(request, clone));
          }
          return response;
        })
        .catch(() => caches.match(request))
    );
    return;
  }

  // Свои ресурсы: stale-while-revalidate
  event.respondWith(
    caches.match(request).then((cached) => {
      const networkFetch = fetch(request)
        .then((response) => {
          if (response.ok) {
            const clone = response.clone();
            caches.open(STATIC_CACHE).then((c) => c.put(request, clone));
          }
          return response;
        })
        .catch(() => cached);

      return cached || networkFetch;
    })
  );
});

// Сообщение от страницы для немедленной активации
self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
});
