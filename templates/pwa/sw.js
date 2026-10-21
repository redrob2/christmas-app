/* Service worker for the installable app.
   - Pages always come from the server (never cached), so nobody sees stale or
     someone else's data; with no connection you get a friendly offline page.
   - Static files (CSS, JS, icons) are cached; their URLs carry a version, and
     this whole cache is replaced when a new version of the app is deployed.
   - Shows push notifications and opens the right page when one is tapped. */
const VERSION = {{ version|tojson }};
const CACHE = 'christmas-' + VERSION;
const OFFLINE_URL = {{ offline_url|tojson }};
const PRECACHE = {{ precache|tojson }};
const ICON = PRECACHE.find(u => u.includes('icon-192'));
const BADGE = PRECACHE.find(u => u.includes('badge-96'));

self.addEventListener('install', event => {
    event.waitUntil(
        caches.open(CACHE)
            .then(cache => cache.addAll([OFFLINE_URL, ...PRECACHE]))
            .then(() => self.skipWaiting())
    );
});

self.addEventListener('activate', event => {
    event.waitUntil((async () => {
        for (const key of await caches.keys()) {
            if (key !== CACHE) await caches.delete(key);
        }
        if (self.registration.navigationPreload) await self.registration.navigationPreload.enable();
        await self.clients.claim();
    })());
});

self.addEventListener('fetch', event => {
    const request = event.request;
    if (request.method !== 'GET') return;
    const url = new URL(request.url);

    if (request.mode === 'navigate') {
        event.respondWith((async () => {
            try {
                return (await event.preloadResponse) || await fetch(request);
            } catch (e) {
                return (await caches.match(OFFLINE_URL)) || Response.error();
            }
        })());
        return;
    }

    if (url.origin === self.location.origin && url.pathname.startsWith('/static/')) {
        event.respondWith((async () => {
            const cache = await caches.open(CACHE);
            const hit = await cache.match(request);
            if (hit) return hit;
            const response = await fetch(request);
            if (response.ok) cache.put(request, response.clone());
            return response;
        })());
    }
});

self.addEventListener('push', event => {
    let data = {};
    try {
        data = event.data ? event.data.json() : {};
    } catch (e) {
        data = { body: event.data ? event.data.text() : '' };
    }
    const shown = self.registration.showNotification(data.title || {{ site_name|tojson }}, {
        body: data.body || '',
        icon: ICON,
        badge: BADGE,
        tag: data.tag,
        renotify: Boolean(data.tag),
        data: { url: data.url || '/' },
    });
    const badge = (typeof data.badge === 'number' && self.navigator.setAppBadge)
        ? (data.badge > 0 ? self.navigator.setAppBadge(data.badge) : self.navigator.clearAppBadge()).catch(() => {})
        : Promise.resolve();
    event.waitUntil(Promise.all([shown, badge]));
});

self.addEventListener('notificationclick', event => {
    event.notification.close();
    const target = new URL(event.notification.data?.url || '/', self.location.origin);
    if (target.origin !== self.location.origin) return;
    event.waitUntil((async () => {
        const windows = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
        for (const client of windows) {
            try {
                await client.focus();
                await client.navigate(target.href);
                return;
            } catch (e) { /* not ours to steer; open a new window below */ }
        }
        await self.clients.openWindow(target.href);
    })());
});
