import axios from "axios";

import { API_BASE_URL, AUTHORIZATION_BEARER } from "./auth/config";

const client = axios.create({
  baseURL: API_BASE_URL,
  timeout: 10000,
  withCredentials: true,
});

client.interceptors.request.use((config) => {
  const token = localStorage.getItem("accessToken");
  const authorization = token ? `Bearer ${token}` : AUTHORIZATION_BEARER;
  if (authorization) {
    config.headers.Authorization = authorization;
  }
  return config;
});

client.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem("accessToken");
    }

    return Promise.reject(error);
  }
);

export default client;
