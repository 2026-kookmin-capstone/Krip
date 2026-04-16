import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  getTripMatePosts,
  createTripMatePost,
  updateTripMatePost,
  deleteTripMatePost,
  searchTripMatePosts,
  toggleLike,
  saveDraft,
  getDraft,
  deleteDraft,
  type TripMatePost,
  type CompanionType,
  type PreferredGender,
} from '../api/mate';
import {
  getSearchHistory,
  deleteSearchHistoryOne,
  deleteSearchHistoryAll,
} from '../api/searchHistory';
import { uploadImages } from '../api/image';
import { getMyProfile } from '../api/auth';

const COMPANION_LABELS: Record<CompanionType | 'all', string> = {
  all: '전체',
  sole: '혼자',
  friend: '친구',
  couple: '커플',
  family: '가족',
};

const COMPANION_FILTERS = ['all', 'sole', 'friend', 'couple', 'family'] as const;

const GENDER_LABELS: Record<PreferredGender, string> = {
  any: '무관',
  male: '남성',
  female: '여성',
};

function MatePage() {
  const navigate = useNavigate();
  const [tab, setTab] = useState<'list' | 'write'>('list');

  // ── 목록 상태 ──
  const [posts, setPosts] = useState<TripMatePost[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [filter, setFilter] = useState<CompanionType | 'all'>('all');

  // ── 검색 상태 ──
  const [searchInput, setSearchInput] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [searchHistory, setSearchHistory] = useState<string[]>([]);
  const [showHistory, setShowHistory] = useState(false);
  const searchRef = useRef<HTMLInputElement>(null);

  // ── 프로필 모달 ──
  const [selectedPost, setSelectedPost] = useState<TripMatePost | null>(null);
  const [friendRequested, setFriendRequested] = useState<Set<string>>(new Set());

  // ── 채팅 팝업 ──
  const [chatTarget, setChatTarget] = useState<TripMatePost | null>(null);
  const [chatMsg, setChatMsg] = useState('');

  // ── 수정/삭제 ──
  const [currentUserId, setCurrentUserId] = useState<string | null>(null);
  const [menuOpenPostId, setMenuOpenPostId] = useState<string | null>(null);
  const [editingPostId, setEditingPostId] = useState<string | null>(null);

  // ── 글쓰기 폼 ──
  const [form, setForm] = useState({
    title: '',
    content: '',
    region: '',
    travel_start_date: '',
    travel_end_date: '',
    companion_type: 'friend' as CompanionType,
    preferred_gender: 'any' as PreferredGender,
    preferred_age_min: 20,
    preferred_age_max: 35,
  });
  const [submitting, setSubmitting] = useState(false);
  const [draftSaving, setDraftSaving] = useState(false);
  const draftTimer = useRef<ReturnType<typeof setInterval> | null>(null);

  // ── 이미지 업로드 ──
  const [imageUrls, setImageUrls] = useState<string[]>([]);       // 서버에서 받은 URL
  const [imagePreviews, setImagePreviews] = useState<string[]>([]); // 로컬 미리보기
  const [imageUploading, setImageUploading] = useState(false);
  const imageInputRef = useRef<HTMLInputElement>(null);

  // ── 검색기록 로드 (서버에서) ──
  const loadSearchHistory = async () => {
    try {
      const res = await getSearchHistory();
      setSearchHistory(res.histories.map((h) => h.search_name));
    } catch {
      // 로그인 전이거나 서버 에러 시 무시
    }
  };

  // ── 데이터 로드 ──
  const fetchPosts = async (cursor?: string) => {
    setLoading(true);
    try {
      let res;
      if (searchQuery) {
        res = await searchTripMatePosts(searchQuery, cursor);
      } else {
        res = await getTripMatePosts(cursor);
      }

      // 백엔드 응답 구조 확인용 (연결 확인 후 제거 예정)
      console.log('📦 API 응답:', res);

      // 응답 형식이 배열로 올 수도 있고 { posts: [] } 형식일 수도 있어서 둘 다 처리
      const newPosts = Array.isArray(res) ? res : (res?.posts ?? []);
      const nextCur = Array.isArray(res) ? null : (res?.next_cursor ?? null);

      if (cursor) {
        setPosts((prev) => [...prev, ...newPosts]);
      } else {
        setPosts(newPosts);
      }
      setNextCursor(nextCur);
    } catch (e) {
      console.error('❌ API 에러:', e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchPosts();
  }, [searchQuery]);

  // 마운트 시 서버에서 검색기록 + 내 user_id 불러오기
  useEffect(() => {
    loadSearchHistory();
    getMyProfile().then((p) => setCurrentUserId(p.user_id)).catch(() => {});
  }, []);

  // ── 임시저장 불러오기 ──
  useEffect(() => {
    if (tab === 'write') {
      getDraft().then((draft) => {
        if (draft) {
          setForm({
            title: draft.title ?? '',
            content: draft.content ?? '',
            region: draft.region ?? '',
            travel_start_date: draft.travel_start_date ?? '',
            travel_end_date: draft.travel_end_date ?? '',
            companion_type: (draft.companion_type as CompanionType) ?? 'friend',
            preferred_gender: (draft.preferred_gender as PreferredGender) ?? 'any',
            preferred_age_min: draft.preferred_age_min ?? 20,
            preferred_age_max: draft.preferred_age_max ?? 35,
          });
        }
      });
      draftTimer.current = setInterval(() => handleAutoSaveDraft(), 30000);
    }
    return () => {
      if (draftTimer.current) clearInterval(draftTimer.current);
    };
  }, [tab]);

  // ── 이미지 선택 → 서버 업로드 ──
  const handleImageSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []);
    if (!files.length) return;

    // 최대 10개 제한
    const remaining = 10 - imageUrls.length;
    const selected = files.slice(0, remaining);

    // 로컬 미리보기 즉시 추가
    const previews = selected.map((f) => URL.createObjectURL(f));
    setImagePreviews((prev) => [...prev, ...previews]);
    setImageUploading(true);

    try {
      const res = await uploadImages(selected);
      const urls = res.images.map((img) => img.image_url);
      setImageUrls((prev) => [...prev, ...urls]);
    } catch {
      alert('이미지 업로드에 실패했어요. 다시 시도해주세요.');
      // 미리보기에서 실패한 항목 제거
      setImagePreviews((prev) => prev.slice(0, prev.length - selected.length));
    } finally {
      setImageUploading(false);
      // input 초기화 (같은 파일 재선택 가능하도록)
      if (imageInputRef.current) imageInputRef.current.value = '';
    }
  };

  // ── 이미지 삭제 ──
  const handleImageRemove = (idx: number) => {
    setImageUrls((prev) => prev.filter((_, i) => i !== idx));
    setImagePreviews((prev) => prev.filter((_, i) => i !== idx));
  };

  const handleAutoSaveDraft = async () => {
    setDraftSaving(true);
    try {
      await saveDraft({ ...form, image_urls: imageUrls });
    } catch (e) {
      console.error(e);
    } finally {
      setTimeout(() => setDraftSaving(false), 1000);
    }
  };

  // ── 검색 ──
  // 백엔드가 검색 시 자동으로 기록 저장함 → addHistory 불필요
  const handleSearch = (keyword: string) => {
    if (!keyword.trim()) return;
    setSearchQuery(keyword.trim());
    setSearchInput(keyword.trim());
    setShowHistory(false);
    // 검색 후 서버에서 최신 기록 불러오기
    setTimeout(() => loadSearchHistory(), 500);
  };

  // ── 좋아요 (낙관적 업데이트) ──
  const handleLike = async (e: React.MouseEvent, post: TripMatePost) => {
    e.stopPropagation();
    const newLiked = !post.is_liked;
    const newCount = newLiked ? post.like_count + 1 : post.like_count - 1;
    setPosts((prev) =>
      prev.map((p) =>
        p.post_id === post.post_id ? { ...p, is_liked: newLiked, like_count: newCount } : p
      )
    );
    try {
      await toggleLike(post.post_id, post.is_liked);
    } catch {
      setPosts((prev) =>
        prev.map((p) =>
          p.post_id === post.post_id
            ? { ...p, is_liked: post.is_liked, like_count: post.like_count }
            : p
        )
      );
    }
  };

  // ── 글 등록 / 수정 ──
  const handleSubmit = async () => {
    if (!form.title || !form.content || !form.region || !form.travel_start_date || !form.travel_end_date) {
      alert('모든 필드를 입력해주세요.');
      return;
    }
    setSubmitting(true);
    try {
      const payload = {
        ...form,
        preferred_age_min: Number(form.preferred_age_min),
        preferred_age_max: Number(form.preferred_age_max),
        image_urls: imageUrls.length > 0 ? imageUrls : null,
      };

      if (editingPostId) {
        // 수정 모드
        const updated = await updateTripMatePost(editingPostId, payload);
        setPosts((prev) =>
          prev.map((p) => p.post_id === editingPostId ? updated : p)
        );
        setEditingPostId(null);
      } else {
        // 신규 등록
        await createTripMatePost(payload);
        await deleteDraft();
        fetchPosts();
      }

      // 공통 초기화
      setImageUrls([]);
      setImagePreviews([]);
      setForm({
        title: '',
        content: '',
        region: '',
        travel_start_date: '',
        travel_end_date: '',
        companion_type: 'friend',
        preferred_gender: 'any',
        preferred_age_min: 20,
        preferred_age_max: 35,
      });
      setTab('list');
    } catch (err: any) {
      const status = err?.response?.status;
      const msg = err?.response?.data?.detail || err?.response?.data?.message || err?.message || '';
      console.error('❌ 게시글 등록 에러:', err?.response?.data ?? err);
      alert(`${editingPostId ? '수정' : '등록'} 실패 (${status ?? 'Network Error'})\n${msg}`);
    } finally {
      setSubmitting(false);
    }
  };

  // ── 수정 시작 (폼 미리 채우기) ──
  const handleStartEdit = (post: TripMatePost) => {
    setEditingPostId(post.post_id);
    setForm({
      title: post.title,
      content: post.content,
      region: post.region,
      travel_start_date: post.travel_start_date,
      travel_end_date: post.travel_end_date,
      companion_type: post.companion_type,
      preferred_gender: post.preferred_gender,
      preferred_age_min: post.preferred_age_min,
      preferred_age_max: post.preferred_age_max,
    });
    // 이미지 상태 미리 채우기
    const urls = post.image_urls ?? [];
    setImageUrls(urls);
    setImagePreviews(urls);   // 서버 URL을 미리보기로도 사용
    setMenuOpenPostId(null);
    setTab('write');
  };

  // ── 삭제 ──
  const handleDeletePost = async (post: TripMatePost) => {
    setMenuOpenPostId(null);
    if (!window.confirm(`"${post.title}" 게시글을 삭제할까요?`)) return;
    try {
      await deleteTripMatePost(post.post_id);
      setPosts((prev) => prev.filter((p) => p.post_id !== post.post_id));
    } catch {
      alert('삭제에 실패했습니다.');
    }
  };

  // ── 필터 적용 ──
  const filteredPosts = filter === 'all' ? posts : posts.filter((p) => p.companion_type === filter);

  return (
    <div className="max-w-md mx-auto bg-gray-50 min-h-screen pb-20">
      {/* 헤더 */}
      <div className="bg-white px-4 pt-6 pb-0 shadow-sm">
        <h1 className="text-2xl font-bold text-gray-800">👫 여행 메이트</h1>
        <p className="text-sm text-gray-500 mt-1">함께 서울을 여행할 메이트를 찾아보세요</p>

        {/* 검색바 */}
        {tab === 'list' && (
          <div className="relative mt-3">
            <input
              ref={searchRef}
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              onFocus={() => { setShowHistory(true); loadSearchHistory(); }}
              onBlur={() => setTimeout(() => setShowHistory(false), 150)}
              onKeyDown={(e) => e.key === 'Enter' && handleSearch(searchInput)}
              placeholder="지역, 닉네임으로 검색"
              className="w-full pl-4 pr-10 py-2.5 border border-gray-200 rounded-xl text-sm focus:outline-none focus:border-pink-400"
            />
            <button
              onMouseDown={() => handleSearch(searchInput)}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400"
            >
              🔍
            </button>

            {showHistory && searchHistory.length > 0 && (
              <div className="absolute top-full left-0 right-0 bg-white border border-gray-100 rounded-xl shadow-lg z-50 mt-1 overflow-hidden">
                <div className="flex items-center justify-between px-3 py-2 border-b border-gray-50">
                  <span className="text-xs text-gray-400 font-medium">최근 검색</span>
                  <button
                    onMouseDown={async () => {
                      await deleteSearchHistoryAll();
                      setSearchHistory([]);
                    }}
                    className="text-xs text-gray-400"
                  >
                    전체 삭제
                  </button>
                </div>
                {searchHistory.map((term) => (
                  <div key={term} className="flex items-center justify-between px-3 py-2.5 hover:bg-gray-50">
                    <button
                      onMouseDown={() => handleSearch(term)}
                      className="text-sm text-gray-700 flex-1 text-left"
                    >
                      🕐 {term}
                    </button>
                    <button
                      onMouseDown={async () => {
                        await deleteSearchHistoryOne(term);
                        setSearchHistory((prev) => prev.filter((t) => t !== term));
                      }}
                      className="text-gray-300 text-sm ml-2"
                    >
                      ✕
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* 탭 */}
        <div className="flex mt-3">
          {(['list', 'write'] as const).map((t) => (
            <button
              key={t}
              onClick={() => {
                if (t === 'list' && editingPostId) {
                  // 수정 중 목록 탭 클릭 시 수정 취소
                  setEditingPostId(null);
                  setImageUrls([]);
                  setImagePreviews([]);
                  setForm({
                    title: '', content: '', region: '',
                    travel_start_date: '', travel_end_date: '',
                    companion_type: 'friend', preferred_gender: 'any',
                    preferred_age_min: 20, preferred_age_max: 35,
                  });
                }
                setTab(t);
              }}
              className={
                'flex-1 py-2.5 text-sm font-semibold border-b-2 ' +
                (tab === t ? 'border-pink-400 text-pink-500' : 'border-transparent text-gray-400')
              }
            >
              {t === 'list' ? '메이트 찾기' : (editingPostId ? '게시글 수정' : '모집 글 작성')}
            </button>
          ))}
        </div>
      </div>

      {/* ────── 목록 탭 ────── */}
      {tab === 'list' && (
        <div className="px-4 py-4">
          {/* 필터 */}
          <div className="flex gap-2 overflow-x-auto pb-2">
            {COMPANION_FILTERS.map((f) => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                className={
                  'flex-shrink-0 px-4 py-1.5 rounded-full text-sm font-medium ' +
                  (filter === f
                    ? 'bg-pink-400 text-white'
                    : 'bg-white text-gray-500 border border-gray-200')
                }
              >
                {COMPANION_LABELS[f]}
              </button>
            ))}
          </div>

          {/* 카드 목록 */}
          <div className="space-y-3 mt-3">
            {loading && posts.length === 0 ? (
              <div className="text-center py-16 text-gray-300 text-4xl">⏳</div>
            ) : filteredPosts.length === 0 ? (
              <div className="text-center py-16 text-gray-400 text-sm">
                {searchQuery ? `"${searchQuery}" 검색 결과가 없어요` : '아직 게시글이 없어요'}
              </div>
            ) : (
              filteredPosts.map((post) => (
                <div
                  key={post.post_id}
                  className="bg-white rounded-2xl p-4 shadow-sm relative"
                >
                  <div
                    className="cursor-pointer"
                    onClick={() => {
                      if (menuOpenPostId === post.post_id) {
                        setMenuOpenPostId(null);
                      } else {
                        setSelectedPost(post);
                      }
                    }}
                  >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <div className="w-10 h-10 bg-pink-100 rounded-full flex items-center justify-center text-lg font-bold text-pink-400">
                        {post.author.user_name[0]}
                      </div>
                      <div>
                        <p className="font-semibold text-gray-800">{post.author.user_name}</p>
                        <p className="text-xs text-gray-400">
                          {post.author.nationality} · {post.author.age}세 · {post.author.gender === 'male' ? '남' : '여'}
                        </p>
                      </div>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <span className="text-xs bg-pink-50 text-pink-400 px-2.5 py-1 rounded-full font-medium">
                        {COMPANION_LABELS[post.companion_type]}
                      </span>
                      {/* 내 게시글에만 ··· 버튼 표시 */}
                      {currentUserId && post.user_id === currentUserId && (
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            setMenuOpenPostId(menuOpenPostId === post.post_id ? null : post.post_id);
                          }}
                          className="text-gray-300 text-lg px-1 leading-none"
                        >
                          ···
                        </button>
                      )}
                    </div>
                  </div>

                  <div className="mt-3">
                    <p className="font-medium text-gray-800 text-sm">{post.title}</p>
                    <p className="text-xs text-gray-400 mt-1 line-clamp-2">{post.content}</p>
                    {/* 이미지 썸네일 */}
                    {post.image_urls && post.image_urls.length > 0 && (
                      <div className="flex gap-1.5 mt-2">
                        {post.image_urls.slice(0, 3).map((url, idx) => (
                          <div key={idx} className="relative">
                            <img
                              src={url}
                              alt=""
                              className="w-16 h-16 rounded-lg object-cover"
                            />
                            {idx === 2 && post.image_urls!.length > 3 && (
                              <div className="absolute inset-0 bg-black/50 rounded-lg flex items-center justify-center text-white text-xs font-bold">
                                +{post.image_urls!.length - 3}
                              </div>
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>

                  <div className="flex items-center gap-3 mt-2.5 text-xs text-gray-400">
                    <span>📍 {post.region}</span>
                    <span>📅 {post.travel_start_date} ~ {post.travel_end_date}</span>
                  </div>

                  <div className="flex items-center justify-between mt-2.5">
                    <div className="flex gap-1.5">
                      <span className="px-2 py-0.5 bg-blue-50 text-blue-400 text-xs rounded-full">
                        {post.preferred_age_min}~{post.preferred_age_max}세
                      </span>
                      <span className="px-2 py-0.5 bg-purple-50 text-purple-400 text-xs rounded-full">
                        {GENDER_LABELS[post.preferred_gender]}
                      </span>
                    </div>
                    <button onClick={(e) => handleLike(e, post)} className="flex items-center gap-1 text-xs">
                      <span className={post.is_liked ? 'text-red-400' : 'text-gray-300'}>
                        {post.is_liked ? '❤️' : '🤍'}
                      </span>
                      <span className={post.is_liked ? 'text-red-400' : 'text-gray-400'}>
                        {post.like_count}
                      </span>
                    </button>
                  </div>
                  </div>{/* cursor-pointer 닫기 */}

                  {/* ··· 드롭다운 메뉴 */}
                  {menuOpenPostId === post.post_id && (
                    <div className="absolute right-4 top-12 bg-white border border-gray-200 rounded-xl shadow-lg z-20 overflow-hidden">
                      <button
                        onClick={() => handleStartEdit(post)}
                        className="flex items-center gap-2 px-5 py-3 text-sm text-gray-700 hover:bg-gray-50 w-full text-left"
                      >
                        <span>✏️</span>
                        <span>수정하기</span>
                      </button>
                      <button
                        onClick={() => handleDeletePost(post)}
                        className="flex items-center gap-2 px-5 py-3 text-sm text-red-500 hover:bg-red-50 w-full text-left"
                      >
                        <span>🗑️</span>
                        <span>삭제하기</span>
                      </button>
                    </div>
                  )}
                </div>
              ))
            )}
          </div>

          {nextCursor && (
            <button
              onClick={() => fetchPosts(nextCursor)}
              className="w-full mt-4 py-3 text-sm text-gray-400 border border-gray-200 rounded-xl bg-white"
            >
              더 보기
            </button>
          )}
        </div>
      )}

      {/* ────── 글쓰기 탭 ────── */}
      {tab === 'write' && (
        <div className="px-4 py-4">
          {/* 수정 모드 안내 배너 */}
          {editingPostId && (
            <div className="flex items-center justify-between bg-orange-50 border border-orange-200 rounded-xl px-4 py-2.5 mb-3">
              <span className="text-sm text-orange-600 font-medium">✏️ 게시글 수정 중</span>
              <button
                onClick={() => {
                  setEditingPostId(null);
                  setImageUrls([]);
                  setImagePreviews([]);
                  setForm({
                    title: '', content: '', region: '',
                    travel_start_date: '', travel_end_date: '',
                    companion_type: 'friend', preferred_gender: 'any',
                    preferred_age_min: 20, preferred_age_max: 35,
                  });
                  setTab('list');
                }}
                className="text-xs text-orange-400 font-medium"
              >
                취소
              </button>
            </div>
          )}
          {draftSaving && (
            <div className="text-xs text-gray-400 text-right mb-2">💾 임시저장 중...</div>
          )}
          <div className="bg-white rounded-2xl p-4 shadow-sm space-y-4">
            <div>
              <label className="text-sm font-medium text-gray-700">제목 *</label>
              <input
                value={form.title}
                onChange={(e) => setForm({ ...form, title: e.target.value })}
                placeholder="예: 제주도 같이 가실 분!"
                maxLength={100}
                className="w-full mt-1.5 px-3 py-2.5 border border-gray-200 rounded-xl text-sm focus:outline-none focus:border-pink-400"
              />
            </div>

            <div>
              <label className="text-sm font-medium text-gray-700">여행 지역 *</label>
              <input
                value={form.region}
                onChange={(e) => setForm({ ...form, region: e.target.value })}
                placeholder="예: 서울 홍대, 제주도"
                maxLength={100}
                className="w-full mt-1.5 px-3 py-2.5 border border-gray-200 rounded-xl text-sm focus:outline-none focus:border-pink-400"
              />
            </div>

            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="text-sm font-medium text-gray-700">시작일 *</label>
                <input
                  type="date"
                  value={form.travel_start_date}
                  onChange={(e) => setForm({ ...form, travel_start_date: e.target.value })}
                  className="w-full mt-1.5 px-3 py-2.5 border border-gray-200 rounded-xl text-sm focus:outline-none focus:border-pink-400"
                />
              </div>
              <div>
                <label className="text-sm font-medium text-gray-700">종료일 *</label>
                <input
                  type="date"
                  value={form.travel_end_date}
                  onChange={(e) => setForm({ ...form, travel_end_date: e.target.value })}
                  className="w-full mt-1.5 px-3 py-2.5 border border-gray-200 rounded-xl text-sm focus:outline-none focus:border-pink-400"
                />
              </div>
            </div>

            <div>
              <label className="text-sm font-medium text-gray-700">동행 유형</label>
              <div className="flex gap-2 mt-1.5 flex-wrap">
                {(['friend', 'family', 'couple', 'sole'] as CompanionType[]).map((type) => (
                  <button
                    key={type}
                    onClick={() => setForm({ ...form, companion_type: type })}
                    className={
                      'px-3 py-1.5 rounded-full text-sm border ' +
                      (form.companion_type === type
                        ? 'bg-pink-400 text-white border-pink-400'
                        : 'bg-white text-gray-500 border-gray-200')
                    }
                  >
                    {COMPANION_LABELS[type]}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <label className="text-sm font-medium text-gray-700">선호 나이대</label>
              <div className="flex items-center gap-2 mt-1.5">
                <input
                  type="number"
                  value={form.preferred_age_min}
                  onChange={(e) => setForm({ ...form, preferred_age_min: Number(e.target.value) })}
                  onBlur={() =>
                    setForm((f) => ({
                      ...f,
                      preferred_age_min: Math.max(18, Math.min(f.preferred_age_min, f.preferred_age_max)),
                    }))
                  }
                  min={18} max={99}
                  className="w-full px-3 py-2.5 border border-gray-200 rounded-xl text-sm focus:outline-none focus:border-pink-400 text-center"
                />
                <span className="text-gray-400 text-sm flex-shrink-0">~</span>
                <input
                  type="number"
                  value={form.preferred_age_max}
                  onChange={(e) => setForm({ ...form, preferred_age_max: Number(e.target.value) })}
                  onBlur={() =>
                    setForm((f) => ({
                      ...f,
                      preferred_age_max: Math.max(f.preferred_age_min, Math.min(f.preferred_age_max, 99)),
                    }))
                  }
                  min={18} max={99}
                  className="w-full px-3 py-2.5 border border-gray-200 rounded-xl text-sm focus:outline-none focus:border-pink-400 text-center"
                />
                <span className="text-gray-400 text-sm flex-shrink-0">세</span>
              </div>
            </div>

            <div>
              <label className="text-sm font-medium text-gray-700">선호 성별</label>
              <div className="flex gap-2 mt-1.5">
                {(['any', 'male', 'female'] as PreferredGender[]).map((g) => (
                  <button
                    key={g}
                    onClick={() => setForm({ ...form, preferred_gender: g })}
                    className={
                      'flex-1 py-2 rounded-xl text-sm border ' +
                      (form.preferred_gender === g
                        ? 'bg-pink-400 text-white border-pink-400'
                        : 'bg-white text-gray-500 border-gray-200')
                    }
                  >
                    {GENDER_LABELS[g]}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <label className="text-sm font-medium text-gray-700">소개글 *</label>
              <textarea
                value={form.content}
                onChange={(e) => setForm({ ...form, content: e.target.value })}
                placeholder="어떤 여행을 원하시나요? 자유롭게 소개해주세요 (10~500자)"
                rows={4}
                maxLength={500}
                className="w-full mt-1.5 px-3 py-2.5 border border-gray-200 rounded-xl text-sm focus:outline-none focus:border-pink-400 resize-none"
              />
              <p className="text-xs text-gray-300 text-right mt-0.5">{form.content.length}/500</p>
            </div>

            {/* ── 사진 첨부 ── */}
            <div>
              <div className="flex items-center justify-between mb-2">
                <label className="text-sm font-medium text-gray-700">사진 첨부</label>
                <span className="text-xs text-gray-400">{imageUrls.length}/10</span>
              </div>

              <div className="flex gap-2 flex-wrap">
                {/* 미리보기 썸네일 */}
                {imagePreviews.map((src, idx) => (
                  <div key={idx} className="relative w-20 h-20 rounded-xl overflow-hidden flex-shrink-0">
                    <img src={src} alt={`첨부 ${idx + 1}`} className="w-full h-full object-cover" />
                    {/* 업로드 중 오버레이 */}
                    {imageUploading && idx >= imageUrls.length && (
                      <div className="absolute inset-0 bg-black/40 flex items-center justify-center">
                        <div className="w-5 h-5 border-2 border-white border-t-transparent rounded-full animate-spin" />
                      </div>
                    )}
                    {/* 삭제 버튼 */}
                    {!imageUploading && (
                      <button
                        onClick={() => handleImageRemove(idx)}
                        className="absolute top-1 right-1 w-5 h-5 bg-black/60 rounded-full flex items-center justify-center text-white text-xs"
                      >
                        ✕
                      </button>
                    )}
                  </div>
                ))}

                {/* + 추가 버튼 */}
                {imageUrls.length < 10 && !imageUploading && (
                  <button
                    onClick={() => imageInputRef.current?.click()}
                    className="w-20 h-20 border-2 border-dashed border-gray-200 rounded-xl flex flex-col items-center justify-center gap-1 text-gray-300 flex-shrink-0 active:bg-gray-50"
                  >
                    <span className="text-2xl font-light">+</span>
                    <span className="text-xs">사진 추가</span>
                  </button>
                )}
              </div>

              <input
                ref={imageInputRef}
                type="file"
                accept="image/jpeg,image/png,image/webp,image/gif"
                multiple
                onChange={handleImageSelect}
                className="hidden"
              />
            </div>

            <div className="flex gap-2">
              {!editingPostId && (
                <button
                  onClick={handleAutoSaveDraft}
                  className="flex-1 py-3 rounded-xl text-sm border border-gray-200 text-gray-500"
                >
                  임시저장
                </button>
              )}
              <button
                onClick={handleSubmit}
                disabled={submitting}
                className={
                  'py-3 rounded-xl text-sm bg-pink-400 text-white font-semibold disabled:opacity-50 ' +
                  (editingPostId ? 'w-full' : 'flex-1')
                }
              >
                {submitting
                  ? (editingPostId ? '수정 중...' : '등록 중...')
                  : (editingPostId ? '수정 완료' : '등록하기')}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ────── 프로필 모달 ────── */}
      {selectedPost && (
        <div
          className="fixed inset-0 bg-black/40 z-50 flex items-end justify-center"
          onClick={() => setSelectedPost(null)}
        >
          <div
            className="bg-white w-full max-w-md rounded-t-3xl p-6 pb-8"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="w-10 h-1 bg-gray-200 rounded-full mx-auto mb-4" />

            <div className="flex items-center gap-4">
              <div className="w-16 h-16 bg-pink-100 rounded-full flex items-center justify-center text-2xl font-bold text-pink-400">
                {selectedPost.author.user_name[0]}
              </div>
              <div>
                <p className="text-lg font-bold text-gray-800">{selectedPost.author.user_name}</p>
                <p className="text-sm text-gray-400">
                  {selectedPost.author.nationality} · {selectedPost.author.age}세 ·{' '}
                  {selectedPost.author.gender === 'male' ? '남성' : '여성'}
                </p>
              </div>
            </div>

            <div className="mt-4 bg-gray-50 rounded-2xl p-4 space-y-2">
              <p className="font-semibold text-gray-800">{selectedPost.title}</p>
              <p className="text-sm text-gray-500">{selectedPost.content}</p>
              <div className="flex gap-3 text-xs text-gray-400 mt-1">
                <span>📍 {selectedPost.region}</span>
                <span>📅 {selectedPost.travel_start_date} ~ {selectedPost.travel_end_date}</span>
              </div>
            </div>

            <div className="flex gap-2 mt-3 flex-wrap">
              <span className="px-3 py-1 bg-blue-50 text-blue-400 text-xs rounded-full">
                {COMPANION_LABELS[selectedPost.companion_type]}
              </span>
              <span className="px-3 py-1 bg-purple-50 text-purple-400 text-xs rounded-full">
                {selectedPost.preferred_age_min}~{selectedPost.preferred_age_max}세
              </span>
              <span className="px-3 py-1 bg-green-50 text-green-500 text-xs rounded-full">
                {GENDER_LABELS[selectedPost.preferred_gender]}
              </span>
            </div>

            <div className="flex gap-2 mt-5">
              <button
                onClick={() => {
                  setFriendRequested((prev) => {
                    const next = new Set(prev);
                    if (next.has(selectedPost.post_id)) next.delete(selectedPost.post_id);
                    else next.add(selectedPost.post_id);
                    return next;
                  });
                }}
                className={
                  'flex-1 py-3 rounded-xl text-sm font-semibold border ' +
                  (friendRequested.has(selectedPost.post_id)
                    ? 'bg-gray-100 text-gray-400 border-gray-200'
                    : 'bg-pink-400 text-white border-pink-400')
                }
              >
                {friendRequested.has(selectedPost.post_id) ? '요청 완료 ✓' : '친구 추가'}
              </button>
              <button
                onClick={() => {
                  setSelectedPost(null);
                  navigate(`/profile/${selectedPost.user_id}`);
                }}
                className="flex-1 py-3 rounded-xl text-sm font-semibold border border-gray-200 text-gray-600"
              >
                피드 보기
              </button>
              <button
                onClick={() => {
                  setChatTarget(selectedPost);
                  setSelectedPost(null);
                }}
                className="flex-1 py-3 rounded-xl text-sm font-semibold bg-blue-400 text-white"
              >
                채팅
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 드롭다운 메뉴 배경 클릭 시 닫기 */}
      {menuOpenPostId !== null && (
        <div
          className="fixed inset-0 z-10"
          onClick={() => setMenuOpenPostId(null)}
        />
      )}

      {/* ────── 채팅 팝업 ────── */}
      {chatTarget && (
        <div
          className="fixed inset-0 bg-black/40 z-50 flex items-end justify-center"
          onClick={() => setChatTarget(null)}
        >
          <div
            className="bg-white w-full max-w-md rounded-t-3xl p-6 pb-8"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="w-10 h-1 bg-gray-200 rounded-full mx-auto mb-4" />
            <p className="font-semibold text-gray-800 mb-3">
              {chatTarget.author.user_name}에게 메시지 보내기
            </p>
            <textarea
              value={chatMsg}
              onChange={(e) => setChatMsg(e.target.value)}
              placeholder="첫 메시지를 입력하세요"
              rows={3}
              className="w-full px-3 py-2.5 border border-gray-200 rounded-xl text-sm focus:outline-none focus:border-pink-400 resize-none"
            />
            <button
              onClick={() => {
                if (chatMsg.trim()) {
                  navigate('/chat');
                  setChatTarget(null);
                  setChatMsg('');
                }
              }}
              className="w-full mt-3 py-3 bg-pink-400 text-white rounded-xl text-sm font-semibold"
            >
              채팅 시작하기
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export default MatePage;
