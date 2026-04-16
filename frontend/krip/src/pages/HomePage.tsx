import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { getHistory, addHistory, removeHistory, clearHistory } from '../utils/searchHistory';

interface Spot {
  id: number;
  name: string;
  category: string;
  address: string;
  rating: number;
  emoji: string;
  isHot?: boolean;
}

const MOCK_SPOTS: Spot[] = [
  { id: 1, name: '경복궁', category: '관광지', address: '서울 종로구', rating: 4.8, emoji: '🏯', isHot: true },
  { id: 2, name: '광장시장', category: '음식', address: '서울 종로구', rating: 4.6, emoji: '🍜', isHot: true },
  { id: 3, name: '한강공원', category: '공원', address: '서울 영등포구', rating: 4.7, emoji: '🌊' },
  { id: 4, name: '북촌한옥마을', category: '관광지', address: '서울 종로구', rating: 4.5, emoji: '🏘️' },
  { id: 5, name: '명동', category: '쇼핑', address: '서울 중구', rating: 4.3, emoji: '🛍️' },
  { id: 6, name: '이태원', category: '음식', address: '서울 용산구', rating: 4.4, emoji: '🍔' },
  { id: 7, name: '홍대', category: '문화', address: '서울 마포구', rating: 4.5, emoji: '🎨', isHot: true },
  { id: 8, name: '남산타워', category: '관광지', address: '서울 용산구', rating: 4.7, emoji: '🗼' },
];

const CATEGORIES = [
  { label: '관광지', emoji: '🏯' },
  { label: '음식', emoji: '🍜' },
  { label: '쇼핑', emoji: '🛍️' },
  { label: '문화', emoji: '🎨' },
];

export default function HomePage() {
  const navigate = useNavigate();
  const [search, setSearch] = useState('');
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null);
  const [focused, setFocused] = useState(false);
  const [history, setHistory] = useState<string[]>(getHistory());

  const hotSpots = MOCK_SPOTS.filter((s) => s.isHot);

  const filtered = MOCK_SPOTS.filter((s) => {
    const matchSearch =
      search === '' ||
      s.name.includes(search) ||
      s.address.includes(search) ||
      s.category.includes(search);
    const matchCategory = !selectedCategory || s.category === selectedCategory;
    return matchSearch && matchCategory;
  });

  const isSearching = search !== '' || selectedCategory !== null;
  const showHistory = focused && search === '' && history.length > 0;

  const handleSearch = (term: string) => {
    if (!term.trim()) return;
    addHistory(term);
    setHistory(getHistory());
    setSearch(term);
    setFocused(false);
  };

  const handleRemove = (term: string) => {
    removeHistory(term);
    setHistory(getHistory());
  };

  const handleClear = () => {
    clearHistory();
    setHistory([]);
  };

  return (
    <div className="min-h-screen bg-gray-50 pb-20">
      {/* 헤더 */}
      <div className="bg-white px-4 pt-10 pb-4">
        <h1 className="text-2xl font-bold text-gray-900 mb-1">🗺️ Krip</h1>
        <p className="text-sm text-gray-400">서울 여행을 즐겨보세요!</p>
      </div>

      {/* 검색바 */}
      <div className="bg-white px-4 pb-3 border-b relative">
        <div className="flex items-center bg-gray-100 rounded-full px-4 py-2.5 gap-2">
          <span className="text-gray-400">🔍</span>
          <input
            type="text"
            placeholder="장소, 음식, 지역 검색"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onFocus={() => setFocused(true)}
            onBlur={() => setTimeout(() => setFocused(false), 150)}
            onKeyDown={(e) => { if (e.key === 'Enter') handleSearch(search); }}
            className="flex-1 bg-transparent text-sm outline-none text-gray-700 placeholder-gray-400"
          />
          {search && (
            <button onClick={() => setSearch('')} className="text-gray-400 text-xs">✕</button>
          )}
        </div>

        {/* 최근 검색 기록 드롭다운 */}
        {showHistory && (
          <div className="absolute left-0 right-0 top-full bg-white border-t shadow-lg z-30 px-4 py-2">
            <div className="flex justify-between items-center mb-2">
              <span className="text-xs text-gray-400 font-medium">최근 검색</span>
              <button onClick={handleClear} className="text-xs text-blue-500">전체 삭제</button>
            </div>
            {history.map((term) => (
              <div
                key={term}
                className="flex items-center justify-between py-2 border-b border-gray-50 last:border-0"
              >
                <button
                  onMouseDown={() => handleSearch(term)}
                  className="flex items-center gap-2 flex-1 text-left"
                >
                  <span className="text-gray-300">🕐</span>
                  <span className="text-sm text-gray-700">{term}</span>
                </button>
                <button
                  onMouseDown={() => handleRemove(term)}
                  className="text-gray-300 text-xs px-1"
                >
                  ✕
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* 검색/필터 결과 */}
      {isSearching ? (
        <div className="p-4 space-y-3">
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm font-medium text-gray-700">
              {'검색 결과 ' + filtered.length + '개'}
            </span>
            <button
              onClick={() => { setSearch(''); setSelectedCategory(null); }}
              className="text-xs text-blue-500"
            >
              초기화
            </button>
          </div>
          {filtered.length === 0 && (
            <div className="text-center py-12 text-gray-400 text-sm">검색 결과가 없어요</div>
          )}
          {filtered.map((spot) => (
            <div
              key={spot.id}
              onClick={() => { handleSearch(search); navigate('/spots/' + spot.id); }}
              className="bg-white rounded-xl p-4 shadow-sm flex items-center gap-3 cursor-pointer active:bg-gray-50"
            >
              <div className="w-12 h-12 bg-gray-100 rounded-xl flex items-center justify-center text-2xl flex-shrink-0">
                {spot.emoji}
              </div>
              <div className="flex-1">
                <div className="font-semibold text-gray-900">{spot.name}</div>
                <div className="text-xs text-gray-400">{spot.address}</div>
              </div>
              <div className="text-sm text-yellow-500 font-medium">⭐ {spot.rating}</div>
            </div>
          ))}
        </div>
      ) : (
        <div className="p-4 space-y-6">
          {/* 2×2 카테고리 그리드 */}
          <div>
            <h2 className="text-base font-bold text-gray-900 mb-3">카테고리</h2>
            <div className="grid grid-cols-2 gap-3">
              {CATEGORIES.map((cat) => (
                <button
                  key={cat.label}
                  onClick={() => setSelectedCategory(cat.label)}
                  className="bg-white rounded-2xl shadow-sm p-5 flex flex-col items-center gap-2 active:bg-gray-50"
                >
                  <span className="text-4xl">{cat.emoji}</span>
                  <span className="text-sm font-medium text-gray-700">{cat.label}</span>
                </button>
              ))}
            </div>
          </div>

          {/* HOT PLACE */}
          <div>
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-base font-bold text-gray-900">🔥 HOT PLACE</h2>
              <button className="text-xs text-blue-500">전체보기</button>
            </div>
            <div className="space-y-3">
              {hotSpots.map((spot) => (
                <div
                  key={spot.id}
                  onClick={() => navigate('/spots/' + spot.id)}
                  className="bg-white rounded-2xl shadow-sm overflow-hidden cursor-pointer active:bg-gray-50"
                >
                  <div className="h-32 bg-gradient-to-br from-blue-100 to-purple-100 flex items-center justify-center text-5xl">
                    {spot.emoji}
                  </div>
                  <div className="p-3 flex justify-between items-center">
                    <div>
                      <div className="font-semibold text-gray-900 text-sm">{spot.name}</div>
                      <div className="text-xs text-gray-400 mt-0.5">{spot.address}</div>
                    </div>
                    <div className="text-sm text-yellow-500 font-medium">⭐ {spot.rating}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}