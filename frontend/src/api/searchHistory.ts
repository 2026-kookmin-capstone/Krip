import client from "./client";
import type { SearchHistoryResponse } from "./auth/auth";

export async function getSearchHistory(): Promise<SearchHistoryResponse> {
  const { data } = await client.get<SearchHistoryResponse>(
    "/api/tripmate/search-history"
  );
  return {
    histories: Array.isArray(data.histories) ? data.histories : [],
  };
}

export async function deleteSearchHistoryOne(
  searchName: string
): Promise<Record<string, unknown>> {
  const { data } = await client.delete<Record<string, unknown>>(
    "/api/tripmate/search-history/one",
    { params: { search_name: searchName } }
  );
  return data;
}

export async function deleteSearchHistoryAll(): Promise<Record<string, unknown>> {
  const { data } = await client.delete<Record<string, unknown>>(
    "/api/tripmate/search-history"
  );
  return data;
}
