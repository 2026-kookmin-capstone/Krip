import { useState, useRef } from 'react'

// 임시 번역 결과 데이터
const MOCK_RESULT = [
  { original: '된장찌개', translated: 'Soybean Paste Stew', price: '8,000원' },
  { original: '김치볶음밥', translated: 'Kimchi Fried Rice', price: '9,000원' },
  { original: '삼겹살', translated: 'Grilled Pork Belly', price: '15,000원' },
  { original: '냉면', translated: 'Cold Noodles', price: '11,000원' },
  { original: '비빔밥', translated: 'Mixed Rice Bowl', price: '10,000원' },
]

type Step = 'upload' | 'loading' | 'result'

function MenuPage() {
  const [step, setStep] = useState<Step>('upload')
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  // 이미지 선택 시
  const handleImageSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    const url = URL.createObjectURL(file)
    setPreviewUrl(url)
    setStep('loading')

    // 임시: 2초 후 결과 화면으로 (나중에 실제 OCR API로 교체)
    setTimeout(() => setStep('result'), 2000)
  }

  const handleReset = () => {
    setStep('upload')
    setPreviewUrl(null)
  }

  return (
    <div className="max-w-md mx-auto bg-gray-50 min-h-screen">
      {/* 헤더 */}
      <div className="bg-white px-4 pt-6 pb-4 shadow-sm">
        <h1 className="text-2xl font-bold text-gray-800">🍽 메뉴 번역</h1>
        <p className="text-sm text-gray-500 mt-1">메뉴판을 찍으면 바로 번역해드려요</p>
      </div>

      <div className="px-4 py-5">

        {/* Step 1: 이미지 업로드 */}
        {step === 'upload' && (
          <div className="space-y-4">
            <input
              ref={inputRef}
              type="file"
              accept="image/*"
              onChange={handleImageSelect}
              className="hidden"
            />

            {/* 카메라 촬영 버튼 */}
            <button
              onClick={() => {
                if (inputRef.current) {
                  inputRef.current.setAttribute('capture', 'environment')
                  inputRef.current.click()
                }
              }}
              className="w-full bg-blue-500 text-white py-4 rounded-2xl font-semibold text-lg flex items-center justify-center gap-3 shadow-sm active:bg-blue-600"
            >
              <span className="text-2xl">📷</span>
              카메라로 촬영하기
            </button>

            {/* 갤러리 선택 버튼 */}
            <button
              onClick={() => {
                if (inputRef.current) {
                  inputRef.current.removeAttribute('capture')
                  inputRef.current.click()
                }
              }}
              className="w-full bg-white text-gray-700 py-4 rounded-2xl font-semibold text-lg flex items-center justify-center gap-3 border border-gray-200 shadow-sm"
            >
              <span className="text-2xl">🖼</span>
              갤러리에서 선택
            </button>

            {/* 안내 */}
            <div className="bg-blue-50 rounded-2xl p-4 mt-4">
              <p className="text-sm text-blue-700 font-medium mb-2">📌 이렇게 사용하세요</p>
              <ul className="text-sm text-blue-600 space-y-1">
                <li>• 메뉴판 전체가 나오도록 찍어주세요</li>
                <li>• 글씨가 잘 보이도록 밝은 곳에서 찍으세요</li>
                <li>• 한국어 메뉴판에 최적화되어 있어요</li>
              </ul>
            </div>
          </div>
        )}

        {/* Step 2: 로딩 */}
        {step === 'loading' && (
          <div className="flex flex-col items-center justify-center py-24 space-y-4">
            {previewUrl && (
              <img
                src={previewUrl}
                alt="업로드된 메뉴판"
                className="w-40 h-40 object-cover rounded-2xl shadow-md mb-4"
              />
            )}
            <div className="w-10 h-10 border-4 border-blue-500 border-t-transparent rounded-full animate-spin" />
            <p className="text-gray-600 font-medium">메뉴를 인식하는 중...</p>
            <p className="text-gray-400 text-sm">잠시만 기다려주세요</p>
          </div>
        )}

        {/* Step 3: 번역 결과 */}
        {step === 'result' && (
          <div className="space-y-3">
            {/* 촬영 이미지 */}
            {previewUrl && (
              <img
                src={previewUrl}
                alt="메뉴판"
                className="w-full h-40 object-cover rounded-2xl shadow-sm"
              />
            )}

            <div className="flex items-center justify-between py-2">
              <h2 className="font-bold text-gray-800">번역 결과</h2>
              <button
                onClick={handleReset}
                className="text-sm text-blue-500 font-medium"
              >
                다시 찍기
              </button>
            </div>

            {MOCK_RESULT.map((item, index) => (
              <div key={index} className="bg-white rounded-2xl p-4 shadow-sm">
                <div className="flex items-start justify-between">
                  <div>
                    <p className="font-semibold text-gray-800">{item.original}</p>
                    <p className="text-blue-500 text-sm mt-0.5">{item.translated}</p>
                  </div>
                  <span className="text-gray-600 text-sm font-medium">{item.price}</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

export default MenuPage