const LEGACY_TOKEN_KEY = import.meta.env.VITE_LEGACY_TOKEN_STORAGE_KEY || "";

export function readAccessToken(): string {
  const tokenKeys = ["accessToken", "token", "utk", LEGACY_TOKEN_KEY].filter(Boolean);

  for (const key of tokenKeys) {
    const token = localStorage.getItem(key);
    if (token) return token;
  }

  return "";
}

export function removeToken(): void {
  localStorage.removeItem("accessToken");
  localStorage.removeItem("token");
  localStorage.removeItem("utk");

  if (LEGACY_TOKEN_KEY) {
    localStorage.removeItem(LEGACY_TOKEN_KEY);
  }
}
