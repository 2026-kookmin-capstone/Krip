import {
  deleteTourSearchHistoryAll,
  deleteTourSearchHistoryOne,
  getTourSearchHistory,
  type SearchHistoryResponse,
} from "./auth/auth";

export function getSearchHistory(): Promise<SearchHistoryResponse> {
  return getTourSearchHistory();
}

export function deleteSearchHistoryOne(
  searchName: string
): Promise<Record<string, unknown> | null> {
  return deleteTourSearchHistoryOne(searchName);
}

export function deleteSearchHistoryAll(): Promise<Record<string, unknown> | null> {
  return deleteTourSearchHistoryAll();
}
