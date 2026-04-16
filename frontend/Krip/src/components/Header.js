import React from 'react';
import './Header.css';

const Header = ({ title, onBack, rightElement }) => {
  return (
    <header className="header">
      <div className="header-left">
        {onBack && (
          <button className="header-back-btn" onClick={onBack} aria-label="뒤로가기">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="15 18 9 12 15 6" />
            </svg>
          </button>
        )}
      </div>
      <h2 className="header-title">{title}</h2>
      <div className="header-right">
        {rightElement || null}
      </div>
    </header>
  );
};

export default Header;
