const KEY = 'krip_search_history';

export const getHistory = (): string[] => {
  try {
    return JSON.parse(localStorage.getItem(KEY) || '[]');
  } catch {
    return [];
  }
};

export const addHistory = (term: string) => {
  if (!term.trim()) return;
  const prev = getHistory().filter((h) => h !== term); // 중복 제거
  const next = [term, ...prev].slice(0, 10); // 최신순 + 최대 10개
  localStorage.setItem(KEY, JSON.stringify(next));
};

export const removeHistory = (term: string) => {
  const next = getHistory().filter((h) => h !== term);
  localStorage.setItem(KEY, JSON.stringify(next));
};

export const clearHistory = () => {
  localStorage.removeItem(KEY);
};