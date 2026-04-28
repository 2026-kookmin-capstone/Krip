/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
  readonly VITE_AUTHORIZATION_BEARER?: string;
  readonly VITE_TOUR_PLACES_AUTHORIZATION_BEARER?: string;
  readonly VITE_AUTH_IS_LOCAL?: string;
  readonly VITE_KAKAO_JS_KEY?: string;
  readonly VITE_LEGACY_TOKEN_STORAGE_KEY?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
