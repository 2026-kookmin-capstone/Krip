/* global importScripts, firebase */

importScripts("https://www.gstatic.com/firebasejs/12.12.1/firebase-app-compat.js");
importScripts("https://www.gstatic.com/firebasejs/12.12.1/firebase-messaging-compat.js");

firebase.initializeApp({
  apiKey: "AIzaSyCNhoADPVfV74tbb9WI9i2eJha7RY4FsyM",
  authDomain: "krip-a4d7d.firebaseapp.com",
  projectId: "krip-a4d7d",
  storageBucket: "krip-a4d7d.firebasestorage.app",
  messagingSenderId: "149172625115",
  appId: "1:149172625115:web:6a337f849a08826243f6fe",
  measurementId: "G-KVHM5PW0MC",
});

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
