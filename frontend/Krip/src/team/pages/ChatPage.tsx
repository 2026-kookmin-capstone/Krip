import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

interface ChatRoom {
  id: number;
  nickname: string;
  lastMessage: string;
  time: string;
  unread: number;
  hidden: boolean;
}

interface FriendRequest {
  id: number;
  nickname: string;
}

const MOCK_CHATS: ChatRoom[] = [
  { id: 1, nickname: 'Mr. Krip', lastMessage: '한강 같이 가실분?', time: '5min', unread: 2, hidden: false },
  { id: 2, nickname: '서울러버', lastMessage: '경복궁 어떠세요?', time: '1h', unread: 0, hidden: false },
  { id: 3, nickname: '맛집헌터', lastMessage: '홍대에서 만나요!', time: '2h', unread: 1, hidden: false },
];

const MOCK_REQUESTS: FriendRequest[] = [
  { id: 1, nickname: 'Mr. Krip' },
  { id: 2, nickname: '서울러버' },
  { id: 3, nickname: '여행왕' },
];

export default function ChatPage() {
  const navigate = useNavigate();
  const [tab, setTab] = useState<'chat' | 'request'>('chat');
  const [chats, setChats] = useState<ChatRoom[]>(MOCK_CHATS);
  const [requests, setRequests] = useState<FriendRequest[]>(MOCK_REQUESTS);
  const [menuOpenId, setMenuOpenId] = useState<number | null>(null);
  const [showHidden, setShowHidden] = useState(false);

  const visibleChats = chats.filter((c) => !c.hidden);
  const hiddenChats = chats.filter((c) => c.hidden);

  const handleHide = (id: number) => {
    setChats((prev) => prev.map((c) => c.id === id ? { ...c, hidden: true } : c));
    setMenuOpenId(null);
  };

  const handleUnhide = (id: number) => {
    setChats((prev) => prev.map((c) => c.id === id ? { ...c, hidden: false } : c));
  };

  const handleAccept = (id: number) => {
    setRequests((prev) => prev.filter((r) => r.id !== id));
    alert('친구 요청을 수락했어요! 🎉');
  };

  const handleReject = (id: number) => {
    setRequests((prev) => prev.filter((r) => r.id !== id));
  };

  return (
    <div className="min-h-screen bg-white">
      {/* 헤더 */}
      <div className="px-4 pt-10 pb-4 bg-white border-b">
        <h1 className="text-2xl font-bold text-gray-900">Chat</h1>
      </div>

      {/* 채팅 목록 */}
      {tab === 'chat' && (
        <div>
          {/* 일반 채팅 목록 */}
          <div className="divide-y">
            {visibleChats.length === 0 && (
              <div className="text-center py-12 text-gray-400 text-sm">채팅방이 없어요</div>
            )}
            {visibleChats.map((room) => (
              <div key={room.id} className="relative">
                <div
                  className="flex items-center gap-3 px-4 py-4 cursor-pointer active:bg-gray-50"
                  onClick={() => {
                    if (menuOpenId === room.id) {
                      setMenuOpenId(null);
                    } else {
                      navigate('/chat/' + room.id);
                    }
                  }}
                >
                  {/* 아바타 */}
                  <div className="w-12 h-12 bg-blue-100 rounded-full flex items-center justify-center text-lg font-bold text-blue-500 flex-shrink-0">
                    {room.nickname[0]}
                  </div>
                  {/* 내용 */}
                  <div className="flex-1 min-w-0">
                    <div className="font-semibold text-gray-900">{room.nickname}</div>
                    <div className="text-sm text-gray-400 truncate">{room.lastMessage}</div>
                  </div>
                  {/* 시간 + 뱃지 */}
                  <div className="flex flex-col items-end gap-1 flex-shrink-0">
                    <span className="text-xs text-gray-400">{room.time}</span>
                    {room.unread > 0 && (
                      <span className="bg-orange-400 text-white text-xs w-5 h-5 rounded-full flex items-center justify-center font-bold">
                        {room.unread}
                      </span>
                    )}
                  </div>
                  {/* ··· 메뉴 버튼 */}
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      setMenuOpenId(menuOpenId === room.id ? null : room.id);
                    }}
                    className="ml-2 text-gray-300 text-xl px-1"
                  >
                    ···
                  </button>
                </div>

                {/* 드롭다운 메뉴 */}
                {menuOpenId === room.id && (
                  <div className="absolute right-4 top-12 bg-white border border-gray-200 rounded-xl shadow-lg z-20 overflow-hidden">
                    <button
                      onClick={() => handleHide(room.id)}
                      className="flex items-center gap-2 px-5 py-3 text-sm text-gray-700 hover:bg-gray-50 w-full text-left"
                    >
                      <span>🙈</span>
                      <span>채팅방 숨기기</span>
                    </button>
                  </div>
                )}
              </div>
            ))}
          </div>

          {/* 숨긴 채팅 토글 */}
          {hiddenChats.length > 0 && (
            <div className="mt-4">
              <button
                onClick={() => setShowHidden(!showHidden)}
                className="w-full flex items-center justify-between px-4 py-3 text-sm text-gray-400 bg-gray-50 border-t border-b"
              >
                <div className="flex items-center gap-2">
                  <span>🙈</span>
                  <span>{'숨긴 채팅 ' + hiddenChats.length + '개'}</span>
                </div>
                <span>{showHidden ? '▲' : '▼'}</span>
              </button>

              {showHidden && (
                <div className="divide-y bg-gray-50">
                  {hiddenChats.map((room) => (
                    <div key={room.id} className="flex items-center gap-3 px-4 py-4">
                      <div className="w-12 h-12 bg-gray-200 rounded-full flex items-center justify-center text-lg font-bold text-gray-400 flex-shrink-0">
                        {room.nickname[0]}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="font-semibold text-gray-400">{room.nickname}</div>
                        <div className="text-sm text-gray-300 truncate">{room.lastMessage}</div>
                      </div>
                      <button
                        onClick={() => handleUnhide(room.id)}
                        className="text-xs text-blue-500 font-medium px-3 py-1.5 border border-blue-200 rounded-full flex-shrink-0"
                      >
                        숨기기 해제
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* 친구 추가 요청 */}
      {tab === 'request' && (
        <div className="px-4 py-4">
          <h2 className="text-xl font-bold text-gray-900 mb-4">친구 추가 요청</h2>
          {requests.length === 0 && (
            <div className="text-center py-12 text-gray-400 text-sm">새로운 친구 요청이 없어요</div>
          )}
          <div className="divide-y">
            {requests.map((req) => (
              <div key={req.id} className="flex items-center gap-3 py-4">
                <div className="w-12 h-12 bg-blue-100 rounded-full flex items-center justify-center text-lg font-bold text-blue-500 flex-shrink-0">
                  {req.nickname[0]}
                </div>
                <div className="flex-1">
                  <div className="font-semibold text-gray-900">{req.nickname}</div>
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={() => handleAccept(req.id)}
                    className="bg-gray-800 text-white text-xs px-3 py-1.5 rounded-full font-medium"
                  >
                    수락
                  </button>
                  <button
                    onClick={() => handleReject(req.id)}
                    className="bg-gray-200 text-gray-600 text-xs px-3 py-1.5 rounded-full font-medium"
                  >
                    거절
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 하단 탭 - 와이어프레임 스타일 */}
      <div className="fixed bottom-16 left-0 right-0 bg-white border-t flex z-10">
        <button
          onClick={() => setTab('chat')}
          className={'flex-1 py-3 text-sm font-semibold border-b-2 transition-colors ' +
            (tab === 'chat'
              ? 'border-gray-900 text-gray-900'
              : 'border-transparent text-gray-400')}
        >
          채팅
        </button>
        <button
          onClick={() => setTab('request')}
          className={'flex-1 py-3 text-sm font-semibold border-b-2 relative transition-colors ' +
            (tab === 'request'
              ? 'border-orange-400 text-orange-500'
              : 'border-transparent text-gray-400')}
        >
          친구 추가 요청
          {requests.length > 0 && (
            <span className="absolute top-2 right-6 bg-orange-400 text-white text-xs min-w-[18px] h-[18px] px-1 rounded-full flex items-center justify-center font-bold">
              {requests.length}
            </span>
          )}
        </button>
      </div>

      {/* 배경 클릭시 메뉴 닫기 */}
      {menuOpenId !== null && (
        <div className="fixed inset-0 z-10" onClick={() => setMenuOpenId(null)} />
      )}
    </div>
  );
}