import { useState, useRef, useEffect } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

interface Message {
  id: number;
  text: string;
  mine: boolean;
  time: string;
}

const MOCK_MESSAGES: Message[] = [
  { id: 1, text: 'Can I join your team?', mine: true, time: '10:00' },
  { id: 2, text: 'Sure!', mine: false, time: '10:01' },
  { id: 3, text: 'Ah, thanks!', mine: true, time: '10:01' },
  { id: 4, text: 'Where you at?', mine: false, time: '10:02' },
  { id: 5, text: 'o o', mine: true, time: '10:03' },
];

const NICKNAME_MAP: Record<string, string> = {
  '1': 'Mr. Krip',
  '2': '서울러버',
  '3': '맛집헌터',
};

export default function ChatRoomPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [messages, setMessages] = useState<Message[]>(MOCK_MESSAGES);
  const [input, setInput] = useState('');
  const bottomRef = useRef<HTMLDivElement>(null);

  const nickname = NICKNAME_MAP[id ?? '1'] ?? '상대방';

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSend = () => {
    if (!input.trim()) return;
    const now = new Date();
    const time = now.getHours() + ':' + String(now.getMinutes()).padStart(2, '0');
    setMessages((prev) => [
      ...prev,
      { id: Date.now(), text: input.trim(), mine: true, time },
    ]);
    setInput('');
  };

  return (
    <div className="flex flex-col h-screen bg-gray-50">
      {/* 헤더 */}
      <div className="bg-white border-b px-4 py-3 flex items-center gap-3 sticky top-0 z-10">
        <button onClick={() => navigate('/chat')} className="text-gray-600 text-lg">
          ‹
        </button>
        <div className="w-8 h-8 bg-blue-100 rounded-full flex items-center justify-center text-sm font-bold text-blue-500">
          {nickname[0]}
        </div>
        <div>
          <div className="font-semibold text-gray-900 text-sm">{nickname}</div>
        </div>
      </div>

      {/* 메시지 목록 */}
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-3 pb-24">
        {messages.map((msg) => (
          <div
            key={msg.id}
            className={'flex items-end gap-2 ' + (msg.mine ? 'flex-row-reverse' : 'flex-row')}
          >
            {!msg.mine && (
              <div className="w-7 h-7 bg-blue-100 rounded-full flex items-center justify-center text-xs font-bold text-blue-500 flex-shrink-0">
                {nickname[0]}
              </div>
            )}
            <div className={'max-w-xs px-4 py-2 rounded-2xl text-sm ' +
              (msg.mine
                ? 'bg-rose-300 text-white rounded-br-sm'
                : 'bg-white text-gray-800 shadow-sm rounded-bl-sm')}
            >
              {msg.text}
            </div>
            <span className="text-xs text-gray-400 flex-shrink-0">{msg.time}</span>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      {/* 입력창 */}
      <div className="fixed bottom-16 left-0 right-0 bg-white border-t px-4 py-3 flex items-center gap-2 z-10">
        <input
          type="text"
          placeholder="메시지 입력..."
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSend()}
          className="flex-1 bg-gray-100 rounded-full px-4 py-2.5 text-sm outline-none"
        />
        <button
          onClick={handleSend}
          className={'w-10 h-10 rounded-full flex items-center justify-center text-white font-bold flex-shrink-0 ' +
            (input.trim() ? 'bg-blue-500' : 'bg-gray-300')}
        >
          ↑
        </button>
      </div>
    </div>
  );
}