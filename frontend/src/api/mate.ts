import client from "./client";

export type CompanionType = "friend" | "family" | "couple" | "sole";
export type PreferredGender = "male" | "female" | "any";
export type Gender = "male" | "female";

export interface Author {
  user_name: string;
  age: number;
  gender: Gender;
  nationality: string;
}

export interface TripMatePost {
  post_id: string;
  user_id: string;
  profile_image_url: string | null;
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
  image_urls?: string[] | null;
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
  image_urls?: string[] | null;
  updated_at?: string;
}

function cursorParams(cursor?: string): { cursor?: string } {
  return cursor ? { cursor } : {};
}

export async function getTripMatePosts(cursor?: string): Promise<PostListResponse> {
  const { data } = await client.get<PostListResponse>("/api/tripmate/posts", {
    params: cursorParams(cursor),
  });
  return data;
}

export async function searchTripMatePosts(
  keyword: string,
  cursor?: string
): Promise<PostListResponse> {
  const { data } = await client.get<PostListResponse>("/api/tripmate/posts/search", {
    params: { keyword, ...cursorParams(cursor) },
  });
  return data;
}

export async function createTripMatePost(
  body: CreateTripMateRequest
): Promise<TripMatePost> {
  const { data } = await client.post<TripMatePost>("/api/tripmate/posts", body);
  return data;
}

export async function updateTripMatePost(
  postId: string,
  body: CreateTripMateRequest
): Promise<TripMatePost> {
  const { data } = await client.put<TripMatePost>(
    `/api/tripmate/posts/${encodeURIComponent(postId)}`,
    body
  );
  return data;
}

export async function getTripMatePost(postId: string): Promise<TripMatePost> {
  const { data } = await client.get<TripMatePost>(
    `/api/tripmate/posts/${encodeURIComponent(postId)}`
  );
  return data;
}

export async function deleteTripMatePost(postId: string): Promise<void> {
  await client.delete(`/api/tripmate/posts/${encodeURIComponent(postId)}`);
}

export async function toggleLike(
  postId: string,
  currentlyLiked: boolean
): Promise<{ post_id: string; like_count: number }> {
  const path = `/api/tripmate/posts/${encodeURIComponent(postId)}/like`;
  const { data } = currentlyLiked
    ? await client.delete<{ post_id: string; like_count: number }>(path)
    : await client.post<{ post_id: string; like_count: number }>(path);
  return data;
}

export async function saveDraft(
  body: Partial<CreateTripMateRequest>
): Promise<DraftData> {
  const { data } = await client.put<DraftData>("/api/tripmate/posts/draft", body);
  return data;
}

export async function getDraft(): Promise<DraftData | null> {
  try {
    const { data } = await client.get<DraftData>("/api/tripmate/posts/draft");
    return data;
  } catch {
    return null;
  }
}

export async function deleteDraft(): Promise<void> {
  await client.delete("/api/tripmate/posts/draft");
}
