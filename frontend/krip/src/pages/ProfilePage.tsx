import { useParams, useNavigate } from 'react-router-dom';
import { useState } from 'react';

interface UserProfile {
  id: number;
  nickname: string;
  bio: string;
  age: number;
  gender: string;
  travel_style: string[];
  posts: { id: number; emoji: string; title: string }[];
}

const MOCK_PROFILES: Record<string, UserProfile> = {
  '1': {
    id: 1,
    nickname: 'Mr. Krip',
    bio: '서울 여행을 사랑하는 여행자 ✈️',
    age: 25,
    gender: 'Male',
    travel_style: ['액티브', '맛집탐방', '사진촬영'],
    posts: [
      { id: 1, emoji: '🏯', title: '경복궁 방문' },
      { id: 2, emoji: '🍜', title: '광장시장 먹방' },
      { id: 3, emoji: '🌊', title: '한강 피크닉' },
      { id: 4, emoji: '🎨', title: '홍대 거리 예술' },
      { id: 5, emoji: '🗼', title: '남산타워 야경' },
      { id: 6, emoji: '🛍️', title: '명동 쇼핑' },
    ],
  },
  '2': {
    id: 2,
    nickname: '서울러버',
    bio: '감성 여행을 즐기는 사람 📸',
    age: 28,
    gender: 'Female',
    travel_style: ['감성여행', '사진촬영', '힐링'],
    posts: [
      { id: 1, emoji: '🏘️', title: '북촌 한옥마을' },
      { id: 2, emoji: '🌸', title: '창덕궁 후원' },
      { id: 3, emoji: '☕', title: '연남동 카페' },
    ],
  },
  '3': {
    id: 3,
    nickname: '맛집헌터',
    bio: '맛집 탐방 전문가 🍔',
    age: 23,
    gender: 'Male',
    travel_style: ['맛집탐방', '힐링'],
    posts: [
      { id: 1, emoji: '🍔', title: '이태원 버거' },
      { id: 2, emoji: '🍣', title: '신사동 스시' },
      { id: 3, emoji: '🥘', title: '을지로 노포' },
      { id: 4, emoji: '🍰', title: '성수동 디저트' },
    ],
  },
};

export default function ProfilePage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [friendRequested, setFriendRequested] = useState(false);

  const profile = MOCK_PROFILES[id ?? '1'] ?? MOCK_PROFILES['1'];

  return (
    <div className="min-h-screen bg-gray-50 pb-24">
      {/* 헤더 */}
      <div className="bg-white border-b px-4 py-4 flex items-center gap-3 sticky top-0 z-10">
        <button onClick={() => navigate(-1)} className="text-gray-600 text-xl">‹</button>
        <h2 className="text-lg font-bold text-gray-900">{profile.nickname}</h2>
      </div>

      {/* 프로필 정보 */}
      <div className="bg-white px-6 py-6 flex flex-col items-center border-b">
        {/* 프로필 이미지 */}
        <div className="w-20 h-20 bg-blue-100 rounded-full flex items-center justify-center text-4xl mb-3">
          🧑‍💼
        </div>
        <div className="text-xl font-bold text-gray-900 mb-1">{profile.nickname}</div>
        <div className="text-sm text-gray-400 mb-3">{profile.bio}</div>

        {/* 정보 태그 */}
        <div className="flex gap-2 flex-wrap justify-center mb-4">
          <span className="bg-purple-50 text-purple-600 text-xs px-3 py-1 rounded-full">
            {'Age ' + profile.age}
          </span>
          <span className="bg-pink-50 text-pink-600 text-xs px-3 py-1 rounded-full">
            {profile.gender}
          </span>
          {profile.travel_style.map((style) => (
            <span key={style} className="bg-blue-50 text-blue-600 text-xs px-3 py-1 rounded-full">
              {style}
            </span>
          ))}
        </div>

        {/* 버튼 */}
        <div className="flex gap-3 w-full">
          <button
            onClick={() => { setFriendRequested(true); alert('친구 요청을 보냈어요! 🎉'); }}
            disabled={friendRequested}
            className={'flex-1 py-2.5 rounded-xl text-sm font-semibold ' +
              (friendRequested
                ? 'bg-gray-200 text-gray-400'
                : 'bg-gray-900 text-white active:bg-gray-700')}
          >
            {friendRequested ? '요청 완료' : '친구 추가'}
          </button>
          <button
            onClick={() => navigate('/chat')}
            className="flex-1 py-2.5 rounded-xl text-sm font-semibold bg-rose-700 text-white active:bg-rose-800"
          >
            채팅 보내기
          </button>
        </div>
      </div>

      {/* 게시글 수 */}
      <div className="bg-white border-b px-4 py-3 flex items-center gap-2">
        <span className="text-sm font-medium text-gray-700">게시글</span>
        <span className="bg-gray-100 text-gray-600 text-xs px-2 py-0.5 rounded-full font-medium">
          {profile.posts.length}
        </span>
      </div>

      {/* 게시글 그리드 */}
      <div className="grid grid-cols-3 gap-0.5 bg-gray-200">
        {profile.posts.map((post) => (
          <div
            key={post.id}
            className="bg-white aspect-square flex flex-col items-center justify-center gap-1 cursor-pointer active:bg-gray-50"
          >
            <span className="text-4xl">{post.emoji}</span>
            <span className="text-xs text-gray-500 text-center px-2 line-clamp-1">{post.title}</span>
          </div>
        ))}
      </div>

      {/* 게시글 없을 때 */}
      {profile.posts.length === 0 && (
        <div className="text-center py-16 text-gray-400 text-sm">
          아직 게시글이 없어요
        </div>
      )}
    </div>
  );
}