// Service worker de Hive2nd Brain.
// - Interfaz (shell): caché primero, se actualiza en segundo plano.
// - API de lectura (/api/pages, /api/page/*): red primero, caché si no hay conexión (marcada con X-Copia-Guardada).
// - Búsqueda y POST: solo red (la página gestiona la cola sin conexión).
// Cambia VERSION en cada cambio de la interfaz: así la app detecta la versión nueva y muestra el aviso.
const VERSION = 'v27';
const SHELL = `shell-${VERSION}`;
const DATA = 'data';
const SHELL_FILES = [
  '/', '/static/manifest.webmanifest', '/static/vendor/marked.min.js', '/static/vendor/purify.min.js',
  '/static/icon-192.png', '/static/icon-512.png', '/static/apple-touch-icon.png',
];

self.addEventListener('install', e => {
  // Sin skipWaiting: la versión nueva espera hasta que el usuario pulse "Actualizar"
  e.waitUntil(caches.open(SHELL).then(c => c.addAll(SHELL_FILES.map(u => new Request(u, { cache:'reload' })))));
});

self.addEventListener('message', e => { if (e.data === 'SKIP_WAITING') self.skipWaiting(); });

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys()
    .then(keys => Promise.all(keys.filter(k => k !== SHELL && k !== DATA).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

// Marca las respuestas servidas desde la caché para que la página avise de que no son datos en vivo
function markCopy(r) {
  const headers = new Headers(r.headers);
  headers.set('X-Copia-Guardada', '1');
  return new Response(r.body, { status: r.status, statusText: r.statusText, headers });
}

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.origin !== location.origin) return;

  if (url.pathname === '/api/pages' || url.pathname.startsWith('/api/page/')) {
    e.respondWith(fetch(e.request).then(res => {
      if (res.ok) { const copy = res.clone(); caches.open(DATA).then(c => c.put(e.request, copy)); }
      return res;
    }).catch(() => caches.match(e.request).then(r => r ? markCopy(r) : new Response(
      JSON.stringify({ error: 'Sin conexión y sin copia guardada' }),
      { status: 503, headers: { 'Content-Type': 'application/json' } }))));
    return;
  }
  if (url.pathname.startsWith('/api/')) return;

  // Shell: responde desde caché y refresca en segundo plano
  const key = url.pathname === '/' ? '/' : e.request;
  e.respondWith(caches.open(SHELL).then(async c => {
    const cached = await c.match(key);
    const net = fetch(e.request).then(res => { if (res.ok) c.put(key, res.clone()); return res; }).catch(() => cached);
    return cached || net;
  }));
});
