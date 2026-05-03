import { getMessaging, getToken, isSupported, onMessage } from "firebase/messaging";

import client from "../api/client";
import { firebaseApp } from "./firebase";

const FCM_TOKEN_STORAGE_KEY = "FCMtoken";
let fcmTokenRegistrationPromise: Promise<string | null> | null = null;

async function issueAndRegisterFcmToken(): Promise<string | null> {
  const vapidKey = import.meta.env.VITE_FIREBASE_VAPID_KEY;
  if (!vapidKey || !("Notification" in window)) {
    return null;
  }

  const supported = await isSupported();
  if (!supported) {
    return null;
  }

  if (Notification.permission !== "granted") {
    return null;
  }

  const messaging = getMessaging(firebaseApp);
  const currentToken = await getToken(messaging, {
    vapidKey,
  });

  if (!currentToken) {
    return null;
  }

  const storedToken = localStorage.getItem(FCM_TOKEN_STORAGE_KEY);
  localStorage.setItem(FCM_TOKEN_STORAGE_KEY, currentToken);

  if (storedToken === currentToken) {
    return currentToken;
  }

  try {
    await client.post("/notification/new", {
      token: currentToken,
    });
  } catch (error) {
    console.warn("Failed to save FCM token to backend", error);
  }

  return currentToken;
}

export function registerFcmToken(): Promise<string | null> {
  if (!fcmTokenRegistrationPromise) {
    fcmTokenRegistrationPromise = issueAndRegisterFcmToken().finally(() => {
      fcmTokenRegistrationPromise = null;
    });
  }

  return fcmTokenRegistrationPromise;
}

export async function requestPermission(): Promise<void> {
  if (!("Notification" in window) || Notification.permission !== "default") {
    return;
  }

  try {
    const permission = await Notification.requestPermission();

    if (permission === "granted") {
      console.log("Push permission granted");
      await registerFcmToken();
      return;
    }

    if (permission === "denied") {
      console.log("Push permission denied");
    }
  } catch (error) {
    console.log("Error while requesting push permission", error);
  }
}

export async function listenForegroundMessages(): Promise<void> {
  const supported = await isSupported();
  if (!supported) {
    return;
  }

  const messaging = getMessaging(firebaseApp);
  onMessage(messaging, (payload) => {
    console.log("Received foreground notification:", payload);
  });
}
