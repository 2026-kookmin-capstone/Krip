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

  self.registration.showNotification(title, options);
});
