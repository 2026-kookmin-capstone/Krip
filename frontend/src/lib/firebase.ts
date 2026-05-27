import { initializeApp } from "firebase/app";
import { getAnalytics, isSupported, type Analytics } from "firebase/analytics";

function readFirebaseEnv(value: string | undefined): string {
  return value?.trim() ?? "";
}

export const firebaseConfig = {
  apiKey: readFirebaseEnv(import.meta.env.VITE_FIREBASE_API_KEY),
  authDomain: readFirebaseEnv(import.meta.env.VITE_FIREBASE_AUTH_DOMAIN),
  projectId: readFirebaseEnv(import.meta.env.VITE_FIREBASE_PROJECT_ID),
  storageBucket: readFirebaseEnv(import.meta.env.VITE_FIREBASE_STORAGE_BUCKET),
  messagingSenderId: readFirebaseEnv(import.meta.env.VITE_FIREBASE_MESSAGING_SENDER_ID),
  appId: readFirebaseEnv(import.meta.env.VITE_FIREBASE_APP_ID),
  measurementId: readFirebaseEnv(import.meta.env.VITE_FIREBASE_MEASUREMENT_ID),
};

export const firebaseApp = initializeApp(firebaseConfig);

export const firebaseAnalytics: Promise<Analytics | null> =
  firebaseConfig.apiKey && firebaseConfig.appId
    ? isSupported()
        .then((supported) => (supported ? getAnalytics(firebaseApp) : null))
        .catch(() => null)
    : Promise.resolve(null);
