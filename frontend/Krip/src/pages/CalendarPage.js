import React, { useState } from 'react';
import '../styles/CalendarPage.css';
import Header from '../components/Header';

const MONTH_NAMES = ['1월','2월','3월','4월','5월','6월','7월','8월','9월','10월','11월','12월'];
const DAY_LABELS  = ['일','월','화','수','목','금','토'];

function sameDay(a, b) {
  return a && b && a.toDateString() === b.toDateString();
}

function inRange(d, start, end) {
  if (!start || !end) return false;
  return d > start && d < end;
}

const CalendarPage = ({ navigate }) => {
  const today = new Date();
  today.setHours(0, 0, 0, 0);

  const [viewYear,  setViewYear]  = useState(today.getFullYear());
  const [viewMonth, setViewMonth] = useState(today.getMonth());
  const [startDate, setStartDate] = useState(null);
  const [endDate,   setEndDate]   = useState(null);

  /* ── navigation ── */
  const prevMonth = () => {
    if (viewMonth === 0) { setViewMonth(11); setViewYear(y => y - 1); }
    else setViewMonth(m => m - 1);
  };
  const nextMonth = () => {
    if (viewMonth === 11) { setViewMonth(0); setViewYear(y => y + 1); }
    else setViewMonth(m => m + 1);
  };

  /* ── date click ── */
  const handleClick = (day) => {
    const clicked = new Date(viewYear, viewMonth, day);
    if (clicked < today) return;

    if (!startDate || (startDate && endDate)) {
      setStartDate(clicked);
      setEndDate(null);
    } else {
      if (clicked < startDate) {
        setEndDate(startDate);
        setStartDate(clicked);
      } else if (sameDay(clicked, startDate)) {
        setStartDate(null);
      } else {
        setEndDate(clicked);
      }
    }
  };

  /* ── cell classes ── */
  const cellClass = (day) => {
    if (!day) return 'cal-cell cal-cell--empty';
    const d = new Date(viewYear, viewMonth, day);
    const past    = d < today;
    const isStart = sameDay(d, startDate);
    const isEnd   = sameDay(d, endDate);
    const range   = inRange(d, startDate, endDate);

    const classes = ['cal-cell'];
    if (past)    classes.push('cal-cell--past');
    if (isStart) classes.push('cal-cell--start');
    if (isEnd)   classes.push('cal-cell--end');
    if (range)   classes.push('cal-cell--range');
    if (sameDay(d, today) && !isStart && !isEnd) classes.push('cal-cell--today');
    return classes.join(' ');
  };

  /* ── grid cells ── */
  const firstWeekday   = new Date(viewYear, viewMonth, 1).getDay();
  const daysInMonth    = new Date(viewYear, viewMonth + 1, 0).getDate();
  const cells = [];
  for (let i = 0; i < firstWeekday; i++) cells.push(null);
  for (let d = 1; d <= daysInMonth; d++) cells.push(d);

  /* ── summary ── */
  const nights = startDate && endDate
    ? Math.round((endDate - startDate) / 86400000)
    : 0;
  const fmt = (d) => d ? `${d.getMonth() + 1}월 ${d.getDate()}일` : '—';

  const handleConfirm = () => {
    if (startDate && endDate) navigate('destination', { startDate, endDate });
  };

  return (
    <div className="cal-page">
      <Header title="날짜 선택" onBack={() => navigate('planSelection')} />

      {/* Month navigator */}
      <div className="cal-nav">
        <button className="cal-nav-btn" onClick={prevMonth}>
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="15 18 9 12 15 6" />
          </svg>
        </button>
        <span className="cal-nav-label">{viewYear}년 {MONTH_NAMES[viewMonth]}</span>
        <button className="cal-nav-btn" onClick={nextMonth}>
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="9 18 15 12 9 6" />
          </svg>
        </button>
      </div>

      {/* Day names */}
      <div className="cal-day-names">
        {DAY_LABELS.map((d, i) => (
          <span key={d} className={i === 0 ? 'sun' : i === 6 ? 'sat' : ''}>{d}</span>
        ))}
      </div>

      {/* Grid */}
      <div className="cal-grid">
        {cells.map((day, idx) => (
          <div
            key={idx}
            className={cellClass(day)}
            onClick={() => day && handleClick(day)}
          >
            {day && <span className="cal-cell-inner">{day}</span>}
          </div>
        ))}
      </div>

      {/* Summary bar */}
      <div className="cal-summary">
        <div className="cal-summary-row">
          <div className="cal-summary-item">
            <span className="cal-summary-lbl">출발</span>
            <span className="cal-summary-val">{fmt(startDate)}</span>
          </div>
          <div className="cal-summary-middle">
            {nights > 0 && (
              <span className="cal-nights-badge">{nights}박 {nights + 1}일</span>
            )}
          </div>
          <div className="cal-summary-item cal-summary-item--right">
            <span className="cal-summary-lbl">도착</span>
            <span className="cal-summary-val">{fmt(endDate)}</span>
          </div>
        </div>

        <button
          className={`cal-confirm-btn${startDate && endDate ? ' cal-confirm-btn--active' : ''}`}
          onClick={handleConfirm}
          disabled={!startDate || !endDate}
        >
          여행지 추가하기
        </button>
      </div>
    </div>
  );
};

export default CalendarPage;
