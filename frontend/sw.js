/* Asclepius service worker.
 *
 * Two jobs:
 *   1. Web push — receive `push` events and surface them as notifications,
 *      and route taps (`notificationclick`) back into the right tab.
 *   2. A light app-shell cache so the PWA opens instantly and survives a flaky
 *      connection. Strategy is network-first for app assets (so an online user
 *      always gets the freshest app.js/styles.css), with the cache as a fallback.
 *
 * Bump SW_VERSION whenever the precache list or this file changes — the new
 * worker takes over on next load and old caches are swept in `activate`.
 */
const SW_VERSION = "v2-2026-06-10";
const CACHE_NAME = `asclepius-${SW_VERSION}`;

// The shell needed to boot the app offline. Vendored libs are big but rarely
// change, so they're worth precaching.
const PRECACHE = [
  "/",
  "/index.html",
  "/app.js",
  "/styles.css",
  "/manifest.webmanifest",
  "/icons/icon-192.png",
  "/icons/icon-512.png",
  "/icons/badge.png",
  "/vendor/chart.umd.min.js",
  "/vendor/marked.min.js",
  "/vendor/quagga.min.js",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      // Don't let one missing asset abort the whole install.
      .then((cache) => Promise.allSettled(PRECACHE.map((u) => cache.add(u))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  // Never cache API calls or cross-origin requests — let them hit the network.
  if (url.origin !== self.location.origin || url.pathname.startsWith("/api/")) return;

  // Navigations: network-first, fall back to the cached shell when offline.
  if (req.mode === "navigate") {
    event.respondWith(
      fetch(req).catch(() => caches.match("/index.html").then((r) => r || caches.match("/")))
    );
    return;
  }

  // Static assets: network-first, caching fresh copies; fall back to cache.
  event.respondWith(
    fetch(req)
      .then((res) => {
        if (res && res.ok) {
          const copy = res.clone();
          caches.open(CACHE_NAME).then((c) => c.put(req, copy));
        }
        return res;
      })
      .catch(() => caches.match(req))
  );
});

/* ---------------------------------------------------------------- Push --- */
self.addEventListener("push", (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch (e) {
    data = { title: "Asclepius", body: event.data ? event.data.text() : "" };
  }
  const title = data.title || "Asclepius";
  const options = {
    body: data.body || "",
    icon: data.icon || "/icons/icon-192.png",
    badge: data.badge || "/icons/badge.png",
    tag: data.tag || "asclepius",
    renotify: true,
    data: { url: data.url || "/", ntype: data.ntype || "" },
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = (event.notification.data && event.notification.data.url) || "/";
  const targetUrl = new URL(target, self.location.origin).href;
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clients) => {
      // Focus an existing app window if one is open, navigating it to the tab.
      for (const client of clients) {
        if (client.url.startsWith(self.location.origin) && "focus" in client) {
          if ("navigate" in client) client.navigate(targetUrl).catch(() => {});
          return client.focus();
        }
      }
      return self.clients.openWindow(targetUrl);
    })
  );
});
