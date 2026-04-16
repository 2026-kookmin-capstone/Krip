import React from 'react';
import '../styles/PlanSelection.css';

const PlanSelection = ({ navigate }) => {
  return (
    <div className="ps-page">

      {/* Hero */}
      <div className="ps-hero">
        <div className="ps-hero-bg" />
        <div className="ps-hero-content">
          <div className="ps-hero-icon">✈️</div>
          <h1 className="ps-hero-title">Krip</h1>
          <p className="ps-hero-sub">나만의 특별한 여행을 시작해보세요</p>
        </div>
        <div className="ps-hero-wave" />
      </div>

      {/* Section label */}
      <div className="ps-section-label">
        <span>계획 방식 선택</span>
      </div>

      {/* Cards */}
      <div className="ps-cards">

        {/* AI 카드 */}
        <button className="ps-card ps-card--ai" onClick={() => navigate('aiPreferences')}>
          <div className="ps-card-top">
            <div className="ps-card-icon-wrap ps-card-icon-wrap--ai">
              <span>🤖</span>
            </div>
            <div className="ps-card-arrow">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <line x1="5" y1="12" x2="19" y2="12" />
                <polyline points="12 5 19 12 12 19" />
              </svg>
            </div>
          </div>
          <div className="ps-card-body">
            <h2 className="ps-card-title">AI 여행 계획</h2>
            <p className="ps-card-desc">취향과 조건을 입력하면 AI가 최적의 여행 일정을 자동으로 만들어드려요</p>
          </div>
        </button>

        {/* 수동 카드 */}
        <button className="ps-card ps-card--manual" onClick={() => navigate('calendar')}>
          <div className="ps-card-top">
            <div className="ps-card-icon-wrap ps-card-icon-wrap--manual">
              <span>✏️</span>
            </div>
            <div className="ps-card-arrow">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <line x1="5" y1="12" x2="19" y2="12" />
                <polyline points="12 5 19 12 12 19" />
              </svg>
            </div>
          </div>
          <div className="ps-card-body">
            <h2 className="ps-card-title">수동 여행 계획</h2>
            <p className="ps-card-desc">날짜를 고르고 직접 여행지를 검색해서 나만의 일정을 자유롭게 만들어요</p>
          </div>
        </button>

      </div>
    </div>
  );
};

export default PlanSelection;
