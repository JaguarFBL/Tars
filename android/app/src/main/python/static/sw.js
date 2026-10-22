const SHELL_CACHE = "tars-shell-v1";
const RUNTIME_CACHE = "tars-runtime-v1";
const PRECACHE = [
  "/manifest.webmanifest",
  "/static/icons/tars-192x192.png",
  "/static/icons/tars-512x512.png",
  "/static/icons/tars-maskable-512x512.png",
];

const OFFLINE_HTML = `<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>TARS hors ligne</title>
  <style>
    :root { color-scheme: light; }
    body {
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      background: #E7E8E6;
      color: #1b1d1c;
      font-family: system-ui, sans-serif;
    }
    main { max-width: 32rem; padding: 2rem; text-align: center; }
    h1 { font-size: 1.5rem; margin: 0 0 0.75rem; }
    p { margin: 0; line-height: 1.5; }
  </style>
</head>
<body>
  <main>
    <h1>TARS est hors ligne</h1>
    <p>Le serveur local est injoignable. Vérifiez qu'il est démarré, puis rechargez la page.</p>
  </main>
</body>
</html>`;

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(SHELL_CACHE)
      .then((cache) => cache.addAll(PRECACHE))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys
          .filter((key) => key.startsWith("tars-") && key !== SHELL_CACHE && key !== RUNTIME_CACHE)
          .map((key) => caches.delete(key))
      ))
      .then(() => self.clients.claim())
  );
});

async function networkFirstNavigation(request) {
  try {
    const response = await fetch(request);
    if (response && response.status === 200) {
      const cache = await caches.open(RUNTIME_CACHE);
      await cache.put("/", response.clone());
    }
    return response;
  } catch (error) {
    const cache = await caches.open(RUNTIME_CACHE);
    const cached = await cache.match("/");
    if (cached) {
      return cached;
    }
    return new Response(OFFLINE_HTML, {
      status: 200,
      headers: { "Content-Type": "text/html; charset=utf-8" },
    });
  }
}

async function cacheFirst(request) {
  const cache = await caches.open(SHELL_CACHE);
  const cached = await cache.match(request);
  if (cached) {
    fetch(request)
      .then((response) => {
        if (response && response.ok) {
          cache.put(request, response.clone());
        }
      })
      .catch(() => {});
    return cached;
  }
  const response = await fetch(request);
  if (response && response.ok) {
    await cache.put(request, response.clone());
  }
  return response;
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") {
    return;
  }
  if (request.headers.has("Range")) {
    return;
  }
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) {
    return;
  }
  if (request.destination === "audio" || /\.(wav|mp3|ogg|m4a)$/i.test(url.pathname)) {
    return;
  }

  if (url.pathname === "/sw.js" || url.pathname === "/manifest.webmanifest") {
    event.respondWith(fetch(request, { cache: "no-store" }));
    return;
  }

  if (request.mode === "navigate" && url.pathname === "/") {
    event.respondWith(networkFirstNavigation(request));
    return;
  }

  if (url.pathname.startsWith("/static/")) {
    event.respondWith(cacheFirst(request));
  }
});
