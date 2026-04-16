import React, { useState, useRef, useEffect } from 'react';
import '../styles/DestinationPage.css';
import Header from '../components/Header';

const SAMPLE_PLACES = [
  { id: 1,  name: '경복궁',      category: '문화/역사', emoji: '🏯', addr: '서울 종로구',   lat: 37.579, lng: 126.977 },
  { id: 2,  name: '남산타워',    category: '관광지',   emoji: '🗼', addr: '서울 용산구',   lat: 37.551, lng: 126.988 },
  { id: 3,  name: '인사동',      category: '쇼핑/문화', emoji: '🎨', addr: '서울 종로구',   lat: 37.574, lng: 126.985 },
  { id: 4,  name: '광장시장',    category: '맛집',     emoji: '🍜', addr: '서울 종로구',   lat: 37.570, lng: 126.999 },
  { id: 5,  name: '홍대거리',    category: '쇼핑',     emoji: '🛍️', addr: '서울 마포구',   lat: 37.556, lng: 126.923 },
  { id: 6,  name: '한강공원',    category: '자연/공원', emoji: '🌿', addr: '서울 여의도',   lat: 37.528, lng: 126.934 },
  { id: 7,  name: '명동거리',    category: '쇼핑',     emoji: '🏪', addr: '서울 중구',    lat: 37.563, lng: 126.982 },
  { id: 8,  name: '이태원',      category: '맛집',     emoji: '🍽️', addr: '서울 용산구',   lat: 37.534, lng: 126.994 },
  { id: 9,  name: '북촌한옥마을', category: '문화/역사', emoji: '🏘️', addr: '서울 종로구',   lat: 37.582, lng: 126.983 },
  { id: 10, name: '동대문DDP',   category: '문화',     emoji: '🌀', addr: '서울 중구',    lat: 37.566, lng: 127.009 },
  { id: 11, name: '성수동',      category: '카페/감성', emoji: '☕', addr: '서울 성동구',   lat: 37.544, lng: 127.056 },
  { id: 12, name: '강남역',      category: '쇼핑',     emoji: '🏬', addr: '서울 강남구',   lat: 37.498, lng: 127.028 },
];

const MAP_PINS = [
  { top: '28%', left: '38%' }, { top: '52%', left: '62%' },
  { top: '40%', left: '22%' }, { top: '65%', left: '45%' },
  { top: '20%', left: '65%' }, { top: '75%', left: '28%' },
];

const formatDate = (d) => d ? `${d.getMonth() + 1}월 ${d.getDate()}일` : '';

/* ── Share utility ── */
const generateShareLink = () => {
  const timestamp = Date.now().toString(36);
  const randomStr = Math.random().toString(36).substring(2, 8);
  return `https://krip.app/share/${timestamp}${randomStr}`;
};

const copyToClipboard = async (text) => {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch (err) {
    // 구형 브라우저 fallback
    try {
      const textArea = document.createElement('textarea');
      textArea.value = text;
      textArea.style.cssText = 'position:fixed;top:-9999px;left:-9999px;opacity:0';
      document.body.appendChild(textArea);
      textArea.focus();
      textArea.select();
      document.execCommand('copy');
      document.body.removeChild(textArea);
      return true;
    } catch {
      console.error('Failed to copy:', err);
      return false;
    }
  }
};

const shareToKakao = (link, destinations, travelDates) => {
  // Kakao SDK가 로드·초기화되지 않은 경우 → 클립보드 복사 후 안내
  if (!window.Kakao || !window.Kakao.isInitialized()) {
    copyToClipboard(link).then((success) => {
      if (success) {
        alert('카카오 SDK가 초기화되지 않았어요.\n링크가 클립보드에 복사되었으니 카카오톡에서 직접 붙여넣기 해주세요.');
      }
    });
    return;
  }

  const destNames = destinations.map((d) => d.name).join(', ') || '여행지들';
  const dateText = travelDates
    ? `${formatDate(travelDates.startDate)} ~ ${formatDate(travelDates.endDate)}`
    : '';

  window.Kakao.Share.sendDefault({
    objectType: 'feed',
    content: {
      title: 'krip: 여행 일정 초대 ✈️',
      description: `[${dateText}]\n${destNames} 일정을 함께 확인해보세요!`,
      imageUrl: 'https://krip.app/images/share-thumb.png',
      link: { webUrl: link, mobileWebUrl: link },
    },
    buttons: [
      {
        title: '일정 보기',
        link: { webUrl: link, mobileWebUrl: link },
      },
    ],
  });
};

// ✅ Web Share API (모바일 기본 공유 시트)
const shareToWeb = async (link, destinations, travelDates) => {
  const destNames = destinations.map((d) => d.name).join(', ') || '여행지';
  const dateText = travelDates
    ? `${formatDate(travelDates.startDate)} ~ ${formatDate(travelDates.endDate)}`
    : '';

  if (navigator.share) {
    try {
      await navigator.share({
        title: `${dateText} 여행 일정`,
        text: `함께 ${destNames} 여행을 계획해요!`,
        url: link,
      });
    } catch (err) {
      if (err.name !== 'AbortError') {
        console.error('Share failed:', err);
      }
    }
  } else {
    // 데스크톱 등 미지원 환경 → 클립보드로 fallback
    const success = await copyToClipboard(link);
    if (success) {
      alert('공유 기능을 지원하지 않는 환경입니다.\n링크가 클립보드에 복사되었어요.');
    }
  }
};

// ✅ 인스타그램: 직접 공유 API 없음 → 클립보드 복사 후 앱 열기
const shareToInstagram = async (link) => {
  const success = await copyToClipboard(link);
  if (success) {
    alert('링크가 복사되었습니다!\n인스타그램 앱 > 스토리 또는 DM에서 붙여넣기 해주세요.');
  }
  // 모바일: 인스타그램 앱 딥링크 시도
  window.open('instagram://app', '_blank');
};

// ✅ 이메일 공유: mailto: 스킴 사용
const shareToEmail = (link, destinations, travelDates) => {
  const destNames = destinations.map((d) => d.name).join(', ') || '여행지';
  const dateText = travelDates
    ? `${formatDate(travelDates.startDate)} ~ ${formatDate(travelDates.endDate)}`
    : '';

  const subject = encodeURIComponent(`[krip] ${dateText} 여행 일정 초대`);
  const body = encodeURIComponent(
    `안녕하세요!\n\n${dateText} 여행을 함께 계획하고 싶어 초대장을 보냈어요.\n\n` +
    `📍 예정 여행지: ${destNames}\n\n` +
    `아래 링크에서 일정을 확인하고 함께 편집해보세요.\n${link}\n\n` +
    `즐거운 여행 되세요! ✈️`
  );

  window.open(`mailto:?subject=${subject}&body=${body}`, '_self');
};

const DestinationPage = ({ navigate, travelDates }) => {
  const [query,        setQuery]        = useState('');
  const [destinations, setDestinations] = useState([]);
  const [showInvite,   setShowInvite]   = useState(false);
  const [saved,        setSaved]        = useState(false);
  const [copied,       setCopied]       = useState(false);
  const [shareLink,    setShareLink]    = useState('');
  const [shareStatus,  setShareStatus]  = useState('');
  const inputRef = useRef(null);

  useEffect(() => {
    if (showInvite && !shareLink) {
      setShareLink(generateShareLink());
    }
  }, [showInvite, shareLink]);

  const filtered = query.trim().length > 0
    ? SAMPLE_PLACES.filter((p) =>
        p.name.includes(query) ||
        p.addr.includes(query) ||
        p.category.includes(query)
      )
    : [];

  const addPlace = (place) => {
    if (!destinations.find((d) => d.id === place.id)) {
      setDestinations((prev) => [...prev, place]);
    }
    setQuery('');
    inputRef.current?.blur();
  };

  const removePlace = (id) => setDestinations((prev) => prev.filter((d) => d.id !== id));

  const handleCopyLink = async () => {
    const success = await copyToClipboard(shareLink);
    if (success) {
      setCopied(true);
      setShareStatus('copied');
      setTimeout(() => {
        setCopied(false);
        setShareStatus('');
      }, 2000);
    } else {
      alert('링크 복사에 실패했습니다. 직접 선택해서 복사해 주세요.');
    }
  };

  const handleShareKakao = () => {
    shareToKakao(shareLink, destinations, travelDates);
    setShareStatus('kakao');
    setTimeout(() => setShareStatus(''), 1500);
  };

  const handleShareWeb = () => {
    shareToWeb(shareLink, destinations, travelDates);
    setShareStatus('web');
    setTimeout(() => setShareStatus(''), 1500);
  };

  const handleShareInstagram = () => {
    shareToInstagram(shareLink);
    setShareStatus('insta');
    setTimeout(() => setShareStatus(''), 1500);
  };

  const handleShareEmail = () => {
    shareToEmail(shareLink, destinations, travelDates);
    setShareStatus('email');
    setTimeout(() => setShareStatus(''), 1500);
  };

  const handleSave = () => {
    setSaved(true);
    console.log('저장된 여행지:', destinations);
    setTimeout(() => setSaved(false), 2000);
  };

  const headerTitle = travelDates
    ? `${formatDate(travelDates.startDate)} ~ ${formatDate(travelDates.endDate)}`
    : '여행지 추가';

  return (
    <div className="dest-page">
      <Header
        title={headerTitle}
        onBack={() => navigate('calendar')}
        rightElement={
          <button className="dest-header-save" onClick={handleSave}>
            {saved ? '✅' : '💾'}
          </button>
        }
      />

      {/* ── Map placeholder ── */}
      <div className="dest-map">
        <div className="dest-map-inner">
          <div className="dest-map-grid" />
          <svg className="dest-map-roads" viewBox="0 0 400 220" preserveAspectRatio="none">
            <path d="M0 110 Q100 90 200 110 T400 110" stroke="#C7E9F8" strokeWidth="8" fill="none" />
            <path d="M0 60 Q80 50 160 70 T320 55 T400 65" stroke="#D9F2FC" strokeWidth="6" fill="none" />
            <path d="M200 0 Q210 80 200 110 Q190 160 200 220" stroke="#C7E9F8" strokeWidth="8" fill="none" />
            <path d="M100 0 Q95 60 110 110 Q115 160 100 220" stroke="#D9F2FC" strokeWidth="5" fill="none" />
            <path d="M320 0 Q315 80 310 110 Q305 160 320 220" stroke="#D9F2FC" strokeWidth="5" fill="none" />
          </svg>

          {destinations.map((dest, idx) => (
            <div
              key={dest.id}
              className="dest-map-pin"
              style={{ top: MAP_PINS[idx % MAP_PINS.length].top, left: MAP_PINS[idx % MAP_PINS.length].left }}
            >
              <div className="dest-map-pin-bubble">
                <span className="dest-map-pin-emoji">{dest.emoji}</span>
              </div>
              <div className="dest-map-pin-stem" />
            </div>
          ))}

          {destinations.length === 0 && (
            <div className="dest-map-empty">
              <span>🗺️</span>
              <p>여행지를 추가하면<br />지도에 표시돼요</p>
            </div>
          )}
        </div>
      </div>

      {/* ── Search ── */}
      <div className="dest-search-wrap">
        <div className="dest-search-box">
          <svg className="dest-search-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="11" cy="11" r="8" />
            <line x1="21" y1="21" x2="16.65" y2="16.65" />
          </svg>
          <input
            ref={inputRef}
            type="text"
            placeholder="여행지를 검색하세요 (예: 경복궁, 홍대)"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          {query && (
            <button className="dest-search-clear" onClick={() => setQuery('')}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
                <line x1="18" y1="6" x2="6" y2="18" />
                <line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </button>
          )}
        </div>

        {filtered.length > 0 && (
          <div className="dest-search-results">
            {filtered.map((place) => (
              <button
                key={place.id}
                className="dest-result-item"
                onClick={() => addPlace(place)}
              >
                <span className="dest-result-emoji">{place.emoji}</span>
                <div className="dest-result-info">
                  <span className="dest-result-name">{place.name}</span>
                  <span className="dest-result-meta">{place.addr} · {place.category}</span>
                </div>
                <span className="dest-result-add">+</span>
              </button>
            ))}
          </div>
        )}
      </div>

      {/* ── Destination List ── */}
      <div className="dest-list-section">
        <div className="dest-list-header">
          <div className="dest-list-title">
            <span>추가된 여행지</span>
            <span className="dest-count">{destinations.length}</span>
          </div>
          <button className="dest-invite-btn" onClick={() => setShowInvite(true)}>
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
              <circle cx="9" cy="7" r="4" />
              <line x1="23" y1="11" x2="17" y2="11" />
              <line x1="20" y1="8" x2="20" y2="14" />
            </svg>
            친구 초대
          </button>
        </div>

        {destinations.length === 0 ? (
          <div className="dest-empty-state">
            <span>📍</span>
            <p>위에서 여행지를 검색해 추가해보세요</p>
          </div>
        ) : (
          <ul className="dest-list">
            {destinations.map((dest, idx) => (
              <li key={dest.id} className="dest-item">
                <div className="dest-item-num">{idx + 1}</div>
                <span className="dest-item-emoji">{dest.emoji}</span>
                <div className="dest-item-info">
                  <span className="dest-item-name">{dest.name}</span>
                  <span className="dest-item-addr">{dest.addr}</span>
                </div>
                <span className="dest-item-cat">{dest.category}</span>
                <button className="dest-item-del" onClick={() => removePlace(dest.id)}>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
                    <line x1="18" y1="6" x2="6" y2="18" />
                    <line x1="6" y1="6" x2="18" y2="18" />
                  </svg>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* ── Invite Modal ── */}
      {showInvite && (
        <div className="modal-overlay" onClick={() => setShowInvite(false)}>
          <div className="modal-sheet" onClick={(e) => e.stopPropagation()}>
            <div className="modal-handle" />
            <h3 className="modal-title">친구 초대 & 공동 편집</h3>
            <p className="modal-desc">링크를 공유해서 친구를 초대하세요.<br />초대된 친구는 일정을 함께 편집할 수 있어요.</p>

            <div className="modal-link-box">
              <span className="modal-link-text">{shareLink || 'Loading...'}</span>
              <button
                className={`modal-link-copy${copied ? ' copied' : ''}`}
                onClick={handleCopyLink}
              >
                {copied ? '복사됨!' : '복사'}
              </button>
            </div>

            <div className="modal-share-grid">
              <button
                className={`modal-share-btn${shareStatus === 'kakao' ? ' active' : ''}`}
                onClick={handleShareKakao}
              >
                <span>💬</span>카카오톡
              </button>
              <button
                className={`modal-share-btn${shareStatus === 'web' ? ' active' : ''}`}
                onClick={handleShareWeb}
              >
                <span>📱</span>공유
              </button>
              <button
                className={`modal-share-btn${shareStatus === 'insta' ? ' active' : ''}`}
                onClick={handleShareInstagram}
              >
                <span>📸</span>인스타
              </button>
              <button
                className={`modal-share-btn${shareStatus === 'email' ? ' active' : ''}`}
                onClick={handleShareEmail}
              >
                <span>✉️</span>이메일
              </button>
            </div>

            <button className="modal-close-btn" onClick={() => setShowInvite(false)}>
              닫기
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

export default DestinationPage;