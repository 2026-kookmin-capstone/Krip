import client from './client';

export type Gender = 'male' | 'female';

export interface UserProfile {
  user_id: string;
  email: string;
  user_name: string;
  phone_number?: string;
  age: number;
  gender: Gender;
  travel_styles: string[];
  nationality: string;
  created_at?: string;
}

export interface RegisterRequest {
  email: string;
  user_name: string;
  phone_number?: string;
  age: number;
  gender: Gender;
  travel_styles: string[];
  nationality: string;
}

/**
 * 내 프로필 전체 조회
 * GET /api/auth/profile/me
 */
export const getMyProfile = async (): Promise<UserProfile> => {
  const { data } = await client.get('/api/auth/profile/me');
  return data;
};

/**
 * 2차 회원가입
 * POST /api/auth/register
 */
export const register = async (body: RegisterRequest): Promise<void> => {
  await client.post('/api/auth/register', body);
};

/**
 * 로그아웃
 * POST /api/auth/logout
 */
export const logout = async (): Promise<void> => {
  await client.post('/api/auth/logout');
  localStorage.removeItem('accessToken');
};

/**
 * Google OAuth 로그인 시작 URL
 */
export const getGoogleLoginUrl = (isLocal = true) =>
  `${import.meta.env.VITE_API_URL}/api/auth/login?type=google&is_local=${isLocal}`;
