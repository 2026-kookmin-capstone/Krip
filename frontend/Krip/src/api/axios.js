import axios from "axios";
import { getToken, removeToken } from "../utils/token";

const api = axios.create({
  baseURL: "https://back.krip.site",
  headers: {
    "Content-Type": "application/json",
  },
});

// 요청 인터셉터 추가
api.interceptors.request.use(
  (config) => {
    const token = getToken();

    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }

    return config;
  },
  (error) => Promise.reject(error)
);

// 응답 인터셉터 추가
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      console.log("토큰 만료 or 인증 실패");

      // 토큰 삭제
      removeToken();

      // 로그인 페이지로 이동
      window.location.href = "/login";
    }

    return Promise.reject(error);
  }
);

export default api;