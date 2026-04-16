import { useState, useRef } from 'react';
import { ocrMenuSingle, type MenuCategory } from '../api/menuOcr';

interface MenuItem {
  id: number;
  original: string;
  translated: string;
  description: string;
  price: string;
  visible: boolean;
  category: MenuCategory;
}

const CATEGORY_LABELS: MenuCategory[] = ['메인메뉴', '사이드', '음료/주류', '디저트', '기타'];
const CATEGORY_EMOJI: Record<MenuCategory, string> = {
  '메인메뉴': '🍽️',
  '사이드': '🥗',
  '음료/주류': '🍺',
  '디저트': '🍰',
  '기타': '📋',
};

type Step = 'upload' | 'loading' | 'result' | 'error';

export default function MenuPage() {
  const [step, setStep] = useState<Step>('upload');
  const [previews, setPreviews] = useState<string[]>([]);       // 여러 장 미리보기
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]); // 여러 장 파일
  const [loadingProgress, setLoadingProgress] = useState('');   // "1/3 처리 중..."
  const [errorDetail, setErrorDetail] = useState('');
  const [showModal, setShowModal] = useState(false);
  const [menuItems, setMenuItems] = useState<MenuItem[]>([]);
  const [restaurantName, setRestaurantName] = useState('');
  const [activeCategory, setActiveCategory] = useState<MenuCategory | 'all'>('all');
  const [speaking, setSpeaking] = useState(false);
  const [orderText, setOrderText] = useState('');
  const fileRef = useRef<HTMLInputElement>(null);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []);
    if (!files.length) return;
    // 최대 5장 제한
    const merged = [...selectedFiles, ...files].slice(0, 5);
    setSelectedFiles(merged);
    setPreviews(merged.map((f) => URL.createObjectURL(f)));
    // input 초기화 (동일 파일 재선택 가능)
    if (fileRef.current) fileRef.current.value = '';
  };

  const handleRemoveImage = (idx: number) => {
    setSelectedFiles((prev) => prev.filter((_, i) => i !== idx));
    setPreviews((prev) => prev.filter((_, i) => i !== idx));
  };

  // 파일마다 OCR 순차 호출 → 결과 병합
  const handleConfirm = async () => {
    if (!selectedFiles.length) return;
    setShowModal(false);
    setStep('loading');

    try {
      let allMenus: MenuItem[] = [];
      let idCounter = 1;

      for (let i = 0; i < selectedFiles.length; i++) {
        setLoadingProgress(`${i + 1}/${selectedFiles.length} 처리 중...`);
        const res = await ocrMenuSingle(selectedFiles[i]);
        const mapped: MenuItem[] = res.menus.map((m) => ({
          id: idCounter++,
          original: m.original_name,
          translated: m.english_name,
          description: m.description,
          price: m.price > 0 ? m.price.toLocaleString() + '원' : '',
          visible: true,
          category: m.category ?? '기타',
        }));
        allMenus = [...allMenus, ...mapped];
        // 첫 번째 이미지에서 식당 이름 추출
        if (i === 0 && res.restaurant_name) {
          setRestaurantName(res.restaurant_name);
        }
      }

      setMenuItems(allMenus);
      setStep('result');
    } catch (err: any) {
      console.error('❌ OCR 에러:', err);
      const status = err?.response?.status;
      const msg = err?.response?.data?.message || err?.message || '';
      if (err?.code === 'ECONNABORTED') {
        setErrorDetail('처리 시간이 초과됐어요 (timeout)');
      } else if (status === 401) {
        setErrorDetail('인증 오류 (401)');
      } else if (status === 413) {
        setErrorDetail('파일 크기가 너무 커요 (413)');
      } else if (status) {
        setErrorDetail(`서버 오류 ${status}${msg ? ': ' + msg : ''}`);
      } else {
        setErrorDetail(msg || '알 수 없는 오류');
      }
      setStep('error');
    }
  };

  const toggleItem = (id: number) => {
    setMenuItems((prev) =>
      prev.map((item) => item.id === id ? { ...item, visible: !item.visible } : item)
    );
  };

  const handleSpeak = () => {
    const visibleItems = menuItems.filter((i) => i.visible);
    const base = visibleItems.map((i) => i.translated + (i.price ? ', ' + i.price : '')).join('. ');
    const full = base + (orderText ? '. ' + orderText : '');
    const utterance = new SpeechSynthesisUtterance(full);
    utterance.lang = 'en-US';
    utterance.onstart = () => setSpeaking(true);
    utterance.onend = () => setSpeaking(false);
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(utterance);
  };

  const visibleItems = menuItems.filter((i) => i.visible);

  // 사장님께 보여줄 주문 문구 생성
  const orderPhrase = visibleItems.map((i) => i.original).join(', ');

  const handleReset = () => {
    setStep('upload');
    setPreviews([]);
    setSelectedFiles([]);
    setMenuItems([]);
    setRestaurantName('');
    setActiveCategory('all');
    setOrderText('');
    setLoadingProgress('');
    setErrorDetail('');
    window.speechSynthesis.cancel();
  };

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col">
      {/* 헤더 */}
      <div className="bg-white border-b px-4 pt-10 pb-4">
        <h1 className="text-xl font-bold text-gray-900">🍽️ 메뉴 번역</h1>
        <p className="text-xs text-gray-400 mt-0.5">메뉴판 사진을 찍으면 영어로 번역해드려요</p>
      </div>

      {/* ── 업로드 단계 ── */}
      {step === 'upload' && (
        <div className="flex-1 flex flex-col items-center justify-center p-6 gap-6">
          <div className="text-center">
            <div className="text-5xl mb-3">📸</div>
            <p className="text-gray-600 text-sm">메뉴판을 촬영하거나 갤러리에서 선택하세요</p>
            <p className="text-xs text-gray-400 mt-1">최대 5장까지 첨부 가능해요</p>
          </div>

          <button
            onClick={() => setShowModal(true)}
            className="w-40 h-40 border-2 border-dashed border-gray-300 rounded-2xl flex flex-col items-center justify-center gap-2 bg-white active:bg-gray-50"
          >
            <span className="text-4xl font-light text-gray-400">+</span>
            <span className="text-sm text-gray-400">이미지 선택</span>
          </button>

          <input
            ref={fileRef}
            type="file"
            accept="image/jpeg,image/png,image/gif,image/webp,image/bmp"
            multiple
            onChange={handleFileChange}
            className="hidden"
          />
        </div>
      )}

      {/* ── 로딩 단계 ── */}
      {step === 'loading' && (
        <div className="flex-1 flex flex-col items-center justify-center gap-4">
          <div className="w-12 h-12 border-4 border-pink-400 border-t-transparent rounded-full animate-spin" />
          <p className="text-gray-600 text-sm font-medium">AI가 메뉴를 번역하고 있어요...</p>
          {loadingProgress && (
            <p className="text-pink-400 text-xs font-medium">{loadingProgress}</p>
          )}
          <p className="text-gray-400 text-xs">잠시만 기다려주세요</p>
        </div>
      )}

      {/* ── 에러 단계 ── */}
      {step === 'error' && (
        <div className="flex-1 flex flex-col items-center justify-center gap-4 p-6">
          <div className="text-5xl">😥</div>
          <p className="text-gray-700 font-medium text-center">번역에 실패했어요</p>
          <p className="text-gray-400 text-sm text-center">
            메뉴판이 잘 보이는 사진으로 다시 시도해주세요
          </p>
          {errorDetail && (
            <p className="text-xs text-red-300 text-center bg-red-50 px-4 py-2 rounded-xl">
              {errorDetail}
            </p>
          )}
          <button
            onClick={handleReset}
            className="mt-2 px-6 py-3 bg-pink-400 text-white rounded-xl text-sm font-semibold"
          >
            다시 시도
          </button>
        </div>
      )}

      {/* ── 결과 단계 ── */}
      {step === 'result' && (
        <div className="flex-1 flex flex-col pb-52">
          {/* 이미지 미리보기 (여러 장) */}
          {previews.length > 0 && (
            <div className="bg-white border-b flex gap-1 overflow-x-auto p-2">
              {previews.map((src, idx) => (
                <img
                  key={idx}
                  src={src}
                  alt={`메뉴판 ${idx + 1}`}
                  className="h-24 w-24 object-cover rounded-xl flex-shrink-0"
                />
              ))}
            </div>
          )}

          {/* 툴바 */}
          <div className="px-4 py-3 bg-white border-b flex justify-between items-center">
            <div>
              {restaurantName && (
                <p className="text-xs text-gray-400 font-medium">{restaurantName}</p>
              )}
              <span className="text-sm font-medium text-gray-700">
                번역 결과 <span className="text-pink-400">{menuItems.length}개</span>
              </span>
            </div>
            <button
              onClick={handleReset}
              className="text-sm text-pink-400 font-medium"
            >
              다시 찍기
            </button>
          </div>

          {/* 카테고리 필터 탭 */}
          {menuItems.length > 0 && (
            <div className="bg-white border-b px-4 py-2 flex gap-2 overflow-x-auto">
              <button
                onClick={() => setActiveCategory('all')}
                className={
                  'flex-shrink-0 px-3 py-1.5 rounded-full text-xs font-medium transition-colors ' +
                  (activeCategory === 'all'
                    ? 'bg-pink-400 text-white'
                    : 'bg-gray-100 text-gray-500')
                }
              >
                전체 {menuItems.length}
              </button>
              {CATEGORY_LABELS.filter((cat) => menuItems.some((m) => m.category === cat)).map((cat) => {
                const count = menuItems.filter((m) => m.category === cat).length;
                return (
                  <button
                    key={cat}
                    onClick={() => setActiveCategory(cat)}
                    className={
                      'flex-shrink-0 px-3 py-1.5 rounded-full text-xs font-medium transition-colors ' +
                      (activeCategory === cat
                        ? 'bg-pink-400 text-white'
                        : 'bg-gray-100 text-gray-500')
                    }
                  >
                    {CATEGORY_EMOJI[cat]} {cat} {count}
                  </button>
                );
              })}
            </div>
          )}

          {/* 메뉴 없을 때 */}
          {menuItems.length === 0 && (
            <div className="flex-1 flex flex-col items-center justify-center py-16 text-gray-400 text-sm gap-2">
              <span className="text-3xl">🤔</span>
              메뉴를 찾지 못했어요. 다시 시도해보세요.
            </div>
          )}

          {/* 메뉴 아이템 목록 — 카테고리별 그룹 */}
          <div className="bg-white">
            {(activeCategory === 'all' ? CATEGORY_LABELS : [activeCategory])
              .map((cat) => {
                const items = menuItems.filter((m) => m.category === cat);
                if (items.length === 0) return null;
                return (
                  <div key={cat}>
                    {/* 카테고리 헤더 */}
                    <div className="flex items-center gap-2 px-4 py-2.5 bg-gray-50 border-y border-gray-100">
                      <span className="text-base">{CATEGORY_EMOJI[cat]}</span>
                      <span className="text-sm font-semibold text-gray-700">{cat}</span>
                      <span className="text-xs text-gray-400">{items.length}개</span>
                    </div>
                    {/* 아이템 목록 */}
                    <div className="divide-y divide-gray-50">
                      {items.map((item) => (
                        <div key={item.id} className="flex items-center px-4 py-4 gap-3">
                          <div className="w-12 h-12 bg-orange-50 rounded-xl flex items-center justify-center text-xl flex-shrink-0">
                            {CATEGORY_EMOJI[item.category]}
                          </div>
                          <div className="flex-1 min-w-0">
                            <div className="font-medium text-gray-900 text-sm">{item.original}</div>
                            <div className="text-xs text-blue-500 mt-0.5 font-medium">{item.translated}</div>
                            {item.description && (
                              <div className="text-xs text-gray-400 mt-0.5 line-clamp-1">{item.description}</div>
                            )}
                            {item.price && (
                              <div className="text-xs text-pink-500 mt-0.5 font-semibold">{item.price}</div>
                            )}
                          </div>
                          {/* ── 토글 (수정됨) ── */}
                          <button
                            onClick={() => toggleItem(item.id)}
                            className={
                              'relative w-12 h-6 rounded-full transition-colors flex-shrink-0 ' +
                              (item.visible ? 'bg-pink-400' : 'bg-gray-200')
                            }
                          >
                            <span
                              className={
                                'absolute top-[3px] w-[18px] h-[18px] bg-white rounded-full shadow-sm transition-all duration-200 ' +
                                (item.visible ? 'left-[27px]' : 'left-[3px]')
                              }
                            />
                          </button>
                        </div>
                      ))}
                    </div>
                  </div>
                );
              })}
          </div>
        </div>
      )}

      {/* ── 사장님께 보여주기 하단 바 ── */}
      {step === 'result' && visibleItems.length > 0 && (
        <div className="fixed bottom-16 left-0 right-0 bg-gray-900 text-white px-4 py-4 z-20">
          {/* 주문 문구 */}
          <div className="text-xs text-gray-400 text-center mb-1">사장님, 여기</div>
          <div className="text-center text-sm font-medium mb-1">
            {orderPhrase}
          </div>
          <div className="text-xs text-gray-400 text-center mb-2">
            {orderText || '맛있게 부탁드립니다!'}
          </div>
          <div className="text-xs text-gray-500 text-center mb-3">
            (Please show this screen to your server when ordering)
          </div>

          {/* 추가 타이핑 입력 */}
          <input
            type="text"
            value={orderText}
            onChange={(e) => setOrderText(e.target.value)}
            placeholder="추가로 전달할 말을 입력하세요..."
            className="w-full bg-gray-800 text-white text-xs px-3 py-2 rounded-lg mb-3 placeholder-gray-500 outline-none"
          />

          {/* 스피커 버튼 */}
          <button
            onClick={handleSpeak}
            className={'w-full py-2.5 rounded-xl text-sm font-semibold flex items-center justify-center gap-2 ' +
              (speaking ? 'bg-pink-400 text-white' : 'bg-white text-gray-900')}
          >
            <span>{speaking ? '🔊' : '🔈'}</span>
            <span>{speaking ? '재생 중...' : '소리 재생'}</span>
          </button>
        </div>
      )}

      {/* ── 이미지 삽입 모달 ── */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex items-end justify-center pb-16">
          <div className="absolute inset-0 bg-black bg-opacity-50" onClick={() => setShowModal(false)} />
          <div className="relative bg-white rounded-t-3xl w-full max-w-md flex flex-col" style={{maxHeight: '70vh'}}>
            {/* 헤더 (고정) */}
            <div className="flex items-center justify-between px-6 pt-5 pb-3 flex-shrink-0">
              <div>
                <div className="font-bold text-gray-900">이미지 삽입</div>
                <div className="text-xs text-gray-400 mt-0.5">
                  메뉴판 사진을 여러 장 선택할 수 있어요 (최대 5장)
                </div>
              </div>
              <button
                onClick={() => setShowModal(false)}
                className="text-gray-400 text-xl ml-4"
              >✕</button>
            </div>

            {/* 이미지 그리드 (스크롤 가능) */}
            <div className="flex-1 overflow-y-auto px-6 py-2">
              <div className="flex gap-2 flex-wrap justify-center">
                {previews.map((src, idx) => (
                  <div key={idx} className="relative w-20 h-20 rounded-xl overflow-hidden flex-shrink-0">
                    <img src={src} alt={`선택 ${idx + 1}`} className="w-full h-full object-cover" />
                    <button
                      onClick={() => handleRemoveImage(idx)}
                      className="absolute top-1 right-1 w-5 h-5 bg-black/60 rounded-full flex items-center justify-center text-white text-xs"
                    >
                      ✕
                    </button>
                  </div>
                ))}

                {/* + 추가 버튼 */}
                {previews.length < 5 && (
                  <button
                    onClick={() => fileRef.current?.click()}
                    className="w-20 h-20 border-2 border-dashed border-gray-300 rounded-xl flex flex-col items-center justify-center gap-1 text-gray-400 active:bg-gray-50"
                  >
                    <span className="text-2xl font-light">+</span>
                    <span className="text-xs">사진 추가</span>
                  </button>
                )}
              </div>

              {previews.length > 0 && (
                <p className="text-xs text-center text-gray-400 mt-3">
                  {previews.length}장 선택됨
                </p>
              )}
            </div>

            {/* 확인 버튼 (항상 하단 고정) */}
            <div className="px-6 pb-6 pt-3 flex-shrink-0">
              <button
                onClick={handleConfirm}
                disabled={previews.length === 0}
                className={'w-full py-3 rounded-xl font-semibold text-sm ' +
                  (previews.length > 0 ? 'bg-gray-900 text-white' : 'bg-gray-200 text-gray-400')}
              >
                {previews.length > 0 ? `${previews.length}장 번역 시작` : '사진을 선택해주세요'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
