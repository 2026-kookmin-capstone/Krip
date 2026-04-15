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

export const getMyProfile = async (): Promise<UserProfile> => {
  const { data } = await client.get('/api/auth/profile/me');
  return data;
};

export const register = async (body: RegisterRequest): Promise<void> => {
  await client.post('/api/auth/register', body);
};

export const logout = async (): Promise<void> => {
  await client.post('/api/auth/logout');
  localStorage.removeItem('accessToken');
};

export const getGoogleLoginUrl = (isLocal = true) =>
  `${import.meta.env.VITE_API_URL}/api/auth/login?type=google&is_local=${isLocal}`;
