const LEGACY_TOKEN_KEY = import.meta.env.VITE_LEGACY_TOKEN_STORAGE_KEY || "";

export function removeToken(): void {
  if (!LEGACY_TOKEN_KEY) return;

  localStorage.removeItem(LEGACY_TOKEN_KEY);
}
