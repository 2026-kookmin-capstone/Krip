import client from "./client";

export type FriendshipStatus = "pending" | "accepted" | "rejected";
export type FriendGender = "male" | "female";

export interface FriendPeer {
  user_id: string;
  user_name: string;
  age: number;
  gender: FriendGender;
  nationality: string;
  profile_image_url: string | null;
}

export interface Friendship {
  friendship_id: string;
  status: FriendshipStatus;
  peer: FriendPeer;
  is_requester: boolean;
  created_at: string;
  updated_at: string;
}

export interface FriendshipListResponse {
  items: Friendship[];
  next_cursor: string | null;
}

export interface UserBlock {
  block_id: string;
  blocked: FriendPeer;
  created_at: string;
}

export interface UserBlockListResponse {
  items: UserBlock[];
  next_cursor: string | null;
}

export interface FriendDetail extends FriendPeer {
  travel_styles: string[];
  friendship_id: string | null;
  friendship_status: FriendshipStatus | null;
  is_requester: boolean | null;
  i_blocked_peer: boolean;
}

export interface FriendSearchUser {
  user_id: string;
  user_name: string;
  profile_image_url: string | null;
  nationality: string;
  travel_styles: string[];
  friendship_status: FriendshipStatus | null;
  is_requester: boolean | null;
  i_blocked_peer: boolean;
}

export interface FriendSearchResponse {
  items: FriendSearchUser[];
  next_cursor: string | null;
}

export interface FriendSearchHistoryItem {
  search_name: string;
  created_at: string;
}

export interface FriendSearchHistoryResponse {
  histories: FriendSearchHistoryItem[];
}

export interface MessageResponse {
  message: string;
}

function cursorParams(cursor?: string): { cursor?: string } {
  return cursor ? { cursor } : {};
}

export async function sendFriendRequest(addresseeId: string): Promise<Friendship> {
  const { data } = await client.post<Friendship>("/api/friend/friendships/requests", {
    addressee_id: addresseeId,
  });
  return data;
}

export async function getReceivedFriendRequests(
  cursor?: string
): Promise<FriendshipListResponse> {
  const { data } = await client.get<FriendshipListResponse>(
    "/api/friend/friendships/requests/received",
    { params: cursorParams(cursor) }
  );
  return data;
}

export async function getSentFriendRequests(
  cursor?: string
): Promise<FriendshipListResponse> {
  const { data } = await client.get<FriendshipListResponse>(
    "/api/friend/friendships/requests/sent",
    { params: cursorParams(cursor) }
  );
  return data;
}

export async function acceptFriendRequest(friendshipId: string): Promise<MessageResponse> {
  const { data } = await client.patch<MessageResponse>(
    `/api/friend/friendships/requests/${encodeURIComponent(friendshipId)}/accept`
  );
  return data;
}

export async function rejectFriendRequest(friendshipId: string): Promise<MessageResponse> {
  const { data } = await client.patch<MessageResponse>(
    `/api/friend/friendships/requests/${encodeURIComponent(friendshipId)}/reject`
  );
  return data;
}

export async function cancelFriendRequest(friendshipId: string): Promise<MessageResponse> {
  const { data } = await client.delete<MessageResponse>(
    `/api/friend/friendships/requests/${encodeURIComponent(friendshipId)}`
  );
  return data;
}

export async function getFriends(cursor?: string): Promise<FriendshipListResponse> {
  const { data } = await client.get<FriendshipListResponse>("/api/friend/friendships", {
    params: cursorParams(cursor),
  });
  return data;
}

export async function searchFriendUsers(
  keyword: string,
  cursor?: string
): Promise<FriendSearchResponse> {
  const { data } = await client.get<FriendSearchResponse>("/api/friend/search", {
    params: { keyword, ...cursorParams(cursor) },
  });
  return {
    items: Array.isArray(data.items) ? data.items : [],
    next_cursor: data.next_cursor ?? null,
  };
}

export async function getFriendSearchHistory(): Promise<FriendSearchHistoryResponse> {
  const { data } = await client.get<FriendSearchHistoryResponse>(
    "/api/friend/search/history"
  );
  return {
    histories: Array.isArray(data.histories) ? data.histories : [],
  };
}

export async function deleteFriendSearchHistoryOne(
  searchName: string
): Promise<MessageResponse> {
  const { data } = await client.delete<MessageResponse>(
    "/api/friend/search/history/one",
    { params: { search_name: searchName } }
  );
  return data;
}

export async function deleteFriendSearchHistoryAll(): Promise<MessageResponse> {
  const { data } = await client.delete<MessageResponse>("/api/friend/search/history");
  return data;
}

export async function deleteFriend(friendshipId: string): Promise<MessageResponse> {
  const { data } = await client.delete<MessageResponse>(
    `/api/friend/friendships/${encodeURIComponent(friendshipId)}`
  );
  return data;
}

export async function blockUser(targetUserId: string): Promise<UserBlock> {
  const { data } = await client.post<UserBlock>("/api/friend/blocks", {
    target_user_id: targetUserId,
  });
  return data;
}

export async function unblockUser(targetUserId: string): Promise<MessageResponse> {
  const { data } = await client.delete<MessageResponse>(
    `/api/friend/blocks/${encodeURIComponent(targetUserId)}`
  );
  return data;
}

export async function getBlockedUsers(cursor?: string): Promise<UserBlockListResponse> {
  const { data } = await client.get<UserBlockListResponse>("/api/friend/blocks", {
    params: cursorParams(cursor),
  });
  return data;
}

export async function getFriendDetail(userId: string): Promise<FriendDetail> {
  const { data } = await client.get<FriendDetail>(
    `/api/friend/detail/${encodeURIComponent(userId)}`
  );
  return data;
}
