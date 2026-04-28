import { useEffect, useMemo, useRef, useState } from "react";
import type { ChangeEvent, CSSProperties, MouseEvent } from "react";
import { useNavigate } from "react-router-dom";
import {
  createTripMatePost,
  deleteDraft,
  deleteTripMatePost,
  getDraft,
  getTripMatePosts,
  saveDraft,
  searchTripMatePosts,
  toggleLike,
  updateTripMatePost,
  type CompanionType,
  type PreferredGender,
  type TripMatePost,
} from "../../api/mate";
import {
  deleteSearchHistoryAll,
  deleteSearchHistoryOne,
  getSearchHistory,
} from "../../api/searchHistory";
import { uploadImages } from "../../api/image";
import { getMyProfile } from "../../api/auth";
import { createDirectChatRoom } from "../../api/chat";
import { getFriendDetail, sendFriendRequest, type FriendshipStatus } from "../../api/friend";

const COMPANION_FILTERS = ["all", "sole", "friend", "couple", "family"] as const;
const COMPANION_OPTIONS: CompanionType[] = ["friend", "family", "couple", "sole"];
const GENDER_OPTIONS: PreferredGender[] = ["any", "male", "female"];

const COMPANION_LABELS: Record<CompanionType | "all", string> = {
  all: "All",
  sole: "Solo",
  friend: "Friends",
  couple: "Couple",
  family: "Family",
};

const GENDER_LABELS: Record<PreferredGender, string> = {
  any: "Any gender",
  male: "Male",
  female: "Female",
};

const EMPTY_FORM = {
  title: "",
  content: "",
  region: "",
  travel_start_date: "",
  travel_end_date: "",
  companion_type: "friend" as CompanionType,
  preferred_gender: "any" as PreferredGender,
  preferred_age_min: 20,
  preferred_age_max: 35,
};

type Tab = "list" | "write";
type MateFriendState = {
  friendship_status: FriendshipStatus | null;
  is_requester: boolean | null;
  i_blocked_peer: boolean;
};

export default function MatePage() {
  const navigate = useNavigate();
  const searchRef = useRef<HTMLInputElement>(null);
  const imageInputRef = useRef<HTMLInputElement>(null);
  const draftTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  const draftFormRef = useRef(EMPTY_FORM);
  const draftImageUrlsRef = useRef<string[]>([]);

  const [tab, setTab] = useState<Tab>("list");
  const [posts, setPosts] = useState<TripMatePost[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const [filter, setFilter] = useState<CompanionType | "all">("all");

  const [searchInput, setSearchInput] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [searchHistory, setSearchHistory] = useState<string[]>([]);
  const [showHistory, setShowHistory] = useState(false);

  const [selectedPost, setSelectedPost] = useState<TripMatePost | null>(null);
  const [friendRequested, setFriendRequested] = useState<Set<string>>(new Set());
  const [friendStates, setFriendStates] = useState<Record<string, MateFriendState>>({});
  const [friendRequestingUserId, setFriendRequestingUserId] = useState<string | null>(null);
  const [expandedImage, setExpandedImage] = useState<string | null>(null);
  const [chatOpeningPostId, setChatOpeningPostId] = useState<string | null>(null);

  const [currentUserId, setCurrentUserId] = useState<string | null>(null);
  const [menuOpenPostId, setMenuOpenPostId] = useState<string | null>(null);
  const [editingPostId, setEditingPostId] = useState<string | null>(null);

  const [form, setForm] = useState(EMPTY_FORM);
  const [submitting, setSubmitting] = useState(false);
  const [draftSaving, setDraftSaving] = useState(false);
  const [draftStatus, setDraftStatus] = useState("");
  const [imageUrls, setImageUrls] = useState<string[]>([]);
  const [imagePreviews, setImagePreviews] = useState<string[]>([]);
  const [imageUploading, setImageUploading] = useState(false);

  useEffect(() => {
    draftFormRef.current = form;
    draftImageUrlsRef.current = imageUrls;
  }, [form, imageUrls]);

  async function loadSearchHistory(): Promise<void> {
    try {
      const response = await getSearchHistory();
      setSearchHistory(response.histories.map((item) => item.search_name));
    } catch {
      setSearchHistory([]);
    }
  }

  async function fetchPosts(cursor?: string): Promise<void> {
    setLoading(true);
    setErrorMessage("");

    try {
      const response = searchQuery
        ? await searchTripMatePosts(searchQuery, cursor)
        : await getTripMatePosts(cursor);

      const newPosts = Array.isArray(response) ? response : response.posts ?? [];
      const newCursor = Array.isArray(response) ? null : response.next_cursor ?? null;

      setPosts((current) => (cursor ? [...current, ...newPosts] : newPosts));
      setNextCursor(newCursor);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Failed to load mate posts.");
      if (!cursor) {
        setPosts([]);
      }
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void fetchPosts();
  }, [searchQuery]);

  useEffect(() => {
    if (!selectedPost || selectedPost.user_id === currentUserId || friendStates[selectedPost.user_id]) {
      return;
    }

    getFriendDetail(selectedPost.user_id)
      .then((detail) => {
        setFriendStates((current) => ({
          ...current,
          [selectedPost.user_id]: {
            friendship_status: detail.friendship_status,
            is_requester: detail.is_requester,
            i_blocked_peer: detail.i_blocked_peer,
          },
        }));
      })
      .catch(() => {
        // Relationship metadata is optional for rendering the post itself.
      });
  }, [currentUserId, friendStates, selectedPost]);

  useEffect(() => {
    void loadSearchHistory();
    getMyProfile()
      .then((profile) => setCurrentUserId(profile?.user_id ?? null))
      .catch((error) => {
        console.warn("Failed to load /api/auth/profile/me", error);
        setCurrentUserId(null);
      });
  }, []);

  useEffect(() => {
    if (tab !== "write") {
      return undefined;
    }

    if (!editingPostId) {
      getDraft()
        .then((draft) => {
          if (!draft) return;

          setForm({
            title: draft.title ?? "",
            content: draft.content ?? "",
            region: draft.region ?? "",
            travel_start_date: draft.travel_start_date ?? "",
            travel_end_date: draft.travel_end_date ?? "",
            companion_type: draft.companion_type ?? "friend",
            preferred_gender: draft.preferred_gender ?? "any",
            preferred_age_min: draft.preferred_age_min ?? 20,
            preferred_age_max: draft.preferred_age_max ?? 35,
          });
          setImageUrls(draft.image_urls ?? []);
          setImagePreviews(draft.image_urls ?? []);
        })
        .catch(() => {
          // Drafts are optional.
        });
    }

    draftTimer.current = setInterval(() => {
      void handleAutoSaveDraft(false);
    }, 30000);

    return () => {
      if (draftTimer.current) {
        clearInterval(draftTimer.current);
      }
    };
  }, [tab, editingPostId]);

  const filteredPosts = useMemo(
    () =>
      filter === "all"
        ? posts
        : posts.filter((post) => post.companion_type === filter),
    [filter, posts]
  );

  function resetEditor(): void {
    setEditingPostId(null);
    setForm(EMPTY_FORM);
    setImageUrls([]);
    setImagePreviews([]);
  }

  function handleTabChange(nextTab: Tab): void {
    if (nextTab === "list" && editingPostId) {
      resetEditor();
    }

    setTab(nextTab);
  }

  function handleSearch(keyword: string): void {
    const nextKeyword = keyword.trim();
    if (!nextKeyword) return;

    setSearchQuery(nextKeyword);
    setSearchInput(nextKeyword);
    setShowHistory(false);
    window.setTimeout(() => void loadSearchHistory(), 500);
  }

  async function handleDeleteSearchHistory(term: string): Promise<void> {
    await deleteSearchHistoryOne(term);
    setSearchHistory((current) => current.filter((item) => item !== term));
  }

  async function handleClearSearchHistory(): Promise<void> {
    await deleteSearchHistoryAll();
    setSearchHistory([]);
  }

  async function handleImageSelect(event: ChangeEvent<HTMLInputElement>): Promise<void> {
    const files = Array.from(event.target.files ?? []);
    if (files.length === 0) return;

    const selectedFiles = files.slice(0, Math.max(0, 10 - imageUrls.length));
    if (selectedFiles.length === 0) return;

    const previews = selectedFiles.map((file) => URL.createObjectURL(file));
    setImagePreviews((current) => [...current, ...previews]);
    setImageUploading(true);

    try {
      const response = await uploadImages(selectedFiles);
      setImageUrls((current) => [
        ...current,
        ...response.images.map((image) => image.image_url),
      ]);
    } catch (uploadError) {
      window.alert(toErrorMessage(uploadError, "Image upload failed. Please try again."));
      setImagePreviews((current) => current.slice(0, current.length - selectedFiles.length));
    } finally {
      setImageUploading(false);
      if (imageInputRef.current) {
        imageInputRef.current.value = "";
      }
    }
  }

  function handleImageRemove(index: number): void {
    setImageUrls((current) => current.filter((_, itemIndex) => itemIndex !== index));
    setImagePreviews((current) => current.filter((_, itemIndex) => itemIndex !== index));
  }

  async function handleAutoSaveDraft(showError = true): Promise<void> {
    if (editingPostId) return;

    setDraftSaving(true);
    setDraftStatus("Saving draft...");
    try {
      await saveDraft({
        ...draftFormRef.current,
        image_urls: draftImageUrlsRef.current,
      });
      setDraftStatus("Draft saved");
    } catch (draftError) {
      setDraftStatus("");
      if (showError) {
        window.alert(toErrorMessage(draftError, "Failed to save draft. Please try again."));
      }
    } finally {
      window.setTimeout(() => {
        setDraftSaving(false);
        setDraftStatus("");
      }, 900);
    }
  }

  async function handleLike(event: MouseEvent<HTMLButtonElement>, post: TripMatePost): Promise<void> {
    event.stopPropagation();

    const nextLiked = !post.is_liked;
    const nextCount = Math.max(0, post.like_count + (nextLiked ? 1 : -1));
    setPosts((current) =>
      current.map((item) =>
        item.post_id === post.post_id
          ? { ...item, is_liked: nextLiked, like_count: nextCount }
          : item
      )
    );

    try {
      await toggleLike(post.post_id, post.is_liked);
    } catch {
      setPosts((current) =>
        current.map((item) => (item.post_id === post.post_id ? post : item))
      );
    }
  }

  async function handleSendFriendRequest(post: TripMatePost): Promise<void> {
    if (friendRequestingUserId) return;

    setFriendRequestingUserId(post.user_id);
    try {
      const friendship = await sendFriendRequest(post.user_id);
      setFriendRequested((current) => new Set(current).add(post.post_id));
      setFriendStates((current) => ({
        ...current,
        [post.user_id]: {
          friendship_status: friendship.status,
          is_requester: friendship.is_requester,
          i_blocked_peer: false,
        },
      }));
    } catch (friendError) {
      window.alert(toErrorMessage(friendError, "Failed to send friend request. Please try again."));
    } finally {
      setFriendRequestingUserId(null);
    }
  }

  async function handleSubmit(): Promise<void> {
    if (imageUploading) {
      window.alert("Please wait until the image upload is complete.");
      return;
    }

    if (
      !form.title.trim() ||
      !form.content.trim() ||
      !form.region.trim() ||
      !form.travel_start_date ||
      !form.travel_end_date
    ) {
      window.alert("Please fill in all required fields.");
      return;
    }

    if (form.content.trim().length < 10) {
      window.alert("Please enter at least 10 characters in the intro.");
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
        const updatedPost = await updateTripMatePost(editingPostId, payload);
        setPosts((current) =>
          current.map((post) => (post.post_id === editingPostId ? updatedPost : post))
        );
      } else {
        await createTripMatePost(payload);
        await deleteDraft();
        await fetchPosts();
      }

      resetEditor();
      setTab("list");
    } catch (error: unknown) {
      const apiError = error as { response?: { status?: number }; message?: string };
      const status = apiError.response?.status ?? "Network Error";
      const message = toErrorMessage(error, "Please try again.");

      window.alert(`${editingPostId ? "Update" : "Create"} failed (${status})\n${message}`);
    } finally {
      setSubmitting(false);
    }
  }

  function handleStartEdit(post: TripMatePost): void {
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
    setImageUrls(post.image_urls ?? []);
    setImagePreviews(post.image_urls ?? []);
    setMenuOpenPostId(null);
    setTab("write");
  }

  async function handleDeletePost(post: TripMatePost): Promise<void> {
    setMenuOpenPostId(null);
    if (!window.confirm(`Delete "${post.title}"?`)) return;

    try {
      await deleteTripMatePost(post.post_id);
      setPosts((current) => current.filter((item) => item.post_id !== post.post_id));
    } catch {
      window.alert("Failed to delete the post.");
    }
  }

  async function handleStartChat(post: TripMatePost): Promise<void> {
    if (chatOpeningPostId) return;

    setChatOpeningPostId(post.post_id);
    try {
      const room = await createDirectChatRoom(post.user_id);
      navigate(`/chat/${room.chat_room_id}`);
    } catch (chatError) {
      window.alert(toErrorMessage(chatError, "Failed to open chat. Please try again."));
    } finally {
      setChatOpeningPostId(null);
    }
  }

  return (
    <div style={styles.page}>
      <div style={styles.shell}>
        <header style={styles.header}>
          <div>
            <p style={styles.eyebrow}>Trip Mate</p>
            <h1 style={styles.headerTitle}>Find Travel Companions</h1>
            <p style={styles.headerCopy}>
              Meet people planning similar routes, dates, and travel styles around Seoul.
            </p>
          </div>
          <button
            type="button"
            style={styles.headerButton}
            onClick={() => handleTabChange(tab === "list" ? "write" : "list")}
          >
            {tab === "list" ? "Write Post" : "View Posts"}
          </button>
        </header>

        <section style={styles.tabPanel}>
          {(["list", "write"] as const).map((item) => (
            <button
              key={item}
              type="button"
              style={{
                ...styles.tabButton,
                ...(tab === item ? styles.tabButtonActive : {}),
              }}
              onClick={() => handleTabChange(item)}
            >
              {item === "list" ? "Browse" : editingPostId ? "Edit Post" : "New Post"}
            </button>
          ))}
        </section>

        {tab === "list" ? (
          <>
            <section style={styles.searchPanel}>
              <div style={styles.searchRow}>
                <label style={styles.searchWrap}>
                  <SearchIcon />
                  <input
                    ref={searchRef}
                    value={searchInput}
                    onChange={(event) => setSearchInput(event.target.value)}
                    onFocus={() => {
                      setShowHistory(true);
                      void loadSearchHistory();
                    }}
                    onBlur={() => window.setTimeout(() => setShowHistory(false), 150)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") {
                        handleSearch(searchInput);
                      }
                    }}
                    placeholder="Search by region or keyword"
                    style={styles.searchInput}
                  />
                </label>
                <button
                  type="button"
                  style={styles.searchAction}
                  onMouseDown={() => handleSearch(searchInput)}
                >
                  Search
                </button>
              </div>

              {showHistory && searchHistory.length > 0 ? (
                <div style={styles.historyPanel}>
                  <div style={styles.historyHeader}>
                    <span style={styles.historyTitle}>Recent Searches</span>
                    <button
                      type="button"
                      style={styles.linkButton}
                      onMouseDown={() => void handleClearSearchHistory()}
                    >
                      Clear
                    </button>
                  </div>
                  <div style={styles.historyList}>
                    {searchHistory.map((term) => (
                      <div key={term} style={styles.historyItem}>
                        <button
                          type="button"
                          style={styles.historyTerm}
                          onMouseDown={() => handleSearch(term)}
                        >
                          {term}
                        </button>
                        <button
                          type="button"
                          style={styles.iconButton}
                          onMouseDown={() => void handleDeleteSearchHistory(term)}
                          aria-label={`Delete ${term}`}
                        >
                          x
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}
            </section>

            <section style={styles.filtersSection}>
              <div style={styles.filterGroup}>
                {COMPANION_FILTERS.map((item) => (
                  <button
                    key={item}
                    type="button"
                    style={{
                      ...styles.filterChip,
                      ...(filter === item ? styles.filterChipActive : {}),
                    }}
                    onClick={() => setFilter(item)}
                  >
                    {COMPANION_LABELS[item]}
                  </button>
                ))}
              </div>
            </section>

            <section style={styles.listSection}>
              {errorMessage ? (
                <div style={styles.emptyState}>
                  <p style={styles.emptyTitle}>{errorMessage}</p>
                  <p style={styles.emptyCopy}>Try refreshing the list in a moment.</p>
                </div>
              ) : loading && posts.length === 0 ? (
                <div style={styles.loadingState}>
                  <span style={styles.spinner} />
                  <p style={styles.emptyCopy}>Loading mate posts...</p>
                </div>
              ) : filteredPosts.length === 0 ? (
                <div style={styles.emptyState}>
                  <p style={styles.emptyTitle}>
                    {searchQuery ? `No results for "${searchQuery}".` : "No mate posts yet."}
                  </p>
                  <p style={styles.emptyCopy}>
                    Create the first post and help others find a travel companion.
                  </p>
                </div>
              ) : (
                filteredPosts.map((post) => (
                  <article
                    key={post.post_id}
                    className="interactive-card"
                    style={styles.card}
                    onClick={() => {
                      if (menuOpenPostId === post.post_id) {
                        setMenuOpenPostId(null);
                        return;
                      }
                      setSelectedPost(post);
                    }}
                  >
                    <div style={styles.cardHeader}>
                      <div style={styles.authorBlock}>
                        <AuthorAvatar post={post} />
                        <div>
                          <p style={styles.authorName}>{post.author.user_name}</p>
                          <p style={styles.authorMeta}>
                            {[post.author.nationality, post.author.age, GENDER_LABELS[post.author.gender]]
                              .filter(Boolean)
                              .join(" / ")}
                          </p>
                        </div>
                      </div>

                      <div style={styles.cardActions}>
                        <span style={styles.typeBadge}>{COMPANION_LABELS[post.companion_type]}</span>
                        {currentUserId && post.user_id === currentUserId ? (
                          <button
                            type="button"
                            style={styles.moreButton}
                            onClick={(event) => {
                              event.stopPropagation();
                              setMenuOpenPostId(
                                menuOpenPostId === post.post_id ? null : post.post_id
                              );
                            }}
                            aria-label={`Open options for ${post.title}`}
                          >
                            ...
                          </button>
                        ) : null}
                      </div>
                    </div>

                    {menuOpenPostId === post.post_id ? (
                      <div style={styles.postMenu}>
                        <button
                          type="button"
                          style={styles.menuButton}
                          onClick={(event) => {
                            event.stopPropagation();
                            handleStartEdit(post);
                          }}
                        >
                          Edit
                        </button>
                        <button
                          type="button"
                          style={{ ...styles.menuButton, ...styles.dangerText }}
                          onClick={(event) => {
                            event.stopPropagation();
                            void handleDeletePost(post);
                          }}
                        >
                          Delete
                        </button>
                      </div>
                    ) : null}

                    <div style={styles.cardBody}>
                      <h2 style={styles.cardTitle}>{post.title}</h2>
                      <p style={styles.cardDescription}>{post.content}</p>
                    </div>

                    {post.image_urls?.length ? (
                      <div style={styles.imageStrip}>
                        {post.image_urls.slice(0, 3).map((url, index) => (
                          <button
                            key={`${url}-${index}`}
                            type="button"
                            style={styles.postImageWrap}
                            onClick={(event) => {
                              event.stopPropagation();
                              setExpandedImage(url);
                            }}
                          >
                            <img src={url} alt="" style={styles.postImage} />
                            {index === 2 && post.image_urls.length > 3 ? (
                              <div style={styles.imageCount}>+{post.image_urls.length - 3}</div>
                            ) : null}
                          </button>
                        ))}
                      </div>
                    ) : null}

                    <div style={styles.metaGrid}>
                      <span style={styles.metaChip}>{post.region}</span>
                      <span style={styles.metaChip}>
                        {post.travel_start_date} - {post.travel_end_date}
                      </span>
                      <span style={styles.metaChip}>
                        Ages {post.preferred_age_min}-{post.preferred_age_max}
                      </span>
                      <span style={styles.metaChip}>{GENDER_LABELS[post.preferred_gender]}</span>
                    </div>

                    <div style={styles.cardFooter}>
                      <button
                        type="button"
                        style={{
                          ...styles.likeButton,
                          ...(post.is_liked ? styles.likeButtonActive : {}),
                        }}
                        onClick={(event) => void handleLike(event, post)}
                      >
                        {post.is_liked ? "Liked" : "Like"} {post.like_count}
                      </button>
                      <span style={styles.createdText}>
                        {new Date(post.created_at).toLocaleDateString()}
                      </span>
                    </div>
                  </article>
                ))
              )}

              {nextCursor ? (
                <button
                  type="button"
                  style={styles.loadMoreButton}
                  onClick={() => void fetchPosts(nextCursor)}
                  disabled={loading}
                >
                  {loading ? "Loading..." : "Load More"}
                </button>
              ) : null}
            </section>
          </>
        ) : (
          <section style={styles.formPanel}>
            {editingPostId ? (
              <div style={styles.editBanner}>
                <span>Editing this mate post</span>
                <button
                  type="button"
                  style={styles.linkButton}
                  onClick={() => {
                    resetEditor();
                    setTab("list");
                  }}
                >
                  Cancel
                </button>
              </div>
            ) : null}

            {draftStatus ? <p style={styles.saveHint}>{draftStatus}</p> : null}

            <div style={styles.formGrid}>
              <Field label="Title" required>
                <input
                  value={form.title}
                  onChange={(event) => setForm({ ...form, title: event.target.value })}
                  maxLength={100}
                  placeholder="Who wants to explore Seoul together?"
                  style={styles.input}
                />
              </Field>

              <Field label="Region" required>
                <input
                  value={form.region}
                  onChange={(event) => setForm({ ...form, region: event.target.value })}
                  maxLength={100}
                  placeholder="Hongdae, Jongno, Gangnam..."
                  style={styles.input}
                />
              </Field>

              <div style={styles.twoColumn}>
                <Field label="Start Date" required>
                  <input
                    type="date"
                    value={form.travel_start_date}
                    onChange={(event) =>
                      setForm({ ...form, travel_start_date: event.target.value })
                    }
                    style={styles.input}
                  />
                </Field>
                <Field label="End Date" required>
                  <input
                    type="date"
                    value={form.travel_end_date}
                    onChange={(event) =>
                      setForm({ ...form, travel_end_date: event.target.value })
                    }
                    style={styles.input}
                  />
                </Field>
              </div>

              <Field label="Companion Type">
                <div style={styles.optionGrid}>
                  {COMPANION_OPTIONS.map((item) => (
                    <button
                      key={item}
                      type="button"
                      style={{
                        ...styles.optionButton,
                        ...(form.companion_type === item ? styles.optionButtonActive : {}),
                      }}
                      onClick={() => setForm({ ...form, companion_type: item })}
                    >
                      {COMPANION_LABELS[item]}
                    </button>
                  ))}
                </div>
              </Field>

              <div style={styles.twoColumn}>
                <Field label="Min Age">
                  <input
                    type="number"
                    min={18}
                    max={99}
                    value={form.preferred_age_min}
                    onChange={(event) =>
                      setForm({
                        ...form,
                        preferred_age_min: Number(event.target.value),
                      })
                    }
                    onBlur={() =>
                      setForm((current) => ({
                        ...current,
                        preferred_age_min: Math.max(
                          18,
                          Math.min(current.preferred_age_min, current.preferred_age_max)
                        ),
                      }))
                    }
                    style={styles.input}
                  />
                </Field>
                <Field label="Max Age">
                  <input
                    type="number"
                    min={18}
                    max={99}
                    value={form.preferred_age_max}
                    onChange={(event) =>
                      setForm({
                        ...form,
                        preferred_age_max: Number(event.target.value),
                      })
                    }
                    onBlur={() =>
                      setForm((current) => ({
                        ...current,
                        preferred_age_max: Math.max(
                          current.preferred_age_min,
                          Math.min(current.preferred_age_max, 99)
                        ),
                      }))
                    }
                    style={styles.input}
                  />
                </Field>
              </div>

              <Field label="Preferred Gender">
                <div style={styles.optionGrid}>
                  {GENDER_OPTIONS.map((item) => (
                    <button
                      key={item}
                      type="button"
                      style={{
                        ...styles.optionButton,
                        ...(form.preferred_gender === item ? styles.optionButtonActive : {}),
                      }}
                      onClick={() => setForm({ ...form, preferred_gender: item })}
                    >
                      {GENDER_LABELS[item]}
                    </button>
                  ))}
                </div>
              </Field>

              <Field label="Intro" required>
                <textarea
                  value={form.content}
                  onChange={(event) => setForm({ ...form, content: event.target.value })}
                  rows={5}
                  maxLength={500}
                  placeholder="Share your itinerary, pace, and what kind of travel mate you are looking for."
                  style={{ ...styles.input, ...styles.textarea }}
                />
                <p style={styles.counterText}>{form.content.length}/500</p>
              </Field>

              <Field label={`Photos (${imageUrls.length}/10)`}>
                <div style={styles.photoGrid}>
                  {imagePreviews.map((src, index) => (
                    <div key={`${src}-${index}`} style={styles.photoPreview}>
                      <img src={src} alt="" style={styles.photoImage} />
                      {imageUploading && index >= imageUrls.length ? (
                        <div style={styles.uploadOverlay}>
                          <span style={styles.smallSpinner} />
                        </div>
                      ) : null}
                      {!imageUploading ? (
                        <button
                          type="button"
                          style={styles.removePhotoButton}
                          onClick={() => handleImageRemove(index)}
                          aria-label="Remove photo"
                        >
                          x
                        </button>
                      ) : null}
                    </div>
                  ))}

                  {imageUrls.length < 10 && !imageUploading ? (
                    <button
                      type="button"
                      style={styles.addPhotoButton}
                      onClick={() => imageInputRef.current?.click()}
                    >
                      Add Photo
                    </button>
                  ) : null}
                </div>
                <input
                  ref={imageInputRef}
                  type="file"
                  accept="image/jpeg,image/png,image/webp,image/gif"
                  multiple
                  onChange={(event) => void handleImageSelect(event)}
                  style={styles.hiddenInput}
                />
              </Field>

              <div style={styles.formActions}>
                {!editingPostId ? (
                  <button
                    type="button"
                    style={styles.secondaryButton}
                    onClick={() => void handleAutoSaveDraft()}
                    disabled={draftSaving || imageUploading}
                  >
                    {draftSaving ? "Saving..." : "Save Draft"}
                  </button>
                ) : null}
                <button
                  type="button"
                  style={styles.primaryButton}
                  onClick={() => void handleSubmit()}
                  disabled={submitting || imageUploading}
                >
                  {imageUploading
                    ? "Uploading..."
                    : submitting
                    ? editingPostId
                      ? "Updating..."
                      : "Posting..."
                    : editingPostId
                      ? "Update Post"
                      : "Publish Post"}
                </button>
              </div>
            </div>
          </section>
        )}
      </div>

      {selectedPost ? (
        <PostModal
          post={selectedPost}
          friendRequested={friendRequested.has(selectedPost.post_id)}
          friendState={friendStates[selectedPost.user_id]}
          isOwnPost={selectedPost.user_id === currentUserId}
          isSendingFriendRequest={friendRequestingUserId === selectedPost.user_id}
          onClose={() => setSelectedPost(null)}
          onImageClick={(url) => setExpandedImage(url)}
          onToggleFriend={() => void handleSendFriendRequest(selectedPost)}
          onEdit={() => {
            handleStartEdit(selectedPost);
            setSelectedPost(null);
          }}
          onViewProfile={() => {
            navigate(`/profile/${selectedPost.user_id}`);
            setSelectedPost(null);
          }}
          onChat={() => {
            void handleStartChat(selectedPost);
            setSelectedPost(null);
          }}
        />
      ) : null}

      {expandedImage ? (
        <ImageLightbox src={expandedImage} onClose={() => setExpandedImage(null)} />
      ) : null}

      {menuOpenPostId !== null ? (
        <div style={styles.menuBackdrop} onClick={() => setMenuOpenPostId(null)} />
      ) : null}

    </div>
  );
}

function Field({
  label,
  required,
  children,
}: {
  label: string;
  required?: boolean;
  children: React.ReactNode;
}) {
  return (
    <label style={styles.field}>
      <span style={styles.fieldLabel}>
        {label}
        {required ? <span style={styles.required}> *</span> : null}
      </span>
      {children}
    </label>
  );
}

function AuthorAvatar({
  post,
  size = "default",
}: {
  post: TripMatePost;
  size?: "default" | "large";
}) {
  const avatarStyle =
    size === "large" ? { ...styles.avatar, ...styles.largeAvatar } : styles.avatar;

  return (
    <div style={avatarStyle}>
      {post.profile_image_url ? (
        <img src={post.profile_image_url} alt="" style={styles.avatarImage} />
      ) : (
        post.author.user_name?.slice(0, 1).toUpperCase() || "T"
      )}
    </div>
  );
}

function PostModal({
  post,
  friendRequested,
  friendState,
  isOwnPost,
  isSendingFriendRequest,
  onClose,
  onImageClick,
  onToggleFriend,
  onEdit,
  onViewProfile,
  onChat,
}: {
  post: TripMatePost;
  friendRequested: boolean;
  friendState?: MateFriendState;
  isOwnPost: boolean;
  isSendingFriendRequest: boolean;
  onClose: () => void;
  onImageClick: (url: string) => void;
  onToggleFriend: () => void;
  onEdit: () => void;
  onViewProfile: () => void;
  onChat: () => void;
}) {
  const isFriend = friendState?.friendship_status === "accepted";
  const hasPendingRequest = friendRequested || friendState?.friendship_status === "pending";
  const canAddFriend = !isOwnPost && !isFriend && !friendState?.i_blocked_peer;

  return (
    <div style={styles.modalOverlay} onClick={onClose}>
      <div style={styles.modalCard} onClick={(event) => event.stopPropagation()}>
        <div style={styles.modalHero}>
          <div style={styles.modalHeroTop}>
            <span style={styles.modalCategory}>{COMPANION_LABELS[post.companion_type]}</span>
            <button type="button" style={styles.modalCloseButton} onClick={onClose}>
              x
            </button>
          </div>
          <div>
            <h2 style={styles.modalTitle}>{post.title}</h2>
            <p style={styles.modalDistance}>
              {post.region} / {post.travel_start_date} - {post.travel_end_date}
            </p>
          </div>
        </div>

        <div style={styles.modalBody}>
          <div style={styles.authorBlock}>
            <AuthorAvatar post={post} size="large" />
            <div>
              <p style={styles.authorName}>{post.author.user_name}</p>
              <p style={styles.authorMeta}>
                {[post.author.nationality, post.author.age, GENDER_LABELS[post.author.gender]]
                  .filter(Boolean)
                  .join(" / ")}
              </p>
            </div>
          </div>

          <p style={styles.modalDescription}>{post.content}</p>

          <div style={styles.metaGrid}>
            <span style={styles.metaChip}>{COMPANION_LABELS[post.companion_type]}</span>
            <span style={styles.metaChip}>
              Ages {post.preferred_age_min}-{post.preferred_age_max}
            </span>
            <span style={styles.metaChip}>{GENDER_LABELS[post.preferred_gender]}</span>
          </div>

          {post.image_urls?.length ? (
            <div style={styles.modalImages}>
              {post.image_urls.map((url, index) => (
                <button
                  key={`${url}-${index}`}
                  type="button"
                  style={styles.modalImageButton}
                  onClick={() => onImageClick(url)}
                >
                  <img src={url} alt="" style={styles.modalImage} />
                </button>
              ))}
            </div>
          ) : null}

          <div style={styles.modalButtonGrid}>
            {isOwnPost ? (
              <button type="button" style={styles.primaryButton} onClick={onEdit}>
                Edit Post
              </button>
            ) : null}
            {canAddFriend ? (
              <button
                type="button"
                style={hasPendingRequest ? styles.secondaryButton : styles.primaryButton}
                onClick={onToggleFriend}
                disabled={hasPendingRequest || isSendingFriendRequest}
              >
                {isSendingFriendRequest
                  ? "Sending..."
                  : hasPendingRequest
                    ? "Request Sent"
                    : "Add Friend"}
              </button>
            ) : null}
            <button type="button" style={styles.secondaryButton} onClick={onViewProfile}>
              View Profile
            </button>
            {!isOwnPost ? (
              <button type="button" style={styles.secondaryButton} onClick={onChat}>
                Chat
              </button>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}

function ImageLightbox({ src, onClose }: { src: string; onClose: () => void }) {
  return (
    <div style={styles.lightboxOverlay} onClick={onClose}>
      <button type="button" style={styles.lightboxClose} onClick={onClose}>
        x
      </button>
      <img src={src} alt="" style={styles.lightboxImage} onClick={(event) => event.stopPropagation()} />
    </div>
  );
}

function SearchIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M10.5 18a7.5 7.5 0 1 1 5.303-12.803A7.5 7.5 0 0 1 10.5 18Zm0-13a5.5 5.5 0 1 0 0 11a5.5 5.5 0 0 0 0-11Zm10 15l-4.35-4.35"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.8"
      />
    </svg>
  );
}

function toErrorMessage(error: unknown, fallback: string): string {
  const apiError = error as {
    response?: {
      data?:
        | {
            detail?: unknown;
            message?: unknown;
          }
        | string;
    };
    message?: string;
  };

  if (typeof apiError.response?.data === "string") {
    return apiError.response.data;
  }

  const detail = apiError.response?.data?.detail;
  const message = apiError.response?.data?.message;

  return stringifyApiMessage(detail) || stringifyApiMessage(message) || apiError.message || fallback;
}

function stringifyApiMessage(value: unknown): string {
  if (!value) return "";
  if (typeof value === "string") return value;
  if (Array.isArray(value)) {
    return value
      .map((item) => {
        if (typeof item === "string") return item;
        if (item && typeof item === "object") {
          const errorItem = item as {
            loc?: unknown[];
            msg?: string;
            type?: string;
            ctx?: { min_length?: number };
          };
          const location = Array.isArray(errorItem.loc) ? errorItem.loc.join(".") : "";
          const friendlyMessage = toFriendlyValidationMessage(errorItem);
          if (friendlyMessage) return friendlyMessage;
          return [location, errorItem.msg || errorItem.type].filter(Boolean).join(": ");
        }
        return "";
      })
      .filter(Boolean)
      .join("\n");
  }

  if (typeof value === "object") {
    try {
      return JSON.stringify(value);
    } catch {
      return "";
    }
  }

  return String(value);
}

function toFriendlyValidationMessage(errorItem: {
  loc?: unknown[];
  msg?: string;
  type?: string;
  ctx?: { min_length?: number };
}): string {
  const location = Array.isArray(errorItem.loc) ? errorItem.loc.join(".") : "";
  const minLength = errorItem.ctx?.min_length;
  const isMinLengthError =
    errorItem.type === "string_too_short" ||
    /at least\s+\d+\s+characters/i.test(errorItem.msg ?? "");

  if (isMinLengthError && minLength === 10) {
    if (location.includes("content")) {
      return "Please enter at least 10 characters in the intro.";
    }

    return "Please enter at least 10 characters.";
  }

  return "";
}

const styles: Record<string, CSSProperties> = {
  page: {
    minHeight: "100dvh",
    padding: "24px 16px 40px",
    background: "transparent",
    fontFamily: "'Nunito', 'Apple SD Gothic Neo', sans-serif",
  },
  shell: {
    width: "100%",
    maxWidth: 760,
    margin: "0 auto",
    display: "flex",
    flexDirection: "column",
    gap: 18,
  },
  header: {
    display: "flex",
    alignItems: "flex-start",
    justifyContent: "space-between",
    gap: 16,
    paddingTop: 8,
  },
  eyebrow: {
    margin: 0,
    color: "var(--brand-primary-deep)",
    fontSize: "0.78rem",
    fontWeight: 800,
    letterSpacing: "0.14em",
    textTransform: "uppercase",
  },
  headerTitle: {
    margin: "6px 0 8px",
    fontSize: "clamp(1.9rem, 5vw, 2.4rem)",
    lineHeight: 1.05,
    color: "var(--text-primary)",
  },
  headerCopy: {
    maxWidth: 460,
    margin: 0,
    color: "var(--neutral-700)",
    fontSize: "0.95rem",
    lineHeight: 1.5,
  },
  headerButton: {
    border: "1px solid rgba(5,181,187,0.2)",
    borderRadius: 999,
    padding: "12px 16px",
    background: "linear-gradient(135deg, var(--brand-primary), #12c0c6)",
    color: "#ffffff",
    fontWeight: 800,
    cursor: "pointer",
    boxShadow: "0 12px 24px rgba(5,181,187,0.22)",
    flexShrink: 0,
  },
  tabPanel: {
    display: "grid",
    gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
    gap: 10,
    padding: 8,
    borderRadius: 22,
    background: "rgba(255,255,255,0.84)",
    border: "1px solid var(--border-soft)",
    boxShadow: "var(--shadow-soft)",
  },
  tabButton: {
    minHeight: 46,
    border: "none",
    borderRadius: 16,
    background: "transparent",
    color: "var(--neutral-700)",
    fontWeight: 800,
    cursor: "pointer",
  },
  tabButtonActive: {
    background: "linear-gradient(135deg, rgba(5,181,187,0.16), rgba(228,247,247,0.96))",
    color: "var(--text-primary)",
  },
  searchPanel: {
    position: "relative",
    padding: 20,
    borderRadius: 28,
    background:
      "linear-gradient(180deg, rgba(5,181,187,0.1), rgba(255,255,255,0.96) 44%)",
    border: "1px solid rgba(5,181,187,0.14)",
    boxShadow: "var(--shadow-soft)",
  },
  searchRow: {
    display: "flex",
    alignItems: "center",
    gap: 12,
  },
  searchWrap: {
    flex: 1,
    display: "flex",
    alignItems: "center",
    gap: 10,
    minHeight: 56,
    padding: "0 14px",
    borderRadius: 20,
    border: "1.5px solid rgba(5,181,187,0.16)",
    background: "rgba(255,255,255,0.92)",
    color: "var(--neutral-700)",
  },
  searchInput: {
    width: "100%",
    border: "none",
    outline: "none",
    background: "transparent",
    color: "var(--text-primary)",
    fontSize: "1rem",
  },
  searchAction: {
    minHeight: 54,
    border: "1px solid rgba(5,181,187,0.2)",
    borderRadius: 18,
    padding: "0 16px",
    background: "linear-gradient(135deg, var(--brand-primary), #12c0c6)",
    color: "#ffffff",
    fontWeight: 800,
    cursor: "pointer",
  },
  historyPanel: {
    position: "absolute",
    left: 20,
    right: 20,
    top: "calc(100% - 8px)",
    zIndex: 8,
    padding: 12,
    borderRadius: 20,
    background: "#ffffff",
    border: "1px solid var(--border-soft)",
    boxShadow: "0 18px 36px rgba(33,33,33,0.14)",
  },
  historyHeader: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    gap: 12,
    marginBottom: 10,
  },
  historyTitle: {
    color: "var(--text-secondary)",
    fontSize: "0.82rem",
    fontWeight: 800,
  },
  historyList: {
    display: "flex",
    flexDirection: "column",
    gap: 8,
  },
  historyItem: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 10,
    padding: "10px 12px",
    borderRadius: 14,
    background: "var(--surface-muted)",
  },
  historyTerm: {
    border: "none",
    background: "transparent",
    color: "var(--text-primary)",
    fontWeight: 700,
    cursor: "pointer",
    padding: 0,
    textAlign: "left",
  },
  iconButton: {
    width: 28,
    height: 28,
    border: "none",
    borderRadius: "50%",
    background: "rgba(248,180,0,0.16)",
    color: "var(--text-secondary)",
    cursor: "pointer",
    fontWeight: 800,
  },
  linkButton: {
    border: "none",
    background: "transparent",
    color: "var(--brand-primary-deep)",
    fontWeight: 800,
    cursor: "pointer",
    padding: 0,
  },
  filtersSection: {
    display: "flex",
    flexDirection: "column",
    gap: 12,
  },
  filterGroup: {
    display: "flex",
    flexWrap: "wrap",
    justifyContent: "center",
    gap: 10,
  },
  filterChip: {
    border: "1px solid rgba(248,180,0,0.18)",
    borderRadius: 999,
    padding: "12px 18px",
    background: "rgba(255,255,255,0.86)",
    color: "var(--neutral-700)",
    fontWeight: 800,
    cursor: "pointer",
  },
  filterChipActive: {
    background: "linear-gradient(135deg, rgba(248,180,0,0.2), rgba(255,233,179,0.92))",
    color: "var(--text-primary)",
    boxShadow: "0 12px 24px rgba(248,180,0,0.14)",
  },
  listSection: {
    display: "flex",
    flexDirection: "column",
    gap: 14,
  },
  card: {
    position: "relative",
    padding: 18,
    borderRadius: 28,
    background: "rgba(255,255,255,0.92)",
    border: "1px solid var(--border-soft)",
    boxShadow: "var(--shadow-soft)",
    cursor: "pointer",
  },
  cardHeader: {
    display: "flex",
    alignItems: "flex-start",
    justifyContent: "space-between",
    gap: 12,
  },
  authorBlock: {
    display: "flex",
    alignItems: "center",
    gap: 12,
    minWidth: 0,
  },
  avatar: {
    width: 44,
    height: 44,
    borderRadius: "50%",
    display: "grid",
    placeItems: "center",
    flexShrink: 0,
    background: "linear-gradient(135deg, var(--brand-primary), var(--brand-primary-deep))",
    color: "#ffffff",
    fontWeight: 800,
    overflow: "hidden",
  },
  avatarImage: {
    width: "100%",
    height: "100%",
    objectFit: "cover",
  },
  largeAvatar: {
    width: 60,
    height: 60,
    fontSize: "1.25rem",
  },
  authorName: {
    margin: 0,
    color: "var(--text-primary)",
    fontWeight: 800,
  },
  authorMeta: {
    margin: "4px 0 0",
    color: "var(--neutral-700)",
    fontSize: "0.82rem",
  },
  cardActions: {
    display: "flex",
    alignItems: "center",
    gap: 8,
    flexShrink: 0,
  },
  typeBadge: {
    padding: "7px 10px",
    borderRadius: 999,
    background: "var(--brand-primary-soft)",
    color: "var(--brand-primary-deep)",
    fontSize: "0.78rem",
    fontWeight: 800,
  },
  moreButton: {
    width: 34,
    height: 34,
    border: "1px solid rgba(5,181,187,0.14)",
    borderRadius: "50%",
    background: "rgba(255,255,255,0.9)",
    color: "var(--text-secondary)",
    fontWeight: 800,
    cursor: "pointer",
  },
  postMenu: {
    position: "absolute",
    right: 18,
    top: 58,
    zIndex: 12,
    display: "flex",
    flexDirection: "column",
    minWidth: 132,
    overflow: "hidden",
    borderRadius: 16,
    background: "#ffffff",
    border: "1px solid var(--border-soft)",
    boxShadow: "0 16px 34px rgba(33,33,33,0.16)",
  },
  menuButton: {
    border: "none",
    background: "transparent",
    padding: "12px 14px",
    color: "var(--text-secondary)",
    textAlign: "left",
    fontWeight: 700,
    cursor: "pointer",
  },
  dangerText: {
    color: "#dc2626",
  },
  cardBody: {
    marginTop: 16,
    display: "flex",
    flexDirection: "column",
    gap: 8,
  },
  cardTitle: {
    margin: 0,
    color: "var(--text-primary)",
    fontSize: "1.2rem",
    lineHeight: 1.2,
  },
  cardDescription: {
    margin: 0,
    color: "var(--neutral-700)",
    lineHeight: 1.55,
    fontSize: "0.94rem",
  },
  imageStrip: {
    display: "flex",
    gap: 8,
    marginTop: 14,
  },
  postImageWrap: {
    position: "relative",
    width: 72,
    height: 72,
    padding: 0,
    border: "none",
    borderRadius: 16,
    overflow: "hidden",
    background: "var(--surface-muted)",
    cursor: "zoom-in",
  },
  postImage: {
    width: "100%",
    height: "100%",
    objectFit: "cover",
  },
  imageCount: {
    position: "absolute",
    inset: 0,
    display: "grid",
    placeItems: "center",
    background: "rgba(24,26,32,0.58)",
    color: "#ffffff",
    fontWeight: 800,
  },
  metaGrid: {
    display: "flex",
    flexWrap: "wrap",
    gap: 8,
    marginTop: 14,
  },
  metaChip: {
    padding: "7px 10px",
    borderRadius: 999,
    background: "rgba(248,180,0,0.13)",
    color: "var(--text-secondary)",
    fontSize: "0.78rem",
    fontWeight: 700,
  },
  cardFooter: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    gap: 12,
    marginTop: 16,
  },
  likeButton: {
    border: "1px solid rgba(5,181,187,0.18)",
    borderRadius: 999,
    padding: "9px 13px",
    background: "rgba(255,255,255,0.9)",
    color: "var(--neutral-700)",
    fontWeight: 800,
    cursor: "pointer",
  },
  likeButtonActive: {
    borderColor: "rgba(248,180,0,0.26)",
    background: "var(--brand-secondary-soft)",
    color: "var(--text-primary)",
  },
  createdText: {
    color: "var(--neutral-700)",
    fontSize: "0.78rem",
  },
  emptyState: {
    padding: "48px 20px",
    textAlign: "center",
    borderRadius: 28,
    background: "rgba(255,255,255,0.88)",
    color: "var(--neutral-700)",
    border: "1px solid var(--border-soft)",
    boxShadow: "var(--shadow-soft)",
  },
  loadingState: {
    minHeight: 180,
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    justifyContent: "center",
    gap: 14,
    borderRadius: 28,
    background: "rgba(255,255,255,0.88)",
    border: "1px solid var(--border-soft)",
    boxShadow: "var(--shadow-soft)",
  },
  emptyTitle: {
    margin: 0,
    color: "var(--text-primary)",
    fontSize: "1.05rem",
    fontWeight: 800,
  },
  emptyCopy: {
    margin: "8px 0 0",
    color: "var(--neutral-700)",
    lineHeight: 1.5,
  },
  spinner: {
    display: "block",
    width: 40,
    height: 40,
    borderRadius: "50%",
    border: "4px solid rgba(5,181,187,0.16)",
    borderTop: "4px solid var(--brand-primary)",
    animation: "spin 0.8s linear infinite",
  },
  smallSpinner: {
    display: "block",
    width: 22,
    height: 22,
    borderRadius: "50%",
    border: "3px solid rgba(255,255,255,0.5)",
    borderTop: "3px solid #ffffff",
    animation: "spin 0.8s linear infinite",
  },
  loadMoreButton: {
    border: "1px solid rgba(5,181,187,0.18)",
    borderRadius: 18,
    padding: "14px 16px",
    background: "rgba(255,255,255,0.88)",
    color: "var(--brand-primary-deep)",
    fontWeight: 800,
    cursor: "pointer",
    boxShadow: "var(--shadow-soft)",
  },
  formPanel: {
    padding: 20,
    borderRadius: 28,
    background: "rgba(255,255,255,0.92)",
    border: "1px solid var(--border-soft)",
    boxShadow: "var(--shadow-soft)",
  },
  editBanner: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    gap: 12,
    padding: "12px 14px",
    marginBottom: 14,
    borderRadius: 16,
    background: "var(--brand-secondary-soft)",
    color: "var(--text-secondary)",
    fontWeight: 800,
  },
  saveHint: {
    margin: "0 0 12px",
    color: "var(--neutral-700)",
    fontSize: "0.82rem",
    textAlign: "right",
  },
  formGrid: {
    display: "flex",
    flexDirection: "column",
    gap: 16,
  },
  field: {
    display: "flex",
    flexDirection: "column",
    gap: 8,
  },
  fieldLabel: {
    color: "var(--text-secondary)",
    fontSize: "0.9rem",
    fontWeight: 800,
  },
  required: {
    color: "#dc2626",
  },
  input: {
    width: "100%",
    minHeight: 48,
    border: "1px solid rgba(5,181,187,0.16)",
    borderRadius: 16,
    padding: "0 14px",
    background: "var(--surface-panel)",
    color: "var(--text-primary)",
    outline: "none",
  },
  textarea: {
    minHeight: 132,
    padding: 14,
    resize: "vertical",
    lineHeight: 1.55,
  },
  counterText: {
    margin: "-2px 0 0",
    color: "var(--neutral-700)",
    fontSize: "0.78rem",
    textAlign: "right",
  },
  twoColumn: {
    display: "grid",
    gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
    gap: 12,
  },
  optionGrid: {
    display: "flex",
    flexWrap: "wrap",
    gap: 10,
  },
  optionButton: {
    border: "1px solid rgba(5,181,187,0.18)",
    borderRadius: 999,
    padding: "10px 14px",
    background: "rgba(255,255,255,0.86)",
    color: "var(--neutral-700)",
    fontWeight: 700,
    cursor: "pointer",
  },
  optionButtonActive: {
    background: "linear-gradient(135deg, rgba(5,181,187,0.18), rgba(228,247,247,0.96))",
    color: "var(--text-primary)",
  },
  photoGrid: {
    display: "flex",
    flexWrap: "wrap",
    gap: 10,
  },
  photoPreview: {
    position: "relative",
    width: 86,
    height: 86,
    borderRadius: 18,
    overflow: "hidden",
    background: "var(--surface-muted)",
  },
  photoImage: {
    width: "100%",
    height: "100%",
    objectFit: "cover",
  },
  uploadOverlay: {
    position: "absolute",
    inset: 0,
    display: "grid",
    placeItems: "center",
    background: "rgba(24,26,32,0.44)",
  },
  removePhotoButton: {
    position: "absolute",
    top: 6,
    right: 6,
    width: 24,
    height: 24,
    border: "none",
    borderRadius: "50%",
    background: "rgba(24,26,32,0.66)",
    color: "#ffffff",
    fontWeight: 800,
    cursor: "pointer",
  },
  addPhotoButton: {
    width: 86,
    height: 86,
    border: "2px dashed rgba(5,181,187,0.24)",
    borderRadius: 18,
    background: "rgba(228,247,247,0.36)",
    color: "var(--brand-primary-deep)",
    fontWeight: 800,
    cursor: "pointer",
  },
  hiddenInput: {
    display: "none",
  },
  formActions: {
    display: "flex",
    gap: 10,
    marginTop: 4,
  },
  primaryButton: {
    flex: 1,
    border: "1px solid rgba(5,181,187,0.2)",
    borderRadius: 18,
    padding: "14px 16px",
    background: "linear-gradient(135deg, var(--brand-primary), #12c0c6)",
    color: "#ffffff",
    fontWeight: 800,
    cursor: "pointer",
    boxShadow: "0 12px 24px rgba(5,181,187,0.22)",
  },
  secondaryButton: {
    flex: 1,
    border: "1px solid rgba(5,181,187,0.18)",
    borderRadius: 18,
    padding: "14px 16px",
    background: "rgba(255,255,255,0.88)",
    color: "var(--text-secondary)",
    fontWeight: 800,
    cursor: "pointer",
  },
  modalOverlay: {
    position: "fixed",
    inset: 0,
    zIndex: 30,
    display: "flex",
    alignItems: "flex-end",
    justifyContent: "center",
    padding: "16px 16px 0",
    background: "rgba(24,26,32,0.42)",
    animation: "fadeInOverlay 220ms ease-out",
  },
  modalCard: {
    width: "100%",
    maxWidth: 760,
    maxHeight: "88dvh",
    overflowY: "auto",
    borderRadius: "32px 32px 0 0",
    background: "var(--surface-panel)",
    boxShadow: "0 28px 72px rgba(24,26,32,0.18)",
    animation: "slideUpModal 280ms cubic-bezier(0.22, 1, 0.36, 1)",
  },
  modalHero: {
    minHeight: 210,
    padding: 22,
    display: "flex",
    flexDirection: "column",
    justifyContent: "space-between",
    borderRadius: "32px 32px 0 0",
    background: "linear-gradient(160deg, rgba(5,181,187,0.2), rgba(248,180,0,0.18))",
  },
  modalHeroTop: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 12,
  },
  modalCategory: {
    padding: "8px 12px",
    borderRadius: 999,
    background: "rgba(255,255,255,0.72)",
    color: "var(--text-secondary)",
    fontSize: "0.8rem",
    fontWeight: 800,
  },
  modalCloseButton: {
    width: 38,
    height: 38,
    border: "1px solid rgba(255,255,255,0.62)",
    borderRadius: "50%",
    background: "rgba(255,255,255,0.82)",
    color: "var(--text-secondary)",
    fontWeight: 800,
    cursor: "pointer",
  },
  modalTitle: {
    margin: 0,
    color: "var(--text-primary)",
    fontSize: "2rem",
    lineHeight: 1.05,
    fontWeight: 800,
  },
  modalDistance: {
    margin: "10px 0 0",
    color: "var(--text-secondary)",
    fontSize: "0.92rem",
  },
  modalBody: {
    padding: 22,
    display: "flex",
    flexDirection: "column",
    gap: 18,
  },
  modalDescription: {
    margin: 0,
    color: "var(--text-secondary)",
    lineHeight: 1.65,
  },
  modalImages: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fill, minmax(118px, 1fr))",
    gap: 10,
  },
  modalImage: {
    width: "100%",
    height: "100%",
    aspectRatio: "1 / 1",
    objectFit: "cover",
    background: "var(--surface-muted)",
  },
  modalImageButton: {
    width: "100%",
    aspectRatio: "1 / 1",
    padding: 0,
    border: "none",
    borderRadius: 18,
    overflow: "hidden",
    background: "var(--surface-muted)",
    cursor: "zoom-in",
  },
  modalButtonGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
    gap: 10,
  },
  lightboxOverlay: {
    position: "fixed",
    inset: 0,
    zIndex: 60,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    padding: 18,
    background: "rgba(8,12,16,0.82)",
    cursor: "zoom-out",
  },
  lightboxImage: {
    maxWidth: "min(100%, 980px)",
    maxHeight: "86dvh",
    objectFit: "contain",
    borderRadius: 20,
    boxShadow: "0 24px 80px rgba(0,0,0,0.36)",
  },
  lightboxClose: {
    position: "fixed",
    top: 18,
    right: 18,
    width: 42,
    height: 42,
    border: "1px solid rgba(255,255,255,0.32)",
    borderRadius: "50%",
    background: "rgba(255,255,255,0.92)",
    color: "var(--text-primary)",
    fontWeight: 800,
    cursor: "pointer",
  },
  chatSheet: {
    width: "100%",
    maxWidth: 760,
    borderRadius: "30px 30px 0 0",
    background: "var(--surface-panel)",
    boxShadow: "0 28px 72px rgba(24,26,32,0.18)",
    padding: "10px 18px 26px",
    display: "flex",
    flexDirection: "column",
    gap: 14,
    animation: "slideUpModal 280ms cubic-bezier(0.22, 1, 0.36, 1)",
  },
  sheetHandle: {
    width: 56,
    height: 6,
    borderRadius: 999,
    background: "rgba(5,181,187,0.24)",
    margin: "4px auto 6px",
  },
  sheetTitle: {
    margin: 0,
    color: "var(--text-primary)",
    fontSize: "1.1rem",
  },
  menuBackdrop: {
    position: "fixed",
    inset: 0,
    zIndex: 10,
    background: "transparent",
  },
};
