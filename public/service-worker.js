const CACHE_NAME = "prompt-library-v2";

self.addEventListener("install", (event) => {
    self.skipWaiting();
});

self.addEventListener("activate", (event) => {
    event.waitUntil(
        caches.keys().then((names) =>
            Promise.all(
                names.filter((n) => n !== CACHE_NAME).map((n) => caches.delete(n))
            )
        )
    );
    self.clients.claim();
});

// Network-first caching for static assets; bypass cache for serverless API & Supabase requests
self.addEventListener("fetch", (event) => {
    if (event.request.method !== "GET") return;

    const url = new URL(event.request.url);
    // Never cache API endpoints or external auth/storage requests
    if (
        url.pathname.startsWith('/.netlify/') ||
        url.pathname.startsWith('/api/') ||
        url.hostname.includes('supabase.co')
    ) {
        return;
    }

    event.respondWith(
        fetch(event.request)
            .then((response) => {
                if (response.ok) {
                    const clone = response.clone();
                    caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
                }
                return response;
            })
            .catch(() => caches.match(event.request))
    );
});
