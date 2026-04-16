import { useParams, useNavigate } from 'react-router-dom'

const MOCK_SPOTS = [
  { id: 1, name: '경복궁', category: '역사', rating: 4.8, image: '🏯', address: '서울 종로구', description: '조선시대 대표 궁궐로, 서울의 상징적인 역사 유적지입니다.' },
  { id: 2, name: '광장시장', category: '음식', rating: 4.6, image: '🍜', address: '서울 종로구', description: '100년 역사의 전통시장. 빈대떡, 마약김밥이 유명합니다.' },
  { id: 3, name: '홍대거리', category: '쇼핑', rating: 4.5, image: '🛍', address: '서울 마포구', description: '젊음과 예술의 거리. 개성 넘치는 카페와 빈티지 숍이 가득합니다.' },
  { id: 4, name: 'N서울타워', category: '관광', rating: 4.7, image: '🗼', address: '서울 용산구', description: '서울 전경을 한눈에 볼 수 있는 랜드마크입니다.' },
  { id: 5, name: '북촌한옥마을', category: '역사', rating: 4.6, image: '🏘', address: '서울 종로구', description: '전통 한옥이 즐비한 골목. 한복 대여 후 인생샷 명소입니다.' },
  { id: 6, name: '명동거리', category: '쇼핑', rating: 4.4, image: '👗', address: '서울 중구', description: '서울 최대 쇼핑 거리. 화장품, 패션, 길거리 음식이 가득합니다.' },
]

function SpotDetailPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const spot = MOCK_SPOTS.find((s) => s.id === Number(id))

  if (!spot) {
    return (
      <div className="flex items-center justify-center h-screen">
        <p className="text-gray-400">관광지를 찾을 수 없어요 😅</p>
      </div>
    )
  }

  return (
    <div className="max-w-md mx-auto bg-white min-h-screen">
      <div className="bg-blue-50 h-56 flex items-center justify-center text-8xl relative">
        {spot.image}
        <button
          onClick={() => navigate(-1)}
          className="absolute top-4 left-4 bg-white rounded-full w-10 h-10 flex items-center justify-center shadow-md text-gray-600 text-lg"
        >
          ←
        </button>
      </div>

      <div className="px-5 py-5">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-bold text-gray-800">{spot.name}</h1>
          <span className="text-yellow-500 font-semibold">⭐ {spot.rating}</span>
        </div>
        <p className="text-gray-400 text-sm mt-1">📍 {spot.address}</p>
        <span className="inline-block mt-2 px-3 py-1 bg-blue-50 text-blue-500 text-sm rounded-full">
          {spot.category}
        </span>
        <div className="mt-5">
          <h2 className="font-semibold text-gray-700 mb-2">소개</h2>
          <p className="text-gray-600 text-sm leading-relaxed">{spot.description}</p>
        </div>
      </div>
    </div>
  )
}

export default SpotDetailPage