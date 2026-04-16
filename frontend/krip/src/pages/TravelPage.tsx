import { useState } from 'react'

const MOCK_PLAN = [
  {
    day: 1,
    spots: [
      { time: '09:00', name: '경복궁', category: '역사', image: '🏯', duration: '2시간' },
      { time: '12:00', name: '광장시장', category: '음식', image: '🍜', duration: '1시간' },
      { time: '14:00', name: '북촌한옥마을', category: '역사', image: '🏘', duration: '1.5시간' },
      { time: '16:30', name: '인사동', category: '쇼핑', image: '🛍', duration: '1시간' },
    ],
  },
  {
    day: 2,
    spots: [
      { time: '10:00', name: 'N서울타워', category: '관광', image: '🗼', duration: '2시간' },
      { time: '13:00', name: '이태원', category: '음식', image: '🍔', duration: '1시간' },
      { time: '15:00', name: '홍대거리', category: '쇼핑', image: '🎨', duration: '2시간' },
    ],
  },
]

const STYLES = ['역사/문화', '음식 탐방', '쇼핑', '자연', '액티비티']

type Step = 'form' | 'loading' | 'result'

function TravelPage() {
  const [step, setStep] = useState<Step>('form')
  const [selectedStyles, setSelectedStyles] = useState<string[]>([])
  const [days, setDays] = useState('2')

  const toggleStyle = (style: string) => {
    setSelectedStyles((prev) =>
      prev.includes(style) ? prev.filter((s) => s !== style) : [...prev, style]
    )
  }

  const handleGenerate = () => {
    setStep('loading')
    setTimeout(() => setStep('result'), 2500)
  }

  return (
    <div className="max-w-md mx-auto bg-gray-50 min-h-screen">
      {/* 헤더 */}
      <div className="bg-white px-4 pt-6 pb-4 shadow-sm">
        <h1 className="text-2xl font-bold text-gray-800">🗺 여행지 설계</h1>
        <p className="text-sm text-gray-500 mt-1">AI가 나만의 서울 여행 코스를 짜드려요</p>
      </div>

      <div className="px-4 py-4">

        {/* Step 1: 조건 입력 폼 */}
        {step === 'form' && (
          <div className="space-y-4">
            <div className="bg-white rounded-2xl p-4 shadow-sm space-y-4">

              <div>
                <label className="text-sm font-medium text-gray-700">여행 기간</label>
                <select
                  value={days}
                  onChange={(e) => setDays(e.target.value)}
                  className="w-full mt-1.5 px-3 py-2.5 border border-gray-200 rounded-xl text-sm focus:outline-none focus:border-blue-400"
                >
                  <option value="1">당일치기</option>
                  <option value="2">1박 2일</option>
                  <option value="3">2박 3일</option>
                  <option value="4">3박 4일</option>
                </select>
              </div>

              <div>
                <label className="text-sm font-medium text-gray-700">여행 스타일 (복수 선택)</label>
                <div className="flex flex-wrap gap-2 mt-2">
                  {STYLES.map((style) => (
                    <button
                      key={style}
                      onClick={() => toggleStyle(style)}
                      className={'px-3 py-1.5 rounded-full text-sm font-medium border transition-colors ' +
                        (selectedStyles.includes(style)
                          ? 'bg-blue-500 text-white border-blue-500'
                          : 'bg-white text-gray-600 border-gray-200')}
                    >
                      {style}
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <label className="text-sm font-medium text-gray-700">인원 수</label>
                <select className="w-full mt-1.5 px-3 py-2.5 border border-gray-200 rounded-xl text-sm focus:outline-none focus:border-blue-400">
                  <option>1명 (혼자)</option>
                  <option>2명</option>
                  <option>3~4명</option>
                  <option>5명 이상</option>
                </select>
              </div>
            </div>

            <button
              onClick={handleGenerate}
              className="w-full bg-blue-500 text-white py-4 rounded-2xl font-bold text-lg shadow-sm"
            >
              ✨ AI 코스 생성하기
            </button>
          </div>
        )}

        {/* Step 2: 로딩 */}
        {step === 'loading' && (
          <div className="flex flex-col items-center justify-center py-32 space-y-4">
            <div className="w-12 h-12 border-4 border-blue-500 border-t-transparent rounded-full animate-spin" />
            <p className="text-gray-700 font-semibold">AI가 코스를 짜는 중...</p>
            <p className="text-gray-400 text-sm">서울 곳곳을 탐색하고 있어요 🗺</p>
          </div>
        )}

        {/* Step 3: 결과 */}
        {step === 'result' && (
          <div className="space-y-4">
            <div className="flex items-center justify-between py-1">
              <h2 className="font-bold text-gray-800">추천 여행 코스</h2>
              <button
                onClick={() => setStep('form')}
                className="text-sm text-blue-500 font-medium"
              >
                다시 생성
              </button>
            </div>

            {MOCK_PLAN.map((dayPlan) => (
              <div key={dayPlan.day} className="bg-white rounded-2xl shadow-sm overflow-hidden">
                <div className="bg-blue-500 px-4 py-2.5">
                  <p className="text-white font-bold">Day {dayPlan.day}</p>
                </div>

                <div className="divide-y divide-gray-50">
                  {dayPlan.spots.map((spot, i) => (
                    <div key={i} className="flex items-center gap-3 px-4 py-3">
                      <div className="text-center w-12 flex-shrink-0">
                        <p className="text-xs text-gray-400">{spot.time}</p>
                      </div>
                      <div className="w-0.5 h-10 bg-blue-100 flex-shrink-0" />
                      <div className="text-2xl">{spot.image}</div>
                      <div className="flex-1">
                        <p className="font-medium text-gray-800 text-sm">{spot.name}</p>
                        <p className="text-xs text-gray-400">{spot.category} · {spot.duration}</p>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

export default TravelPage