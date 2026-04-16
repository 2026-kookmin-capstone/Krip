import { BrowserRouter, Routes, Route, Link, useLocation } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Toaster } from 'react-hot-toast'
import HomePage from './pages/HomePage'
import MenuPage from './pages/MenuPage'
import MatePage from './pages/MatePage'
import TravelPage from './pages/TravelPage'
import SpotDetailPage from './pages/SpotDetailPage'
import ChatPage from './pages/ChatPage'
import ChatRoomPage from './pages/ChatRoomPage'
import MyPage from './pages/MyPage'
import ProfilePage from './pages/ProfilePage'

const queryClient = new QueryClient()

function NavBar() {
  const location = useLocation()

  // 채팅방은 풀스크린이라 네비바 숨김
  if (location.pathname.startsWith('/chat/')) return null

  const navItems = [
    { to: '/',        icon: '🏠', label: '홈' },
    { to: '/menu',    icon: '🍽', label: '메뉴' },
    { to: '/mate',    icon: '👫', label: '메이트' },
    { to: '/chat',    icon: '💬', label: '채팅' },
    { to: '/mypage',  icon: '👤', label: '마이' },
  ]

  return (
    <nav className="fixed bottom-0 left-0 right-0 bg-white border-t border-gray-100 flex justify-around py-2 z-50">
      {navItems.map(({ to, icon, label }) => {
        const isActive = to === '/'
          ? location.pathname === '/'
          : location.pathname.startsWith(to)
        return (
          <Link
            key={to}
            to={to}
            className={`flex flex-col items-center gap-0.5 px-3 py-1 rounded-xl transition-colors ${
              isActive ? 'text-pink-500' : 'text-gray-400'
            }`}
          >
            <span className="text-xl">{icon}</span>
            <span className="text-xs font-medium">{label}</span>
          </Link>
        )
      })}
    </nav>
  )
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <main className="pb-16">
          <Routes>
            <Route path="/"           element={<HomePage />} />
            <Route path="/menu"       element={<MenuPage />} />
            <Route path="/mate"       element={<MatePage />} />
            <Route path="/travel"     element={<TravelPage />} />
            <Route path="/spots/:id"  element={<SpotDetailPage />} />
            <Route path="/chat"       element={<ChatPage />} />
            <Route path="/chat/:id"   element={<ChatRoomPage />} />
            <Route path="/mypage"     element={<MyPage />} />
            <Route path="/profile/:id" element={<ProfilePage />} />
          </Routes>
        </main>
        <NavBar />
        <Toaster position="top-center" />
      </BrowserRouter>
    </QueryClientProvider>
  )
}

export default App
