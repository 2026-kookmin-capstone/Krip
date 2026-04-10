const TOKEN_KEY = "krip_access_token";

export function saveToken(token) {
  if (!token) return;
  localStorage.setItem(TOKEN_KEY, token);
}

export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

export function removeToken() {
  localStorage.removeItem(TOKEN_KEY);
}

export function saveTokenFromParams(searchParams) {
  const token =
    searchParams.get("access_token") ||
    searchParams.get("token") ||
    searchParams.get("bearer_token");

  if (token) {
    saveToken(token);
  }

  return token;
}
