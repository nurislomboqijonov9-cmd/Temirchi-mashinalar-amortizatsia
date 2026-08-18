// TEMIRCHI GPS Service Worker — fon rejimida yordam beradi
const CACHE = 'temirchi-gps-v1';

self.addEventListener('install', e => { self.skipWaiting(); });
self.addEventListener('activate', e => { e.waitUntil(self.clients.claim()); });

// Periodic Background Sync (qo'llab-quvvatlansa) — fonда flush chaqiradi
self.addEventListener('periodicsync', event => {
  if (event.tag === 'gps-flush') {
    event.waitUntil(notifyClients());
  }
});
// Oddiy Background Sync — internet kelganda
self.addEventListener('sync', event => {
  if (event.tag === 'gps-flush') {
    event.waitUntil(notifyClients());
  }
});

async function notifyClients() {
  const cs = await self.clients.matchAll({ includeUncontrolled: true, type: 'window' });
  cs.forEach(c => c.postMessage({ type: 'flush' }));
}

// Sahifadan xabar — hozircha faqat ping
self.addEventListener('message', e => {
  if (e.data && e.data.type === 'ping') { /* keep-alive */ }
});
