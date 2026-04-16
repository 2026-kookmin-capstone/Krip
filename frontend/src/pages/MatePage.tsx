import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

const MOCK_MATES = [
  { id: 1, name: 'Sarah', country: '🇺🇸 미국', destination: '홍대, 이태원', date: '4/15', members: '1/2', tags: ['쇼핑', '맛집'] },
  { id: 2, name: 'Kenji', country: '🇯🇵 일본', destination: '경복궁, 북촌', date: '4/17', members: '2/3', tags: ['역사', '사진'] },
  { id: 3, name: 'Emma', country: '🇬🇧 영국', destination: '명동, 남산', date: '4/20', members: '1/4', tags: ['관광', '음식'] },
  { id: 4, name: 'Lucas', country: '🇫🇷 프랑스', destination: '인사동, 광장시장', date: '4/22', members: '2/3', tags: ['문화', '맛집'] },
]

function MatePage() {
  const [tab, setTab] = useState<'list' | 'write'>('list')
  const navigate = useNavigate()

  return (
    <div className="max-w-md mx-auto bg-gray-50 min-h-screen">
      {/* 헤더 */}
      <div className="bg-white px-4 pt-6 pb-0 shadow-sm">
        <h1 className="text-2xl font-bold text-gray-800">👫 여행 메이트</h1>
        <p className="text-sm text-gray-500 mt-1">함께 서울을 여행할 메이트를 찾아보세요</p>

        {/* 탭 */}
        <div className="flex mt-4">
          <button
            onClick={() => setTab('list')}
            className={'flex-1 py-2.5 text-sm font-semibold border-b-2 ' +
              (tab === 'list' ? 'border-blue-500 text-blue-500' : 'border-transparent text-gray-400')}
          >
            메이트 찾기
          </button>
          <button
            onClick={() => setTab('write')}
            className={'flex-1 py-2.5 text-sm font-semibold border-b-2 ' +
              (tab === 'write' ? 'border-blue-500 text-blue-500' : 'border-transparent text-gray-400')}
          >
            모집 글 작성
          </button>
        </div>
      </div>

      {/* 메이트 목록 */}
      {tab === 'list' && (
        <div className="px-4 py-4 space-y-3">
          {MOCK_MATES.map((mate) => (
            <div
              key={mate.id}
              onClick={() => navigate('/mate/' + mate.id)}
              className="bg-white rounded-2xl p-4 shadow-sm cursor-pointer"
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 bg-blue-100 rounded-full flex items-center justify-center text-lg">
                    {mate.country.split(' ')[0]}
                  </div>
                  <div>
                    <p className="font-semibold text-gray-800">{mate.name}</p>
                    <p className="text-xs text-gray-400">{mate.country.split(' ')[1]}</p>
                  </div>
                </div>
                <span className="text-xs text-gray-400">{mate.members} 명</span>
              </div>

              <div className="mt-3">
                <p className="text-sm text-gray-700">📍 {mate.destination}</p>
                <p className="text-sm text-gray-400 mt-0.5">📅 {mate.date}</p>
              </div>

              <div className="flex gap-1.5 mt-2.5 flex-wrap">
                {mate.tags.map((tag) => (
                  <span key={tag} className="px-2 py-0.5 bg-blue-50 text-blue-500 text-xs rounded-full">
                    #{tag}
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* 글 작성 폼 */}
      {tab === 'write' && (
        <div className="px-4 py-4 space-y-4">
          <div className="bg-white rounded-2xl p-4 shadow-sm space-y-4">

            <div>
              <label className="text-sm font-medium text-gray-700">목적지</label>
              <input
                type="text"
                placeholder="예: 홍대, 강남"
                className="w-full mt-1.5 px-3 py-2.5 border border-gray-200 rounded-xl text-sm focus:outline-none focus:border-blue-400"
              />
            </div>

            <div>
              <label className="text-sm font-medium text-gray-700">여행 날짜</label>
              <input
                type="date"
                className="w-full mt-1.5 px-3 py-2.5 border border-gray-200 rounded-xl text-sm focus:outline-none focus:border-blue-400"
              />
            </div>

            <div>
              <label className="text-sm font-medium text-gray-700">모집 인원</label>
              <select className="w-full mt-1.5 px-3 py-2.5 border border-gray-200 rounded-xl text-sm focus:outline-none focus:border-blue-400">
                <option>2명</option>
                <option>3명</option>
                <option>4명</option>
                <option>5명 이상</option>
              </select>
            </div>

            <div>
              <label className="text-sm font-medium text-gray-700">소개글</label>
              <textarea
                placeholder="어떤 여행을 원하시나요? 자유롭게 소개해주세요"
                rows={4}
                className="w-full mt-1.5 px-3 py-2.5 border border-gray-200 rounded-xl text-sm focus:outline-none focus:border-blue-400 resize-none"
              />
            </div>

            <button
              onClick={() => setTab('list')}
              className="w-full bg-blue-500 text-white py-3 rounded-xl font-semibold text-sm"
            >
              모집 글 등록하기
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

export default MatePage