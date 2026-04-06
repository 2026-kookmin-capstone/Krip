import { getToken, removeToken } from "../../utils/tokens";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "https://back.krip.site";

function getAuthHeaders(headers = {}) {
  const token = getToken();

  return token
    ? {
        ...headers,
        Authorization: `Bearer ${token}`,
      }
    : headers;
}

async function authRequest(path, options = {}) {
  const { headers, ...rest } = options;
  const response = await fetch(`${API_BASE_URL}${path}`, {
    credentials: "include",
    headers: getAuthHeaders(headers),
    ...rest,
  });

  if (response.ok) {
    if (response.status === 204) {
      return null;
    }

    const contentType = response.headers.get("content-type") || "";
    return contentType.includes("application/json") ? response.json() : null;
  }

  let detail = "요청 처리 중 오류가 발생했습니다.";

  try {
    const data = await response.json();
    detail = data.detail || data.message || detail;
  } catch {
    // JSON 응답이 아니면 기본 메시지를 유지한다.
  }

  if (response.status === 401) {
    removeToken();
  }

  const error = new Error(detail);
  error.status = response.status;
  throw error;
}

export function createLoginUrl() {
  const url = new URL("/api/auth/login", API_BASE_URL);
  url.searchParams.set("type", "google");

  const isLocalHost =
    window.location.hostname === "localhost" ||
    window.location.hostname === "127.0.0.1";

  if (isLocalHost) {
    url.searchParams.set("is_local", "true");
  }

  return url.toString();
}

export function registerUser(payload) {
  return authRequest("/api/auth/register", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
}

export function logoutUser() {
  return authRequest("/api/auth/logout", {
    method: "POST",
  });
}

export function getMyProfile() {
  return authRequest("/api/auth/profile/me");
}
