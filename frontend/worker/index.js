import { precacheAndRoute } from 'workbox-precaching';
import { clientsClaim } from 'workbox-core';
import { StaleWhileRevalidate, CacheFirst } from 'workbox-strategies';
import { registerRoute } from 'workbox-routing';
import { CacheableResponsePlugin } from 'workbox-cacheable-response';
import { ExpirationPlugin } from 'workbox-expiration';
import { BackgroundSyncPlugin } from 'workbox-background-sync';

// Precache all Next.js build artifacts
precacheAndRoute(self.__WB_MANIFEST);

self.skipWaiting();
clientsClaim();

// Background sync for task operations when offline
const taskSyncPlugin = new BackgroundSyncPlugin('task-sync', {
  maxRetentionTime: 24 * 60, // 24 hours in minutes
});

registerRoute(
  ({ url }) => url.pathname.startsWith('/api/v1/tasks'),
  new StaleWhileRevalidate({
    cacheName: 'tasks-api',
    plugins: [
      new CacheableResponsePlugin({ statuses: [0, 200] }),
      new ExpirationPlugin({ maxEntries: 50, maxAgeSeconds: 24 * 60 * 60 }),
      taskSyncPlugin,
    ],
  }),
  'POST'
);

registerRoute(
  ({ url }) => url.pathname.startsWith('/api/v1/tasks'),
  new StaleWhileRevalidate({
    cacheName: 'tasks-api',
    plugins: [
      new CacheableResponsePlugin({ statuses: [0, 200] }),
      new ExpirationPlugin({ maxEntries: 50, maxAgeSeconds: 24 * 60 * 60 }),
      taskSyncPlugin,
    ],
  }),
  'PUT'
);

registerRoute(
  ({ url }) => url.pathname.startsWith('/api/v1/tasks'),
  new StaleWhileRevalidate({
    cacheName: 'tasks-api',
    plugins: [
      new CacheableResponsePlugin({ statuses: [0, 200] }),
      new ExpirationPlugin({ maxEntries: 50, maxAgeSeconds: 24 * 60 * 60 }),
    ],
  }),
  'DELETE'
);

registerRoute(
  ({ url }) => url.pathname.startsWith('/api/v1/tasks'),
  new StaleWhileRevalidate({
    cacheName: 'tasks-api',
    plugins: [
      new CacheableResponsePlugin({ statuses: [0, 200] }),
      new ExpirationPlugin({ maxEntries: 50, maxAgeSeconds: 60 * 60 }),
    ],
  }),
  'GET'
);

// Push event handler for task alarms
self.addEventListener('push', (event) => {
  let data = {};
  try {
    data = event.data?.json() || {};
  } catch {
    data = { title: 'SOWKNOW', body: event.data?.text() || '' };
  }

  const title = data.title || 'SOWKNOW';
  const options = {
    body: data.body || 'You have a task alarm',
    icon: '/icon-192x192.png',
    badge: '/icon-72x72.png',
    tag: data.data?.tag || 'sowknow-task',
    requireInteraction: true,
    data: data.data || {},
  };

  event.waitUntil(self.registration.showNotification(title, options));
});

// Notification click handler
self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const notificationData = event.notification.data || {};

  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
      const targetUrl = notificationData.taskId
        ? `/tasks/${notificationData.taskId}`
        : '/tasks';

      // Focus existing window if open
      for (const client of clientList) {
        if (client.url.includes(targetUrl) && 'focus' in client) {
          return client.focus();
        }
      }
      // Otherwise open new window
      if (self.clients.openWindow) {
        return self.clients.openWindow(targetUrl);
      }
    })
  );
});
