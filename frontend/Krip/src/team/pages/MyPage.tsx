import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { getMyProfile, logout, type UserProfile } from '../api/auth';

const SEOUL_DISTRICTS = [
  '종로구', '중구', '용산구', '성동구', '광진구',
  '동대문구', '중랑구', '성북구', '강북구', '도봉구',
  '노원구', '은평구', '서대문구', '마포구', '양천구',
  '강서구', '구로구', '금천구', '영등포구', '동작구',
  '관악구', '서초구', '강남구', '송파구', '강동구',
];

// 스탬프는 추후 백엔드 연결 (현재 mock)
const MOCK_STAMPS = ['종로구', '중구', '마포구', '강남구'];

const MOCK_SAVED_SPOTS = [
  { id: 1, name: '경복궁', address: '서울 종로구', emoji: '🏯' },
  { id: 2, name: '광장시장', address: '서울 종로구', emoji: '🍜' },
  { id: 3, name: '남산타워', address: '서울 용산구', emoji: '🗼' },
];

const MOCK_SAVED_PLANS = [
  { id: 1, title: '서울 2박 3일 코스', date: '2024-05-10', days: 3 },
  { id: 2, title: '강남 맛집 투어', date: '2024-05-20', days: 1 },
];

const TRAVEL_STYLE_LABELS: Record<string, string> = {
  food: '맛집탐방',
  active: '액티브',
  culture: '문화여행',
  healing: '힐링',
  photo: '사진촬영',
  shopping: '쇼핑',
  history: '역사탐방',
};

type Section = 'main' | 'editProfile' | 'stamp' | 'savedInfo' | 'settings';

export default function MyPage() {
  const navigate = useNavigate();
  const [section, setSection] = useState<Section>('main');
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [savedTab, setSavedTab] = useState<'spots' | 'plans' | 'shared'>('spots');
  const [notifications, setNotifications] = useState({
    push: true, mate: true, chat: true, travel: false,
  });

  const stamps = MOCK_STAMPS;
  const stampsCount = stamps.length;
  const level = stampsCount >= 20 ? 5 : stampsCount >= 15 ? 4 : stampsCount >= 10 ? 3 : stampsCount >= 5 ? 2 : 1;

  // ── 프로필 불러오기 ──
  useEffect(() => {
    const fetchProfile = async () => {
      try {
        const data = await getMyProfile();
        setProfile(data);
      } catch {
        // 로그인 안 됐거나 에러 → null 유지
      } finally {
        setLoading(false);
      }
    };
    fetchProfile();
  }, []);

  // ── 로그아웃 ──
  const handleLogout = async () => {
    if (!window.confirm('로그아웃 하시겠어요?')) return;
    try {
      await logout();
    } catch {
      // 에러 무시하고 로그아웃 처리
    }
    navigate('/');
  };

  // 표시할 이름/정보
  const displayName = profile?.user_name ?? 'Guest';
  const displayNationality = profile?.nationality ?? '';
  const displayAge = profile?.age ? `${profile.age}세` : '';
  const displayGender = profile?.gender === 'male' ? '남성' : profile?.gender === 'female' ? '여성' : '';
  const travelStyles = profile?.travel_styles ?? [];

  // ── 메인 ──
  if (section === 'main') {
    return (
      <div className="min-h-screen bg-gray-50 pb-24">
        {/* 헤더 */}
        <div className="bg-white px-4 pt-10 pb-6 flex flex-col items-center border-b">
          <div className="w-20 h-20 bg-pink-100 rounded-full flex items-center justify-center text-4xl mb-3">
            {loading ? '⏳' : '🧑‍💼'}
          </div>

          {loading ? (
            <div className="text-gray-400 text-sm">불러오는 중...</div>
          ) : (
            <>
              <div className="text-xl font-bold text-gray-900">{displayName}</div>
              <div className="text-sm text-gray-400 mt-1 flex items-center gap-2">
                {displayNationality && <span>🌍 {displayNationality}</span>}
                {displayAge && <span>{displayAge}</span>}
                {displayGender && <span>{displayGender}</span>}
              </div>

              {/* 여행 스타일 태그 */}
              {travelStyles.length > 0 && (
                <div className="flex gap-2 mt-3 flex-wrap justify-center">
                  {travelStyles.map((style) => (
                    <span key={style} className="bg-pink-50 text-pink-500 text-xs px-3 py-1 rounded-full">
                      {TRAVEL_STYLE_LABELS[style] ?? style}
                    </span>
                  ))}
                </div>
              )}
            </>
          )}

          {/* 레벨 */}
          <div className="mt-3 bg-yellow-50 px-4 py-1.5 rounded-full flex items-center gap-1">
            <span>⭐</span>
            <span className="text-sm font-semibold text-yellow-700">{'Lv.' + level + ' 여행자'}</span>
            <span className="text-xs text-yellow-500">{'(' + stampsCount + '/25 스탬프)'}</span>
          </div>
        </div>

        {/* 메뉴 */}
        <div className="mt-3 bg-white divide-y">
          {[
            { icon: '✏️', label: '프로필 수정', action: () => setSection('editProfile') },
            { icon: '🏆', label: '스탬프', badge: `${stampsCount}/25`, action: () => setSection('stamp') },
            { icon: '📌', label: '저장된 여행정보', action: () => setSection('savedInfo') },
            { icon: '⚙️', label: '설정', action: () => setSection('settings') },
          ].map(({ icon, label, badge, action }) => (
            <button
              key={label}
              onClick={action}
              className="w-full flex items-center justify-between px-5 py-4 active:bg-gray-50"
            >
              <div className="flex items-center gap-3">
                <span className="text-xl">{icon}</span>
                <span className="text-sm font-medium text-gray-800">{label}</span>
                {badge && (
                  <span className="bg-orange-100 text-orange-600 text-xs px-2 py-0.5 rounded-full font-medium">
                    {badge}
                  </span>
                )}
              </div>
              <span className="text-gray-400">›</span>
            </button>
          ))}
        </div>

        {/* 앱 정보 */}
        <div className="mt-3 bg-white divide-y">
          <div className="flex items-center justify-between px-5 py-4">
            <span className="text-sm text-gray-500">버전 정보</span>
            <span className="text-sm text-gray-400">v1.0.0</span>
          </div>
          <button className="w-full flex items-center justify-between px-5 py-4 active:bg-gray-50">
            <span className="text-sm text-gray-500">이용약관</span>
            <span className="text-gray-400">›</span>
          </button>
          <button className="w-full flex items-center justify-between px-5 py-4 active:bg-gray-50">
            <span className="text-sm text-gray-500">개인정보 처리방침</span>
            <span className="text-gray-400">›</span>
          </button>
        </div>
      </div>
    );
  }

  // ── 프로필 수정 ──
  if (section === 'editProfile') {
    return (
      <div className="min-h-screen bg-gray-50">
        <div className="bg-white border-b px-4 py-4 flex items-center gap-3">
          <button onClick={() => setSection('main')} className="text-gray-600 text-xl">‹</button>
          <h2 className="text-lg font-bold text-gray-900">프로필 수정</h2>
        </div>
        <div className="p-4 space-y-4">
          <div className="flex flex-col items-center py-4">
            <div className="w-20 h-20 bg-pink-100 rounded-full flex items-center justify-center text-4xl mb-3">
              🧑‍💼
            </div>
            <button className="text-sm text-pink-400 font-medium">사진 변경</button>
          </div>

          {/* 실제 프로필 정보 표시 */}
          <div className="bg-white rounded-xl p-4 space-y-3">
            <div>
              <label className="block text-xs text-gray-400 mb-1">이름</label>
              <div className="text-sm text-gray-900 border-b border-gray-100 pb-1">{displayName}</div>
            </div>
            {displayNationality && (
              <div>
                <label className="block text-xs text-gray-400 mb-1">국적</label>
                <div className="text-sm text-gray-900 border-b border-gray-100 pb-1">{displayNationality}</div>
              </div>
            )}
            {displayAge && (
              <div>
                <label className="block text-xs text-gray-400 mb-1">나이</label>
                <div className="text-sm text-gray-900 border-b border-gray-100 pb-1">{displayAge}</div>
              </div>
            )}
            {displayGender && (
              <div>
                <label className="block text-xs text-gray-400 mb-1">성별</label>
                <div className="text-sm text-gray-900 border-b border-gray-100 pb-1">{displayGender}</div>
              </div>
            )}
          </div>

          <div className="bg-yellow-50 rounded-xl p-4 text-xs text-yellow-700 text-center">
            프로필 수정 기능은 준비 중이에요 🔧
          </div>
        </div>
      </div>
    );
  }

  // ── 스탬프 ──
  if (section === 'stamp') {
    return (
      <div className="min-h-screen bg-gray-50 pb-24">
        <div className="bg-white border-b px-4 py-4 flex items-center gap-3">
          <button onClick={() => setSection('main')} className="text-gray-600 text-xl">‹</button>
          <h2 className="text-lg font-bold text-gray-900">스탬프</h2>
        </div>
        <div className="bg-white mx-4 mt-4 rounded-2xl p-4 text-center shadow-sm">
          <div className="text-3xl mb-1">🏆</div>
          <div className="font-bold text-gray-900">{'Lv.' + level + ' 여행자'}</div>
          <div className="text-sm text-gray-400 mt-1">{stampsCount + '개 / 25개 수집'}</div>
          <div className="mt-3 bg-gray-100 rounded-full h-2">
            <div
              className="bg-yellow-400 h-2 rounded-full transition-all"
              style={{ width: (stampsCount / 25 * 100) + '%' }}
            />
          </div>
        </div>
        <div className="px-4 mt-4">
          <h3 className="text-sm font-medium text-gray-700 mb-3">서울 25개 구 스탬프</h3>
          <div className="grid grid-cols-5 gap-2">
            {SEOUL_DISTRICTS.map((district) => {
              const collected = stamps.includes(district);
              return (
                <div
                  key={district}
                  className={'flex flex-col items-center p-2 rounded-xl text-center ' +
                    (collected ? 'bg-yellow-50' : 'bg-white opacity-50')}
                >
                  <span className="text-xl">{collected ? '🏅' : '⬜'}</span>
                  <span className={'text-xs mt-0.5 ' + (collected ? 'text-yellow-700 font-medium' : 'text-gray-400')}>
                    {district.replace('구', '')}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    );
  }

  // ── 저장된 여행정보 ──
  if (section === 'savedInfo') {
    return (
      <div className="min-h-screen bg-gray-50 pb-24">
        <div className="bg-white border-b px-4 py-4 flex items-center gap-3">
          <button onClick={() => setSection('main')} className="text-gray-600 text-xl">‹</button>
          <h2 className="text-lg font-bold text-gray-900">저장된 여행정보</h2>
        </div>
        <div className="bg-white border-b flex">
          {(['spots', 'plans', 'shared'] as const).map((t) => {
            const labels = { spots: '즐겨찾기', plans: '저장된 일정', shared: '공유받은 일정' };
            return (
              <button
                key={t}
                onClick={() => setSavedTab(t)}
                className={'flex-1 py-3 text-sm font-medium border-b-2 ' +
                  (savedTab === t ? 'border-pink-400 text-pink-500' : 'border-transparent text-gray-400')}
              >
                {labels[t]}
              </button>
            );
          })}
        </div>
        <div className="p-4 space-y-3">
          {savedTab === 'spots' && MOCK_SAVED_SPOTS.map((spot) => (
            <div
              key={spot.id}
              onClick={() => navigate('/spots/' + spot.id)}
              className="bg-white rounded-xl p-4 shadow-sm flex items-center gap-3 cursor-pointer active:bg-gray-50"
            >
              <div className="w-12 h-12 bg-gray-100 rounded-xl flex items-center justify-center text-2xl">
                {spot.emoji}
              </div>
              <div className="flex-1">
                <div className="font-semibold text-gray-900 text-sm">{spot.name}</div>
                <div className="text-xs text-gray-400">{spot.address}</div>
              </div>
              <span className="text-red-400">❤️</span>
            </div>
          ))}
          {savedTab === 'plans' && MOCK_SAVED_PLANS.map((plan) => (
            <div key={plan.id} className="bg-white rounded-xl p-4 shadow-sm">
              <div className="font-semibold text-gray-900 text-sm">{plan.title}</div>
              <div className="text-xs text-gray-400 mt-1">{plan.date + ' · ' + plan.days + '일 일정'}</div>
            </div>
          ))}
          {savedTab === 'shared' && (
            <div className="text-center py-12 text-gray-400 text-sm">공유받은 일정이 없어요</div>
          )}
        </div>
      </div>
    );
  }

  // ── 설정 ──
  if (section === 'settings') {
    const toggleNotif = (key: keyof typeof notifications) =>
      setNotifications((prev) => ({ ...prev, [key]: !prev[key] }));
    const notifItems = [
      { key: 'push' as const, label: '푸시 알림' },
      { key: 'mate' as const, label: '여행 메이트 알림' },
      { key: 'chat' as const, label: '채팅 알림' },
      { key: 'travel' as const, label: '여행 일정 알림' },
    ];
    return (
      <div className="min-h-screen bg-gray-50 pb-24">
        <div className="bg-white border-b px-4 py-4 flex items-center gap-3">
          <button onClick={() => setSection('main')} className="text-gray-600 text-xl">‹</button>
          <h2 className="text-lg font-bold text-gray-900">설정</h2>
        </div>
        <div className="mt-3">
          <div className="px-4 py-2 text-xs text-gray-400 font-medium">알림 설정</div>
          <div className="bg-white divide-y">
            {notifItems.map((item) => (
              <div key={item.key} className="flex items-center justify-between px-5 py-4">
                <span className="text-sm text-gray-800">{item.label}</span>
                <button
                  onClick={() => toggleNotif(item.key)}
                  className={'relative w-11 h-6 rounded-full transition-colors ' +
                    (notifications[item.key] ? 'bg-pink-400' : 'bg-gray-200')}
                >
                  <span className={'absolute top-0.5 w-5 h-5 bg-white rounded-full shadow transition-transform ' +
                    (notifications[item.key] ? 'translate-x-5' : 'translate-x-0.5')} />
                </button>
              </div>
            ))}
          </div>
        </div>
        <div className="mt-3">
          <div className="px-4 py-2 text-xs text-gray-400 font-medium">계정 설정</div>
          <div className="bg-white divide-y">
            <button
              onClick={handleLogout}
              className="w-full flex items-center justify-between px-5 py-4 active:bg-gray-50"
            >
              <span className="text-sm text-gray-800">로그아웃</span>
              <span className="text-gray-400">›</span>
            </button>
            <button
              onClick={() => window.confirm('정말 탈퇴하시겠어요? 모든 데이터가 삭제됩니다.')}
              className="w-full flex items-center justify-between px-5 py-4 active:bg-gray-50"
            >
              <span className="text-sm text-red-500">회원 탈퇴</span>
              <span className="text-gray-400">›</span>
            </button>
          </div>
        </div>
      </div>
    );
  }

  return null;
}
