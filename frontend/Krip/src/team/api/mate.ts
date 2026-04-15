import client from './client';

// ─── Enums ───────────────────────────────────────────────
export type CompanionType = 'friend' | 'family' | 'couple' | 'sole';
export type PreferredGender = 'male' | 'female' | 'any';
export type Gender = 'male' | 'female';

// ─── Types ───────────────────────────────────────────────
export interface Author {
  user_name: string;
  age: number;
  gender: Gender;
  nationality: string;
}

export interface TripMatePost {
  post_id: string;
  user_id: string;
  author: Author;
  title: string;
  content: string;
  preferred_age_min: number;
  preferred_age_max: number;
  preferred_gender: PreferredGender;
  region: string;
  travel_start_date: string;
  travel_end_date: string;
  companion_type: CompanionType;
  is_displayed: boolean;
  created_at: string;
  updated_at: string;
  like_count: number;
  is_liked: boolean;
  image_urls: string[];
}

export interface PostListResponse {
  posts: TripMatePost[];
  next_cursor: string | null;
}

export interface CreateTripMateRequest {
  title: string;
  content: string;
  preferred_age_min: number;
  preferred_age_max: number;
  preferred_gender: PreferredGender;
  region: string;
  travel_start_date: string;
  travel_end_date: string;
  companion_type: CompanionType;
  image_urls?: string[] | null;  // 이미지 업로드 API로 받은 URL 목록 (선택)
}

export interface DraftData {
  user_id?: string;
  title?: string | null;
  content?: string | null;
  preferred_age_min?: number | null;
  preferred_age_max?: number | null;
  preferred_gender?: PreferredGender | null;
  region?: string | null;
  travel_start_date?: string | null;
  travel_end_date?: string | null;
  companion_type?: CompanionType | null;
  image_urls?: string[] | null;  // 임시저장 이미지 URL 목록
  updated_at?: string;
}

// ─── API Functions ───────────────────────────────────────

// 1. 게시글 목록 조회
export const getTripMatePosts = async (cursor?: string): Promise<PostListResponse> => {
  const params: Record<string, string> = {};
  if (cursor) params.cursor = cursor;
  const { data } = await client.get('/api/tripmate/posts', { params });
  return data;
};

// 2. 게시글 생성
export const createTripMatePost = async (body: CreateTripMateRequest): Promise<TripMatePost> => {
  const { data } = await client.post('/api/tripmate/posts', body);
  return data;
};

// 3. 게시글 검색
export const searchTripMatePosts = async (keyword: string, cursor?: string): Promise<PostListResponse> => {
  const params: Record<string, string> = { keyword };
  if (cursor) params.cursor = cursor;
  const { data } = await client.get('/api/tripmate/posts/search', { params });
  return data;
};

// 4. 게시글 단건 조회
export const getTripMatePost = async (postId: string): Promise<TripMatePost> => {
  const { data } = await client.get(`/api/tripmate/posts/${postId}`);
  return data;
};

// 5. 게시글 수정
export const updateTripMatePost = async (postId: string, body: CreateTripMateRequest): Promise<TripMatePost> => {
  const { data } = await client.put(`/api/tripmate/posts/${postId}`, body);
  return data;
};

// 6. 게시글 삭제
export const deleteTripMatePost = async (postId: string): Promise<void> => {
  await client.delete(`/api/tripmate/posts/${postId}`);
};

// 7. 게시글 표시 토글
export const toggleDisplay = async (postId: string): Promise<{ post_id: string; is_displayed: boolean }> => {
  const { data } = await client.patch(`/api/tripmate/posts/${postId}/display`);
  return data;
};

// 8-1. 좋아요 추가
export const addLike = async (postId: string): Promise<{ post_id: string; like_count: number }> => {
  const { data } = await client.post(`/api/tripmate/posts/${postId}/like`);
  return data;
};

// 8-2. 좋아요 취소
export const cancelLike = async (postId: string): Promise<{ post_id: string; like_count: number }> => {
  const { data } = await client.delete(`/api/tripmate/posts/${postId}/like`);
  return data;
};

// 8-3. 좋아요 유저 목록
export const getLikeUsers = async (postId: string): Promise<{ post_id: string; user_ids: string[] }> => {
  const { data } = await client.get(`/api/tripmate/posts/${postId}/likes`);
  return data;
};

// 9-1. 임시저장 저장/갱신
export const saveDraft = async (body: Partial<CreateTripMateRequest>): Promise<DraftData> => {
  const { data } = await client.put('/api/tripmate/posts/draft', body);
  return data;
};

// 9-2. 임시저장 조회
export const getDraft = async (): Promise<DraftData | null> => {
  try {
    const { data } = await client.get('/api/tripmate/posts/draft');
    return data;
  } catch {
    return null;
  }
};

// 9-3. 임시저장 삭제
export const deleteDraft = async (): Promise<void> => {
  await client.delete('/api/tripmate/posts/draft');
};

// ─── 좋아요 토글 헬퍼 ────────────────────────────────────
export const toggleLike = async (postId: string, currentlyLiked: boolean) => {
  if (currentlyLiked) {
    return await cancelLike(postId);
  } else {
    return await addLike(postId);
  }
};
