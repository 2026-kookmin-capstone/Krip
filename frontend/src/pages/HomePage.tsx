import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

const MOCK_SPOTS = [
  { id: 1, name: '경복궁', category: '역사', rating: 4.8, image: '🏯', address: '서울 종로구' },
  { id: 2, name: '광장시장', category: '음식', rating: 4.6, image: '🍜', address: '서울 종로구' },
  { id: 3, name: '홍대거리', category: '쇼핑', rating: 4.5, image: '🛍', address: '서울 마포구' },
  { id: 4, name: 'N서울타워', category: '관광', rating: 4.7, image: '🗼', address: '서울 용산구' },
  { id: 5, name: '북촌한옥마을', category: '역사', rating: 4.6, image: '🏘', address: '서울 종로구' },
  { id: 6, name: '명동거리', category: '쇼핑', rating: 4.4, image: '👗', address: '서울 중구' },
]

const CATEGORIES = ['전체', '역사', '음식', '쇼핑', '관광']

function HomePage() {
  const [search, setSearch] = useState('')
  const [selectedCategory, setSelectedCategory] = useState('전체')
  const navigate = useNavigate()

  const filtered = MOCK_SPOTS.filter((spot) => {
    const matchCategory = selectedCategory === '전체' || spot.category === selectedCategory
    const matchSearch = spot.name.includes(search) || spot.address.includes(search)
    return matchCategory && matchSearch
  })

  return (
    <div className="max-w-md mx-auto bg-gray-50 min-h-screen">
      <div className="bg-white px-4 pt-6 pb-4 shadow-sm">
        <h1 className="text-2xl font-bold text-gray-800 mb-1">🗺 Krip</h1>
        <p className="text-sm text-gray-500">서울의 숨겨진 명소를 찾아보세요</p>
        <div className="mt-3 relative">
          <input
            type="text"
            placeholder="관광지, 주소 검색..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full pl-10 pr-4 py-2 border border-gray-200 rounded-full text-sm focus:outline-none focus:border-blue-400"
          />
          <span className="absolute left-3 top-2 text-gray-400">🔍</span>
        </div>
      </div>

      <div className="flex gap-2 px-4 py-3 overflow-x-auto bg-white border-b">
        {CATEGORIES.map((cat) => (
          <button
            key={cat}
            onClick={() => setSelectedCategory(cat)}
            className={
              'px-4 py-1.5 rounded-full text-sm whitespace-nowrap font-medium transition-colors ' +
              (selectedCategory === cat ? 'bg-blue-500 text-white' : 'bg-gray-100 text-gray-600')
            }
          >
            {cat}
          </button>
        ))}
      </div>

      <div className="px-4 py-3 space-y-3">
        {filtered.length === 0 ? (
          <div className="text-center py-16 text-gray-400">
            <p className="text-4xl mb-2">😅</p>
            <p>검색 결과가 없어요</p>
          </div>
        ) : (
          filtered.map((spot) => (
            <div
              key={spot.id}
              onClick={() => navigate(`/spots/${spot.id}`)}
              className="bg-white rounded-2xl p-4 shadow-sm flex items-center gap-4 cursor-pointer"
            >
              <div className="w-16 h-16 bg-blue-50 rounded-xl flex items-center justify-center text-3xl flex-shrink-0">
                {spot.image}
              </div>
              <div className="flex-1">
                <div className="flex items-center justify-between">
                  <h3 className="font-semibold text-gray-800">{spot.name}</h3>
                  <span className="text-yellow-500 text-sm">⭐ {spot.rating}</span>
                </div>
                <p className="text-xs text-gray-400 mt-0.5">{spot.address}</p>
                <span className="inline-block mt-1.5 px-2 py-0.5 bg-blue-50 text-blue-500 text-xs rounded-full">
                  {spot.category}
                </span>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  )
}

export default HomePage