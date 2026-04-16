import React, { useState, useEffect } from 'react';
import './App.css';
import PlanSelection   from './pages/PlanSelection';
import CalendarPage    from './pages/CalendarPage';
import DestinationPage from './pages/DestinationPage';
import AIPreferences   from './pages/AIPreferences';


function App() {
  const [page,        setPage]        = useState('planSelection');
  const [travelDates, setTravelDates] = useState(null);

  useEffect(() => {
    if (window.Kakao) {
      if (!window.Kakao.isInitialized()) {
        window.Kakao.init(process.env.REACT_APP_KAKAO_APP_KEY);
        console.info('[Kakao] SDK 초기화 성공');
      }
    }
  }, []);

  const navigate = (targetPage, data) => {
    if (targetPage === 'destination' && data) {
      setTravelDates(data);
    }
    setPage(targetPage);
    window.scrollTo(0, 0);
  };

  return (
    <div className="phone-frame">
      {page === 'planSelection' && <PlanSelection   navigate={navigate} />}
      {page === 'calendar'      && <CalendarPage    navigate={navigate} />}
      {page === 'destination'   && <DestinationPage navigate={navigate} travelDates={travelDates} />}
      {page === 'aiPreferences' && <AIPreferences   navigate={navigate} />}
    </div>
  );
}

export default App;