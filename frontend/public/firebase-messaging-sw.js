/* global importScripts, firebase */

importScripts("https://www.gstatic.com/firebasejs/12.12.1/firebase-app-compat.js");
importScripts("https://www.gstatic.com/firebasejs/12.12.1/firebase-messaging-compat.js");

loadFirebaseMessaging();

async function loadFirebaseMessaging() {
  try {
    const response = await fetch("/firebase-config.json", { cache: "no-store" });
    if (!response.ok) return;

    const config = await response.json();
    if (!isFirebaseConfigReady(config)) return;

    firebase.initializeApp(config);
    const messaging = firebase.messaging();

    messaging.onBackgroundMessage((payload) => {
      const notification = payload.notification || {};
      const title = notification.title || "Krip";
      const options = {
        body: notification.body,
        icon: "/favicon.png",
        data: payload.data,
      };

      self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clients) => {
        clients.forEach((client) => {
          client.postMessage({
            type: "KRIP_FCM_BACKGROUND_MESSAGE",
            payload,
          });
        });
      });

      self.registration.showNotification(title, options);
    });
  } catch {
    // Background web push stays disabled when the ignored local config is absent.
  }
}

function isFirebaseConfigReady(config) {
  return Boolean(config?.apiKey && config?.projectId && config?.messagingSenderId && config?.appId);
}

self.addEventListener("notificationclick", (event) => {
  event.notification.close();

  const targetUrl = event.notification.data?.url || "/mate";
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clients) => {
      const existingClient = clients.find((client) => "focus" in client);
      if (existingClient) {
        existingClient.postMessage({
          type: "KRIP_FCM_BACKGROUND_MESSAGE",
          payload: {
            notification: {
              title: event.notification.title,
              body: event.notification.body,
            },
            data: event.notification.data || {},
          },
        });
        return existingClient.focus();
      }

      return self.clients.openWindow(targetUrl);
    })
  );
});
