import type { CSSProperties } from "react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getMyProfile } from "../../api/auth";
import { type ChatRoom, type SystemContent } from "../../api/chat";
import {
  acceptFriendRequest,
  blockUser,
  cancelFriendRequest,
  deleteFriend,
  getBlockedUsers,
  getFriends,
  getReceivedFriendRequests,
  getSentFriendRequests,
  rejectFriendRequest,
  unblockUser,
  type FriendPeer,
  type Friendship,
  type UserBlock,
} from "../../api/friend";
import { useChat } from "./ChatProvider";
import { reportChatNetworkError } from "../../utils/chatDiagnostics";
import FeedPopup from "../../components/FeedPopup";

type ChatTab = "chats" | "requests" | "friends";
type LoadingKey = "received" | "sent" | "friends" | "blocks";

const DEFAULT_PROFILE_IMAGE_URL = "/default-profile.svg";

const TABS: Array<{ key: ChatTab; label: string }> = [
  { key: "chats", label: "Chats" },
  { key: "requests", label: "Requests" },
  { key: "friends", label: "Friends" },
];

export default function ChatPage() {
  const navigate = useNavigate();
  const {
    rooms: chatRooms,
    roomsLoading: chatLoading,
    connectionState: chatConnectionStatus,
    currentUserId,
    refreshRooms,
  } = useChat();
  const [tab, setTab] = useState<ChatTab>("chats");
  const [receivedRequests, setReceivedRequests] = useState<Friendship[]>([]);
  const [sentRequests, setSentRequests] = useState<Friendship[]>([]);
  const [friends, setFriends] = useState<Friendship[]>([]);
  const [blockedUsers, setBlockedUsers] = useState<UserBlock[]>([]);
  const [cursors, setCursors] = useState<Record<LoadingKey, string | null>>({
    received: null,
    sent: null,
    friends: null,
    blocks: null,
  });
  const [loading, setLoading] = useState<Record<LoadingKey, boolean>>({
    received: false,
    sent: false,
    friends: false,
    blocks: false,
  });
  const [actionId, setActionId] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [currentUserName, setCurrentUserName] = useState<string | null>(null);
  const [feedPopupUserId, setFeedPopupUserId] = useState<string | null>(null);
  const [isGroupModalOpen, setIsGroupModalOpen] = useState(false);
  const [groupTitle, setGroupTitle] = useState("");
  const [selectedGroupMemberIds, setSelectedGroupMemberIds] = useState<Set<string>>(new Set());

  const pendingCount = receivedRequests.length + sentRequests.length;
  const displayNamesById = useMemo(() => {
    const names = new Map<string, string>();

    if (currentUserId && currentUserName) {
      names.set(currentUserId, currentUserName);
    }

    friends.forEach((friend) => {
      names.set(friend.peer.user_id, friend.peer.user_name);
    });

    chatRooms.forEach((room) => {
      if (room.peer?.user_id && room.peer.user_name) {
        names.set(room.peer.user_id, room.peer.user_name);
      }

      room.members?.forEach((member) => {
        if (member.user_id && member.user_name) {
          names.set(member.user_id, member.user_name);
        }
      });
    });

    return names;
  }, [chatRooms, currentUserId, currentUserName, friends]);
  const resolveDisplayName = useCallback(
    (userId: string | null): string =>
      userId === null ? "(Unknown)" : displayNamesById.get(userId) || "Deleted User",
    [displayNamesById]
  );
  const chatRows = useMemo(
    () => chatRooms.map((room) => toChatRow(room, resolveDisplayName)),
    [chatRooms, resolveDisplayName]
  );

  useEffect(() => {
    void refreshAll();
  }, []);

  async function loadReceived(cursor?: string, append = false): Promise<void> {
    setLoading((current) => ({ ...current, received: true }));
    try {
      const response = await getReceivedFriendRequests(cursor);
      setReceivedRequests((current) =>
        append ? [...current, ...response.items] : response.items
      );
      setCursors((current) => ({ ...current, received: response.next_cursor }));
    } finally {
      setLoading((current) => ({ ...current, received: false }));
    }
  }

  async function loadSent(cursor?: string, append = false): Promise<void> {
    setLoading((current) => ({ ...current, sent: true }));
    try {
      const response = await getSentFriendRequests(cursor);
      setSentRequests((current) =>
        append ? [...current, ...response.items] : response.items
      );
      setCursors((current) => ({ ...current, sent: response.next_cursor }));
    } finally {
      setLoading((current) => ({ ...current, sent: false }));
    }
  }

  async function loadFriends(cursor?: string, append = false): Promise<void> {
    setLoading((current) => ({ ...current, friends: true }));
    try {
      const response = await getFriends(cursor);
      setFriends((current) => (append ? [...current, ...response.items] : response.items));
      setCursors((current) => ({ ...current, friends: response.next_cursor }));
    } finally {
      setLoading((current) => ({ ...current, friends: false }));
    }
  }

  async function loadBlocks(cursor?: string, append = false): Promise<void> {
    setLoading((current) => ({ ...current, blocks: true }));
    try {
      const response = await getBlockedUsers(cursor);
      setBlockedUsers((current) =>
        append ? [...current, ...response.items] : response.items
      );
      setCursors((current) => ({ ...current, blocks: response.next_cursor }));
    } finally {
      setLoading((current) => ({ ...current, blocks: false }));
    }
  }

  async function loadCurrentUserName(): Promise<void> {
    try {
      const profile = await getMyProfile();
      setCurrentUserName(profile?.user_name ?? null);
    } catch {
      setCurrentUserName(null);
    }
  }

  async function refreshAll(): Promise<void> {
    setError("");
    try {
      await Promise.all([
        refreshRooms(),
        loadCurrentUserName(),
        loadReceived(),
        loadSent(),
        loadFriends(),
        loadBlocks(),
      ]);
      window.dispatchEvent(new CustomEvent("krip:friend-chat-notifications-updated"));
    } catch (loadError) {
      reportChatNetworkError({
        action: "refresh_chat_page",
        detail: toErrorMessage(loadError, "Failed to load friend data."),
        extra: getErrorStatus(loadError),
      });
      setError(toErrorMessage(loadError, "Failed to load friend data."));
    }
  }

  async function runAction(action: () => Promise<unknown>, successMessage: string): Promise<void> {
    setNotice("");
    setError("");
    try {
      await action();
      setNotice(successMessage);
      await refreshAll();
    } catch (actionError) {
      setError(toErrorMessage(actionError, "Action failed. Please try again."));
    } finally {
      setActionId("");
    }
  }

  function isBusy(id: string): boolean {
    return actionId === id;
  }

  async function handleOpenDirectChat(userId: string): Promise<void> {
    setActionId(`chat:${userId}`);
    setError("");

    try {
      navigate(`/chat/${userId}`);
    } catch (chatError) {
      reportChatNetworkError({
        action: "open_direct_chat",
        detail: toErrorMessage(chatError, "Failed to open chat."),
        extra: getErrorStatus(chatError),
      });
      setError(toErrorMessage(chatError, "Failed to open chat."));
    } finally {
      setActionId("");
    }
  }

  function toggleGroupMember(userId: string): void {
    setSelectedGroupMemberIds((current) => {
      const next = new Set(current);
      if (next.has(userId)) {
        next.delete(userId);
      } else {
        if (next.size >= 99) {
          setError("A group chat can invite up to 99 friends.");
          return next;
        }
        next.add(userId);
      }
      return next;
    });
  }

  function closeGroupModal(): void {
    setIsGroupModalOpen(false);
    setGroupTitle("");
    setSelectedGroupMemberIds(new Set());
  }

  async function handleCreateGroupRoom(): Promise<void> {
    const memberIds = Array.from(selectedGroupMemberIds);
    if (memberIds.length === 0) {
      setError("Select at least one friend to create a group chat.");
      return;
    }

    setError("");
    setNotice("");

    try {
      const draftId = `GROUP_DRAFT_${Date.now()}`;
      const selectedMembers = friends
        .filter((friend) => selectedGroupMemberIds.has(friend.peer.user_id))
        .map((friend) => friend.peer);

      window.sessionStorage.setItem(
        `krip-chat-group-draft:${draftId}`,
        JSON.stringify({
          title: groupTitle.trim() || "Group Chat",
          memberIds,
          members: selectedMembers,
        })
      );
      setIsGroupModalOpen(false);
      setGroupTitle("");
      setSelectedGroupMemberIds(new Set());
      navigate(`/chat/${draftId}`);
    } catch (createError) {
      reportChatNetworkError({
        action: "prepare_group_chat",
        detail: toErrorMessage(createError, "Failed to prepare group chat."),
        extra: getErrorStatus(createError),
      });
      setError(toErrorMessage(createError, "Failed to prepare group chat."));
    }
  }

  return (
    <div style={styles.page}>
      <div style={styles.shell}>
        <header style={styles.header}>
          <div>
            <p style={styles.eyebrow}>Conversation</p>
            <h1 style={styles.title}>Friend/Chat</h1>
            <p style={styles.headerCopy}>
              Manage chats, friend requests, friends, and blocked users in one place.
            </p>
          </div>
          <div style={styles.headerActions}>
            <button type="button" style={styles.refreshButton} onClick={() => void refreshAll()}>
              Refresh
            </button>
            <button
              type="button"
              style={styles.primaryHeaderButton}
              onClick={() => setIsGroupModalOpen(true)}
            >
              New Group
            </button>
          </div>
        </header>

        <section style={styles.segment}>
          {TABS.map((item) => (
            <button
              key={item.key}
              type="button"
              onClick={() => setTab(item.key)}
              style={{
                ...styles.segmentButton,
                ...(tab === item.key ? styles.segmentButtonActive : {}),
              }}
            >
              {item.label}
              {item.key === "requests" && pendingCount > 0 ? (
                <span style={styles.countBadge}>{pendingCount}</span>
              ) : null}
            </button>
          ))}
        </section>

        {notice ? <div style={styles.notice}>{notice}</div> : null}
        {error ? <div style={styles.error}>{error}</div> : null}

        {tab === "chats" ? (
          <section style={styles.list}>
            <p style={styles.statusText}>WebSocket: {chatConnectionStatus}</p>
            {chatLoading && chatRows.length === 0 ? (
              <p style={styles.mutedText}>Loading chats...</p>
            ) : chatRows.length > 0 ? (
              chatRows.map((chat) => (
                <button
                  key={chat.id}
                  type="button"
                  style={styles.chatRow}
                  onClick={() => navigate(`/chat/${chat.id}`)}
                >
                  <Avatar name={chat.name} imageUrl={chat.imageUrl} />
                  <span style={styles.rowMain}>
                    <strong style={styles.rowTitle}>{chat.name}</strong>
                    <span style={styles.rowSubtitle}>{chat.subtitle}</span>
                    <span style={styles.rowSubtitle}>{chat.preview}</span>
                  </span>
                  {chat.unreadCount > 0 ? (
                    <span style={styles.unreadBadge}>
                      {chat.unreadCount >= 999 ? "999+" : chat.unreadCount}
                    </span>
                  ) : null}
                  <span style={styles.chevron}>{">"}</span>
                </button>
              ))
            ) : (
              <EmptyCard
                title="No chats yet"
                copy="Accepted friends will appear here as chat-ready contacts."
              />
            )}
          </section>
        ) : null}

        {tab === "requests" ? (
          <section style={styles.stack}>
            <RequestSection
              title="Received Requests"
              emptyTitle="No received requests"
              emptyCopy="Incoming friend requests will show up here."
              loading={loading.received}
              items={receivedRequests}
              nextCursor={cursors.received}
              onLoadMore={() => void loadReceived(cursors.received || undefined, true)}
              renderActions={(item) => (
                <>
                  <button
                    type="button"
                    style={styles.primaryButton}
                    disabled={Boolean(actionId)}
                    onClick={() => {
                      setActionId(`accept:${item.friendship_id}`);
                      void runAction(
                        () => acceptFriendRequest(item.friendship_id),
                        "Friend request accepted."
                      );
                    }}
                  >
                    {isBusy(`accept:${item.friendship_id}`) ? "Accepting..." : "Accept"}
                  </button>
                  <button
                    type="button"
                    style={styles.secondaryButton}
                    disabled={Boolean(actionId)}
                    onClick={() => {
                      setActionId(`reject:${item.friendship_id}`);
                      void runAction(
                        () => rejectFriendRequest(item.friendship_id),
                        "Friend request rejected."
                      );
                    }}
                  >
                    Reject
                  </button>
                </>
              )}
            />

            <RequestSection
              title="Sent Requests"
              emptyTitle="No sent requests"
              emptyCopy="Requests you send will stay here until accepted or canceled."
              loading={loading.sent}
              items={sentRequests}
              nextCursor={cursors.sent}
              onLoadMore={() => void loadSent(cursors.sent || undefined, true)}
              renderActions={(item) => (
                <button
                  type="button"
                  style={styles.secondaryButton}
                  disabled={Boolean(actionId)}
                  onClick={() => {
                    setActionId(`cancel:${item.friendship_id}`);
                    void runAction(
                      () => cancelFriendRequest(item.friendship_id),
                      "Friend request canceled."
                    );
                  }}
                >
                  {isBusy(`cancel:${item.friendship_id}`) ? "Canceling..." : "Cancel Request"}
                </button>
              )}
            />
          </section>
        ) : null}

        {tab === "friends" ? (
          <section style={styles.stack}>
            <div style={styles.panel}>
              <div style={styles.sectionHeader}>
                <h2 style={styles.sectionTitle}>Friends</h2>
                {cursors.friends ? (
                  <button
                    type="button"
                    style={styles.linkButton}
                    onClick={() => void loadFriends(cursors.friends || undefined, true)}
                  >
                    Load More
                  </button>
                ) : null}
              </div>

              {loading.friends && friends.length === 0 ? (
                <p style={styles.mutedText}>Loading friends...</p>
              ) : friends.length > 0 ? (
                <div style={styles.friendList}>
                  {friends.map((friend) => (
                    <FriendCard
                      key={friend.friendship_id}
                      item={friend}
                      onChat={() => void handleOpenDirectChat(friend.peer.user_id)}
                      onViewFeed={() => setFeedPopupUserId(friend.peer.user_id)}
                      onDelete={() => {
                        setActionId(`delete:${friend.friendship_id}`);
                        void runAction(
                          () => deleteFriend(friend.friendship_id),
                          "Friend deleted."
                        );
                      }}
                      onBlock={() => {
                        setActionId(`block:${friend.peer.user_id}`);
                        void runAction(
                          () => blockUser(friend.peer.user_id),
                          "User blocked."
                        );
                      }}
                      busy={Boolean(actionId)}
                    />
                  ))}
                </div>
              ) : (
                <EmptyCard
                  title="No friends yet"
                  copy="Accepted friends will appear here."
                />
              )}
            </div>

            <div style={styles.panel}>
              <div style={styles.sectionHeader}>
                <h2 style={styles.sectionTitle}>Blocked Users</h2>
                {cursors.blocks ? (
                  <button
                    type="button"
                    style={styles.linkButton}
                    onClick={() => void loadBlocks(cursors.blocks || undefined, true)}
                  >
                    Load More
                  </button>
                ) : null}
              </div>

              {loading.blocks && blockedUsers.length === 0 ? (
                <p style={styles.mutedText}>Loading blocked users...</p>
              ) : blockedUsers.length > 0 ? (
                <div style={styles.friendList}>
                  {blockedUsers.map((block) => (
                    <div key={block.block_id} style={styles.friendCard}>
                      <PeerSummary peer={block.blocked} />
                      <button
                        type="button"
                        style={styles.secondaryButton}
                        disabled={Boolean(actionId)}
                        onClick={() => {
                          setActionId(`unblock:${block.blocked.user_id}`);
                          void runAction(
                            () => unblockUser(block.blocked.user_id),
                            "User unblocked."
                          );
                        }}
                      >
                        Unblock
                      </button>
                    </div>
                  ))}
                </div>
              ) : (
                <EmptyCard
                  title="No blocked users"
                  copy="Blocked users will appear here."
                />
              )}
            </div>
          </section>
        ) : null}

        {feedPopupUserId ? (
          <FeedPopup
            key={feedPopupUserId}
            userId={feedPopupUserId}
            onClose={() => setFeedPopupUserId(null)}
          />
        ) : null}

        {isGroupModalOpen ? (
          <div style={styles.groupModalBackdrop} role="dialog" aria-modal="true">
            <section style={styles.groupModal}>
              <div style={styles.groupModalHeader}>
                <div>
                  <p style={styles.groupModalEyebrow}>Friends only</p>
                  <h2 style={styles.groupModalTitle}>New Group Chat</h2>
                </div>
                <button type="button" style={styles.closeButton} onClick={closeGroupModal}>
                  Close
                </button>
              </div>

              <label style={styles.groupField}>
                <span style={styles.groupLabel}>Room name</span>
                <input
                  value={groupTitle}
                  onChange={(event) => setGroupTitle(event.target.value)}
                  placeholder="Group Chat"
                  style={styles.input}
                  maxLength={40}
                />
              </label>

              <div style={styles.groupMemberList}>
                {friends.length > 0 ? (
                  friends.map((friend) => {
                    const selected = selectedGroupMemberIds.has(friend.peer.user_id);
                    return (
                      <button
                        key={friend.friendship_id}
                        type="button"
                        style={{
                          ...styles.groupMemberRow,
                          ...(selected ? styles.groupMemberRowSelected : {}),
                        }}
                        onClick={() => toggleGroupMember(friend.peer.user_id)}
                      >
                        <PeerSummary peer={friend.peer} />
                        <span style={selected ? styles.checkedCircle : styles.emptyCircle}>
                          {selected ? "✓" : ""}
                        </span>
                      </button>
                    );
                  })
                ) : (
                  <EmptyCard
                    title="No friends available"
                    copy="Group chats can only invite accepted friends."
                  />
                )}
              </div>

              <div style={styles.groupModalActions}>
                <button type="button" style={styles.secondaryButton} onClick={closeGroupModal}>
                  Cancel
                </button>
                <button
                  type="button"
                  style={styles.primaryButton}
                  onClick={() => void handleCreateGroupRoom()}
                  disabled={selectedGroupMemberIds.size === 0}
                >
                  Start Chat
                </button>
              </div>
            </section>
          </div>
        ) : null}
      </div>
    </div>
  );
}

function RequestSection({
  title,
  emptyTitle,
  emptyCopy,
  loading,
  items,
  nextCursor,
  onLoadMore,
  renderActions,
}: {
  title: string;
  emptyTitle: string;
  emptyCopy: string;
  loading: boolean;
  items: Friendship[];
  nextCursor: string | null;
  onLoadMore: () => void;
  renderActions: (item: Friendship) => React.ReactNode;
}) {
  return (
    <div style={styles.panel}>
      <div style={styles.sectionHeader}>
        <h2 style={styles.sectionTitle}>{title}</h2>
        {nextCursor ? (
          <button type="button" style={styles.linkButton} onClick={onLoadMore}>
            Load More
          </button>
        ) : null}
      </div>

      {loading && items.length === 0 ? (
        <p style={styles.mutedText}>Loading...</p>
      ) : items.length > 0 ? (
        <div style={styles.friendList}>
          {items.map((item) => (
            <div key={item.friendship_id} style={styles.friendCard}>
              <PeerSummary peer={item.peer} />
              <div style={styles.actionRow}>{renderActions(item)}</div>
            </div>
          ))}
        </div>
      ) : (
        <EmptyCard title={emptyTitle} copy={emptyCopy} />
      )}
    </div>
  );
}

function FriendCard({
  item,
  onChat,
  onViewFeed,
  onDelete,
  onBlock,
  busy,
}: {
  item: Friendship;
  onChat: () => void;
  onViewFeed: () => void;
  onDelete: () => void;
  onBlock: () => void;
  busy: boolean;
}) {
  return (
    <div style={styles.friendCard}>
      <PeerSummary peer={item.peer} />
      <div style={styles.actionRow}>
        <button type="button" style={styles.primaryButton} onClick={onChat}>
          Chat
        </button>
        <button type="button" style={styles.secondaryButton} onClick={onViewFeed}>
          Feed
        </button>
        <button type="button" style={styles.secondaryButton} disabled={busy} onClick={onDelete}>
          Delete
        </button>
        <button type="button" style={styles.dangerButton} disabled={busy} onClick={onBlock}>
          Block
        </button>
      </div>
    </div>
  );
}

function PeerSummary({ peer }: { peer: FriendPeer }) {
  return (
    <div style={styles.peerSummary}>
      <Avatar name={peer.user_name} imageUrl={peer.profile_image_url} />
      <span style={styles.rowMain}>
        <strong style={styles.rowTitle}>{peer.user_name}</strong>
        <span style={styles.rowSubtitle}>
          {peer.nationality} / {peer.age} / {formatGender(peer.gender)}
        </span>
        <span style={styles.userId}>{peer.user_id}</span>
      </span>
    </div>
  );
}

function Avatar({ name, imageUrl }: { name: string; imageUrl?: string | null }) {
  return (
    <span style={styles.avatar}>
      {imageUrl ? (
        <img src={imageUrl} alt={name} style={styles.avatarImage} />
      ) : (
        <img src={DEFAULT_PROFILE_IMAGE_URL} alt={name} style={styles.avatarImage} />
      )}
    </span>
  );
}

function EmptyCard({ title, copy }: { title: string; copy: string }) {
  return (
    <div style={styles.emptyCard}>
      <p style={styles.emptyTitle}>{title}</p>
      <p style={styles.emptyCopy}>{copy}</p>
    </div>
  );
}

function formatGender(gender: string): string {
  if (gender === "male") return "Male";
  if (gender === "female") return "Female";
  return gender;
}

function toChatRow(
  room: ChatRoom,
  resolveDisplayName: (userId: string | null) => string
): {
  id: string;
  name: string;
  imageUrl: string | null;
  subtitle: string;
  preview: string;
  unreadCount: number;
} {
  const name =
    room.type === "direct"
      ? room.peer?.user_name || "Deleted User"
      : room.title || "Group Chat";
  const subtitle = room.type === "direct" ? "Direct message" : "Group chat";

  return {
    id: room.chat_room_id,
    name,
    imageUrl: room.type === "direct" ? room.peer?.profile_image_url ?? null : null,
    subtitle,
    preview: renderLastMessage(room.last_message, resolveDisplayName),
    unreadCount: room.unread_count,
  };
}

function renderLastMessage(
  lastMessage: ChatRoom["last_message"],
  resolveDisplayName: (userId: string | null) => string
): string {
  if (!lastMessage) return "No messages yet.";
  if (lastMessage.content === null) return "Deleted message.";
  if (lastMessage.type === "system") {
    return renderSystemLastMessage(lastMessage.content, resolveDisplayName);
  }
  if (typeof lastMessage.content === "string") return lastMessage.content;
  return "";
}

function renderSystemLastMessage(
  content: ChatRoom["last_message"]["content"],
  resolveDisplayName: (userId: string | null) => string
): string {
  if (!isSystemContent(content)) return "System message";

  const actorName = resolveDisplayName(content.actor_id);
  if (content.action === "created") {
    return `${actorName} created the chat room.`;
  }
  if (content.action === "join") {
    const targetNames = content.target_ids.map(resolveDisplayName);
    if (targetNames.length === 1 && (!content.actor_id || content.actor_id === content.target_ids[0])) {
      return `${targetNames[0]} joined.`;
    }
    return `${actorName} invited ${formatTargetNames(targetNames)}.`;
  }
  if (content.action === "leave") {
    return `${actorName} left.`;
  }
  if (content.action === "kick") {
    return `${actorName} removed ${formatTargetNames(content.target_ids.map(resolveDisplayName))}.`;
  }

  return "System message";
}

function isSystemContent(content: unknown): content is SystemContent {
  if (!content || typeof content !== "object") return false;

  const value = content as Partial<SystemContent>;
  if (value.action === "created" || value.action === "leave") {
    return "actor_id" in value;
  }
  if (value.action === "join" || value.action === "kick") {
    return "actor_id" in value && Array.isArray(value.target_ids);
  }
  return false;
}

function formatTargetNames(names: string[]): string {
  if (names.length === 0) return "(Unknown)";
  if (names.length === 1) return names[0];
  return `${names[0]} and ${names.length - 1} others`;
}

function toErrorMessage(error: unknown, fallback: string): string {
  const apiError = error as {
    response?: { data?: { detail?: string; message?: string } };
    message?: string;
  };
  return apiError.response?.data?.detail || apiError.response?.data?.message || apiError.message || fallback;
}

function getErrorStatus(error: unknown): number | undefined {
  const apiError = error as { response?: { status?: number } };
  return apiError.response?.status;
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
    gap: 16,
  },
  header: {
    display: "flex",
    alignItems: "flex-start",
    justifyContent: "space-between",
    gap: 16,
    paddingTop: 8,
  },
  headerActions: {
    display: "flex",
    flexWrap: "wrap",
    justifyContent: "flex-end",
    gap: 10,
  },
  eyebrow: {
    margin: 0,
    color: "var(--brand-primary-deep)",
    fontSize: "0.78rem",
    fontWeight: 800,
    letterSpacing: "0.14em",
    textTransform: "uppercase",
  },
  title: {
    margin: "6px 0 8px",
    color: "var(--text-primary)",
    fontSize: "clamp(1.9rem, 5vw, 2.4rem)",
    lineHeight: 1.05,
  },
  headerCopy: {
    maxWidth: 470,
    margin: 0,
    color: "var(--neutral-700)",
    fontSize: "0.95rem",
    lineHeight: 1.5,
  },
  refreshButton: {
    border: "1px solid rgba(5,181,187,0.18)",
    borderRadius: 999,
    padding: "12px 16px",
    background: "rgba(255,255,255,0.88)",
    color: "var(--text-secondary)",
    fontWeight: 800,
    cursor: "pointer",
    boxShadow: "var(--shadow-soft)",
  },
  primaryHeaderButton: {
    border: "1px solid rgba(5,181,187,0.22)",
    borderRadius: 999,
    padding: "12px 16px",
    background: "linear-gradient(135deg, var(--brand-primary), #12c0c6)",
    color: "#ffffff",
    fontWeight: 900,
    cursor: "pointer",
    boxShadow: "0 12px 24px rgba(5,181,187,0.2)",
  },
  segment: {
    padding: 8,
    borderRadius: 22,
    background: "rgba(255,255,255,0.88)",
    display: "grid",
    gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
    gap: 8,
    border: "1px solid var(--border-soft)",
    boxShadow: "var(--shadow-soft)",
  },
  segmentButton: {
    border: "none",
    borderRadius: 16,
    minHeight: 46,
    background: "transparent",
    color: "var(--neutral-700)",
    fontWeight: 800,
    cursor: "pointer",
  },
  segmentButtonActive: {
    background: "linear-gradient(135deg, rgba(5,181,187,0.18), rgba(248,180,0,0.18))",
    color: "var(--text-primary)",
  },
  countBadge: {
    display: "inline-grid",
    placeItems: "center",
    minWidth: 20,
    height: 20,
    marginLeft: 6,
    padding: "0 6px",
    borderRadius: 999,
    background: "var(--brand-secondary)",
    color: "var(--text-primary)",
    fontSize: "0.72rem",
  },
  notice: {
    padding: "12px 14px",
    borderRadius: 16,
    background: "var(--brand-primary-soft)",
    color: "var(--brand-primary-deep)",
    fontWeight: 800,
  },
  error: {
    padding: "12px 14px",
    borderRadius: 16,
    background: "rgba(220,38,38,0.1)",
    color: "#b91c1c",
    fontWeight: 800,
  },
  list: {
    display: "flex",
    flexDirection: "column",
    gap: 12,
  },
  stack: {
    display: "flex",
    flexDirection: "column",
    gap: 14,
  },
  panel: {
    padding: 18,
    borderRadius: 28,
    background: "rgba(255,255,255,0.92)",
    border: "1px solid var(--border-soft)",
    boxShadow: "var(--shadow-soft)",
  },
  sectionHeader: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 12,
    marginBottom: 12,
  },
  sectionTitle: {
    margin: 0,
    color: "var(--text-primary)",
    fontSize: "1.05rem",
    fontWeight: 800,
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
  friendList: {
    display: "flex",
    flexDirection: "column",
    gap: 12,
  },
  friendCard: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 14,
    padding: 14,
    borderRadius: 20,
    background: "rgba(255,255,255,0.82)",
    border: "1px solid var(--border-soft)",
  },
  peerSummary: {
    display: "flex",
    alignItems: "center",
    gap: 12,
    minWidth: 0,
    flex: 1,
  },
  chatRow: {
    display: "flex",
    alignItems: "center",
    gap: 12,
    width: "100%",
    padding: 16,
    borderRadius: 24,
    background: "rgba(255,255,255,0.92)",
    border: "1px solid var(--border-soft)",
    boxShadow: "var(--shadow-soft)",
    cursor: "pointer",
    textAlign: "left",
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
  rowMain: {
    minWidth: 0,
    display: "flex",
    flexDirection: "column",
    gap: 4,
    flex: 1,
  },
  rowTitle: {
    color: "var(--text-primary)",
    fontSize: "0.98rem",
  },
  rowSubtitle: {
    color: "var(--neutral-700)",
    fontSize: "0.82rem",
  },
  userId: {
    color: "var(--neutral-500)",
    fontSize: "0.72rem",
    overflowWrap: "anywhere",
  },
  chevron: {
    color: "var(--neutral-700)",
    fontSize: "1.4rem",
  },
  actionRow: {
    display: "flex",
    flexWrap: "wrap",
    justifyContent: "flex-end",
    gap: 8,
  },
  primaryButton: {
    border: "1px solid rgba(5,181,187,0.2)",
    borderRadius: 16,
    minHeight: 42,
    padding: "0 14px",
    background: "linear-gradient(135deg, var(--brand-primary), #12c0c6)",
    color: "#ffffff",
    fontWeight: 800,
    cursor: "pointer",
    whiteSpace: "nowrap",
  },
  secondaryButton: {
    border: "1px solid rgba(5,181,187,0.18)",
    borderRadius: 16,
    minHeight: 42,
    padding: "0 14px",
    background: "rgba(255,255,255,0.88)",
    color: "var(--text-secondary)",
    fontWeight: 800,
    cursor: "pointer",
    whiteSpace: "nowrap",
  },
  dangerButton: {
    border: "1px solid rgba(220,38,38,0.18)",
    borderRadius: 16,
    minHeight: 42,
    padding: "0 14px",
    background: "rgba(255,255,255,0.88)",
    color: "#dc2626",
    fontWeight: 800,
    cursor: "pointer",
    whiteSpace: "nowrap",
  },
  linkButton: {
    border: "none",
    background: "transparent",
    color: "var(--brand-primary-deep)",
    fontWeight: 800,
    cursor: "pointer",
    padding: 0,
  },
  mutedText: {
    margin: 0,
    color: "var(--neutral-700)",
    lineHeight: 1.5,
  },
  statusText: {
    margin: "0 0 2px",
    color: "var(--neutral-700)",
    fontSize: "0.78rem",
    fontWeight: 800,
  },
  unreadBadge: {
    display: "inline-grid",
    placeItems: "center",
    minWidth: 24,
    height: 24,
    padding: "0 7px",
    borderRadius: 999,
    background: "var(--brand-secondary)",
    color: "var(--text-primary)",
    fontSize: "0.76rem",
    fontWeight: 900,
  },
  emptyCard: {
    padding: 22,
    borderRadius: 24,
    background: "rgba(255,255,255,0.88)",
    border: "1px solid var(--border-soft)",
  },
  emptyTitle: {
    margin: 0,
    color: "var(--text-primary)",
    fontWeight: 800,
  },
  emptyCopy: {
    margin: "8px 0 0",
    color: "var(--neutral-700)",
    lineHeight: 1.55,
  },
  groupModalBackdrop: {
    position: "fixed",
    inset: 0,
    zIndex: 80,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    padding: 18,
    background: "rgba(24,26,32,0.48)",
  },
  groupModal: {
    width: "100%",
    maxWidth: 520,
    maxHeight: "86dvh",
    overflowY: "auto",
    display: "flex",
    flexDirection: "column",
    gap: 16,
    padding: 20,
    borderRadius: 28,
    background: "#ffffff",
    boxShadow: "0 28px 72px rgba(24,26,32,0.22)",
  },
  groupModalHeader: {
    display: "flex",
    alignItems: "flex-start",
    justifyContent: "space-between",
    gap: 14,
  },
  groupModalEyebrow: {
    margin: 0,
    color: "var(--brand-primary-deep)",
    fontSize: "0.74rem",
    fontWeight: 900,
    textTransform: "uppercase",
    letterSpacing: "0.12em",
  },
  groupModalTitle: {
    margin: "5px 0 0",
    color: "var(--text-primary)",
    fontSize: "1.35rem",
    lineHeight: 1.15,
  },
  closeButton: {
    border: "1px solid rgba(5,181,187,0.16)",
    borderRadius: 999,
    padding: "9px 12px",
    background: "rgba(255,255,255,0.9)",
    color: "var(--text-secondary)",
    fontWeight: 800,
    cursor: "pointer",
  },
  groupField: {
    display: "flex",
    flexDirection: "column",
    gap: 8,
  },
  groupLabel: {
    color: "var(--text-secondary)",
    fontSize: "0.86rem",
    fontWeight: 900,
  },
  groupMemberList: {
    display: "flex",
    flexDirection: "column",
    gap: 10,
  },
  groupMemberRow: {
    width: "100%",
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 12,
    padding: 12,
    border: "1px solid var(--border-soft)",
    borderRadius: 18,
    background: "rgba(255,255,255,0.92)",
    cursor: "pointer",
    textAlign: "left",
  },
  groupMemberRowSelected: {
    borderColor: "rgba(5,181,187,0.34)",
    background: "rgba(228,247,247,0.7)",
  },
  emptyCircle: {
    width: 24,
    height: 24,
    borderRadius: "50%",
    border: "2px solid rgba(5,181,187,0.2)",
    flexShrink: 0,
  },
  checkedCircle: {
    width: 24,
    height: 24,
    borderRadius: "50%",
    display: "grid",
    placeItems: "center",
    background: "var(--brand-primary)",
    color: "#ffffff",
    fontSize: "0.78rem",
    fontWeight: 900,
    flexShrink: 0,
  },
  groupModalActions: {
    display: "grid",
    gridTemplateColumns: "1fr 1fr",
    gap: 10,
  },
};
