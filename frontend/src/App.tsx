import { BrowserRouter, Routes, Route, Link } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Toaster } from 'react-hot-toast'
import HomePage from './pages/HomePage'
import MenuPage from './pages/MenuPage'
import MatePage from './pages/MatePage'
import TravelPage from './pages/TravelPage'
import SpotDetailPage from './pages/SpotDetailPage'

const queryClient = new QueryClient()

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        {/* 하단 네비게이션 바 */}
        <nav className="fixed bottom-0 left-0 right-0 bg-white border-t flex justify-around py-3 z-50">
          <Link to="/" className="text-sm text-gray-600">🏠 홈</Link>
          <Link to="/menu" className="text-sm text-gray-600">🍽 메뉴</Link>
          <Link to="/mate" className="text-sm text-gray-600">👫 메이트</Link>
          <Link to="/travel" className="text-sm text-gray-600">🗺 여행</Link>
        </nav>

        {/* 페이지 영역 */}
        <main className="pb-16">
          <Routes>
            <Route path="/" element={<HomePage />} />
            <Route path="/menu" element={<MenuPage />} />
            <Route path="/mate" element={<MatePage />} />
            <Route path="/travel" element={<TravelPage />} />
            <Route path="/spots/:id" element={<SpotDetailPage />} />
          </Routes>
        </main>
      </BrowserRouter>
      <Toaster position="top-center" />
    </QueryClientProvider>
  )
}

export default App