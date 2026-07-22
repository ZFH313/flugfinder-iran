/**
 * FlugFinder Iran – Service Worker
 * Ermöglicht Offline-Nutzung und schnellere Ladezeiten.
 */

const CACHE_NAME = "flugfinder-v1";
const ASSETS_TO_CACHE = [
    "/",
    "/index.html",
    "/style.css",
    "/app.js",
    "/manifest.json",
];

// Installation: Cache alle statischen Assets
self.addEventListener("install", (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => {
            console.log("Service Worker: Cache geöffnet");
            return cache.addAll(ASSETS_TO_CACHE);
        })
    );
    // Sofort aktivieren
    self.skipWaiting();
});

// Aktivierung: Alte Caches löschen
self.addEventListener("activate", (event) => {
    event.waitUntil(
        caches.keys().then((cacheNames) => {
            return Promise.all(
                cacheNames
                    .filter((name) => name !== CACHE_NAME)
                    .map((name) => caches.delete(name))
            );
        })
    );
    // Alle offenen Tabs übernehmen
    self.clients.claim();
});

// Fetch: Network-first für data.json, Cache-first für alles andere
self.addEventListener("fetch", (event) => {
    const url = new URL(event.request.url);

    // data.json immer frisch vom Netzwerk laden (enthält aktuelle Flugdaten)
    if (url.pathname.endsWith("data.json")) {
        event.respondWith(
            fetch(event.request)
                .then((response) => {
                    // Erfolgreiche Antwort in Cache speichern
                    const clone = response.clone();
                    caches.open(CACHE_NAME).then((cache) => {
                        cache.put(event.request, clone);
                    });
                    return response;
                })
                .catch(() => {
                    // Offline: aus Cache laden
                    return caches.match(event.request);
                })
        );
        return;
    }

    // Alle anderen Assets: Cache-first, dann Netzwerk
    event.respondWith(
        caches.match(event.request).then((cached) => {
            if (cached) {
                return cached;
            }
            return fetch(event.request).then((response) => {
                // Nur gültige Antworten cachen
                if (!response || response.status !== 200 || response.type !== "basic") {
                    return response;
                }
                const clone = response.clone();
                caches.open(CACHE_NAME).then((cache) => {
                    cache.put(event.request, clone);
                });
                return response;
            });
        })
    );
});
