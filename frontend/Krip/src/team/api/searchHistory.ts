import client from './client';

export interface SearchHistoryItem {
  search_name: string;
  created_at: string;
}

export interface SearchHistoryResponse {
  histories: SearchHistoryItem[];
}

/**
 * 검색 기록 조회 (최신순, 최대 10개)
 * 검색 시 백엔드에서 자동 저장됨 (별도 저장 API 없음)
 */
export const getSearchHistory = async (): Promise<SearchHistoryResponse> => {
  const { data } = await client.get('/api/tripmate/search-history');
  return data;
};

/**
 * 검색어 단건 삭제
 */
export const deleteSearchHistoryOne = async (searchName: string): Promise<void> => {
  await client.delete('/api/tripmate/search-history/one', {
    params: { search_name: searchName },
  });
};

/**
 * 검색 기록 전체 삭제
 */
export const deleteSearchHistoryAll = async (): Promise<void> => {
  await client.delete('/api/tripmate/search-history');
};
