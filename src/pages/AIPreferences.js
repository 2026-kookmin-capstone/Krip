import React, { useState } from 'react';
import '../styles/AIPreferences.css';
import Header from '../components/Header';

/* ── Data ── */
const TRAVEL_STYLES = [
  { id: 'activity',  label: '체험·액티비티', emoji: '🏄' },
  { id: 'landmark',  label: '유명 관광지',   emoji: '🏛️' },
  { id: 'healing',   label: '휴양·힐링',     emoji: '🧘' },
  { id: 'culture',   label: '관광·문화', emoji: '🎭' },
  { id: 'shopping',  label: '쇼핑',          emoji: '🛍️' },
  { id: 'food',      label: '맛집 탐방',      emoji: '🍽️' },
  { id: 'photo',     label: '사진·감성',      emoji: '📸' },
  { id: 'festival',  label: '축제·이벤트',    emoji: '🎊' },
];

const DURATIONS = [
  { id: 'day',  label: '당일치기', nights: 0 },
  { id: '1n2d', label: '1박 2일',  nights: 1 },
  { id: '2n3d', label: '2박 3일',  nights: 2 },
  { id: '3n4d', label: '3박 4일',  nights: 3 },
];

const COMPANIONS = [
  { id: 'solo',    label: '혼자',        emoji: '🧍' },
  { id: 'couple',  label: '연인',        emoji: '💑' },
  { id: 'married', label: '부부',        emoji: '💍' },
  { id: 'friends', label: '친구·동료',   emoji: '👫' },
  { id: 'parents', label: '가족(부모님)', emoji: '👨‍👩‍👦' },
  { id: 'kids',    label: '가족(아이)',   emoji: '🧒' },
];

const DENSITIES = [
  { id: 'packed', label: '빽빽하게', emoji: '⚡', desc: '많은 곳을 알차게' },
  { id: 'loose',  label: '널널하게', emoji: '🌊', desc: '여유롭게 천천히' },
];

const FOOD_PREFS = [
  { id: 'halal',  label: '할랄', emoji: '☪️' },
  { id: 'vegan',  label: '채식', emoji: '🥗' },
];

/* ── Budget utils ── */
const formatBudget = (val) => {
  if (val >= 100_0000) return `${(val / 100_0000).toFixed(1)}백만원`;
  if (val >= 10000)    return `${Math.round(val / 10000)}만원`;
  return `${val.toLocaleString()}원`;
};

const toBudgetCategory = (val) => {
  if (val < 300000)  return '저예산';
  if (val < 800000)  return '중간';
  return '고예산';
};

const toApiStyle = (ids) => {
  const map = { activity: '체험/액티비티', landmark: '유명 관광지', healing: '자연/공원', culture: '문화/역사', shopping: '쇼핑', food: '맛집 탐방', photo: '카페', festival: '축제/이벤트' };
  return ids.map(id => map[id] || id);
};

/* ────────────────────────────── Component ────────────────────────────── */
const AIPreferences = ({ navigate }) => {
  const [styles,      setStyles]      = useState([]);
  const [duration,    setDuration]    = useState('');
  const [budget,      setBudget]      = useState(400000);
  const [companion,   setCompanion]   = useState('');
  const [density,     setDensity]     = useState('');
  const [foodPrefs,   setFoodPrefs]   = useState([]);
  const [allergy,     setAllergy]     = useState('');
  const [mobility,    setMobility]    = useState(false);
  const [showPayload, setShowPayload] = useState(false);

  /* toggle helpers */
  const toggleStyle = (id) =>
    setStyles(prev => prev.includes(id) ? prev.filter(s => s !== id) : [...prev, id]);

  const toggleFood = (id) =>
    setFoodPrefs(prev => prev.includes(id) ? prev.filter(f => f !== id) : [...prev, id]);

  /* readiness check */
  const isReady = styles.length > 0 && duration && companion && density;

  /* API payload */
  const payload = {
    travel_days:      DURATIONS.find(d => d.id === duration)?.nights ?? null,
    travel_style:     toApiStyle(styles),
    budget:           toBudgetCategory(budget),
    companion_type:   companion,
    schedule_density: density === 'packed' ? '빽빽하게' : density === 'loose' ? '널널하게' : null,
    food_preferences: [...foodPrefs, ...(allergy ? [`알레르기: ${allergy}`] : [])],
    mobility_support: mobility,
  };

  return (
    <div className="ai-page">
      <Header title="AI 여행 계획" onBack={() => navigate('planSelection')} />

      <div className="ai-scroll">

        {/* ── 여행 스타일 ── */}
        <section className="ai-section">
          <div className="ai-section-header">
            <h3>여행 스타일</h3>
            <span className="ai-required">필수</span>
            <span className="ai-multi-hint">중복 선택 가능</span>
          </div>
          <div className="ai-token-grid">
            {TRAVEL_STYLES.map(s => (
              <button
                key={s.id}
                className={`ai-token${styles.includes(s.id) ? ' ai-token--on' : ''}`}
                onClick={() => toggleStyle(s.id)}
              >
                <span>{s.emoji}</span>
                <span>{s.label}</span>
              </button>
            ))}
          </div>
        </section>

        {/* ── 여행 기간 ── */}
        <section className="ai-section">
          <div className="ai-section-header">
            <h3>여행 기간</h3>
            <span className="ai-required">필수</span>
          </div>
          <div className="ai-row-chips">
            {DURATIONS.map(d => (
              <button
                key={d.id}
                className={`ai-chip${duration === d.id ? ' ai-chip--on' : ''}`}
                onClick={() => setDuration(d.id)}
              >
                {d.label}
              </button>
            ))}
          </div>
        </section>

        {/* ── 여행 예산 ── */}
        <section className="ai-section">
          <div className="ai-section-header">
            <h3>여행 예산</h3>
            <span className="ai-sub-label">1인 기준</span>
          </div>
          <div className="ai-budget-display">
            <span className="ai-budget-val">{formatBudget(budget)}</span>
            <span className={`ai-budget-cat ai-budget-cat--${toBudgetCategory(budget) === '저예산' ? 'low' : getBudgetCatId(budget)}`}>
              {toBudgetCategory(budget)}
            </span>
          </div>
          <div className="ai-slider-wrap">
            <input
              type="range"
              min={50000}
              max={2000000}
              step={50000}
              value={budget}
              onChange={e => setBudget(Number(e.target.value))}
              className="ai-slider"
              style={{ '--pct': `${((budget - 50000) / (2000000 - 50000)) * 100}%` }}
            />
            <div className="ai-slider-labels">
              <span>5만원</span>
              <span>200만원</span>
            </div>
          </div>
        </section>

        {/* ── 동행 유형 ── */}
        <section className="ai-section">
          <div className="ai-section-header">
            <h3>동행 유형</h3>
            <span className="ai-required">필수</span>
          </div>
          <div className="ai-token-grid">
            {COMPANIONS.map(c => (
              <button
                key={c.id}
                className={`ai-token${companion === c.id ? ' ai-token--on' : ''}`}
                onClick={() => setCompanion(c.id)}
              >
                <span>{c.emoji}</span>
                <span>{c.label}</span>
              </button>
            ))}
          </div>
        </section>

        {/* ── 선호 일정 ── */}
        <section className="ai-section">
          <div className="ai-section-header">
            <h3>선호 일정</h3>
            <span className="ai-required">필수</span>
          </div>
          <div className="ai-density-row">
            {DENSITIES.map(d => (
              <button
                key={d.id}
                className={`ai-density-btn${density === d.id ? ' ai-density-btn--on' : ''}`}
                onClick={() => setDensity(d.id)}
              >
                <span className="ai-density-emoji">{d.emoji}</span>
                <span className="ai-density-label">{d.label}</span>
                <span className="ai-density-desc">{d.desc}</span>
              </button>
            ))}
          </div>
        </section>

        {/* ── 취향 메뉴 (선택) ── */}
        <section className="ai-section">
          <div className="ai-section-header">
            <h3>취향 메뉴</h3>
            <span className="ai-optional">선택</span>
          </div>
          <div className="ai-row-chips ai-row-chips--gap">
            {FOOD_PREFS.map(f => (
              <button
                key={f.id}
                className={`ai-chip${foodPrefs.includes(f.id) ? ' ai-chip--on' : ''}`}
                onClick={() => toggleFood(f.id)}
              >
                {f.emoji} {f.label}
              </button>
            ))}
          </div>
          <div className="ai-allergy-box">
            <label className="ai-allergy-label">
              <span>⚠️</span> 알레르기 정보
            </label>
            <input
              className="ai-allergy-input"
              type="text"
              placeholder="예: 견과류, 갑각류, 밀 (직접 입력)"
              value={allergy}
              onChange={e => setAllergy(e.target.value)}
            />
          </div>
        </section>

        {/* ── 교통약자 ── */}
        <section className="ai-section ai-section--toggle">
          <div className="ai-toggle-row">
            <div className="ai-toggle-info">
              <h3>교통약자 동행</h3>
              <p>이동 경로 계획 시 참고해요</p>
            </div>
            <button
              className={`ai-toggle${mobility ? ' ai-toggle--on' : ''}`}
              onClick={() => setMobility(m => !m)}
              aria-label="교통약자 토글"
            >
              <div className="ai-toggle-thumb" />
            </button>
          </div>
          {mobility && (
            <div className="ai-mobility-notice">
              ♿ 엘리베이터·휠체어 접근 가능한 장소 위주로 추천돼요
            </div>
          )}
        </section>

        {/* ── Submit ── */}
        <div className="ai-submit-wrap">
          {!isReady && (
            <p className="ai-submit-hint">여행 스타일, 기간, 동행 유형, 선호 일정을 선택해주세요</p>
          )}
          <button
            className={`ai-submit-btn${isReady ? ' ai-submit-btn--active' : ''}`}
            disabled={!isReady}
          >
            ✨ AI 일정 생성하기
          </button>
        </div>

      </div>
    </div>
  );
};

function getBudgetCatId(val) {
  if (val < 300000) return 'low';
  if (val < 800000) return 'mid';
  return 'high';
}

export default AIPreferences;
