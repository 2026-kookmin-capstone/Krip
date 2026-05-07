import type { CSSProperties } from "react";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  createGroupChatRoom,
  deleteChatMessage,
  editChatMessage,
  getChatRoom,
  getChatRoomMembers,
  inviteChatRoomMembers,
  kickChatRoomMember,
  leaveChatRoom,
  type ChatMessage,
  type ChatPeer,
  type ChatRoom,
  type ChatRoomMember,
} from "../../api/chat";
import { getFriendDetail, getFriends, type FriendPeer, type Friendship } from "../../api/friend";
import FeedPopup from "../../components/FeedPopup";
import { useChat } from "./ChatProvider";

const BOTTOM_THRESHOLD_PX = 160;
const DEFAULT_PROFILE_IMAGE_URL = "/default-profile.svg";

interface GroupDraft {
  draftId: string;
  title: string;
  memberIds: string[];
  members: FriendPeer[];
}

export default function ChatRoomPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const messageListRef = useRef<HTMLElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const scrollModeRef = useRef<"bottom" | "preserve">("bottom");
  const shouldForceScrollToBottomRef = useRef(true);
  const scrollSnapshotRef = useRef<{ height: number; top: number } | null>(null);
  const {
    connectionState,
    currentUserId,
    messagesByRoom,
    roomPageStateByRoom,
    openDirectChat,
    setActiveRoomId,
    loadInitialMessages,
    loadOlderMessages,
    sendMessage,
    sendRead,
  } = useChat();
  const [room, setRoom] = useState<ChatRoom | null>(null);
  const [draftPeer, setDraftPeer] = useState<FriendPeer | null>(null);
  const [groupDraft, setGroupDraft] = useState<GroupDraft | null>(null);
  const [roomMembers, setRoomMembers] = useState<ChatRoomMember[]>([]);
  const [input, setInput] = useState("");
  const [errorMessage, setErrorMessage] = useState("");
  const [feedPopupUserId, setFeedPopupUserId] = useState<string | null>(null);
  const [isMenuOpen, setIsMenuOpen] = useState(false);
  const [isSearchOpen, setIsSearchOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [friends, setFriends] = useState<Friendship[]>([]);
  const [friendsLoading, setFriendsLoading] = useState(false);
  const [selectedInviteIds, setSelectedInviteIds] = useState<Set<string>>(new Set());
  const [inviteMessage, setInviteMessage] = useState("");
  const [inviteBusy, setInviteBusy] = useState(false);
  const [knownUsers, setKnownUsers] = useState<Record<string, ChatPeer>>({});
  const [messageActionId, setMessageActionId] = useState<string | null>(null);
  const [editingMessageId, setEditingMessageId] = useState<string | null>(null);
  const [editingContent, setEditingContent] = useState("");
  const [messageBusyId, setMessageBusyId] = useState<string | null>(null);
  const [roomActionBusy, setRoomActionBusy] = useState(false);

  const roomId = room?.chat_room_id ?? "";
  const messages = useMemo(
    () => (roomId ? messagesByRoom[roomId] ?? [] : []),
    [messagesByRoom, roomId]
  );
  const roomPageState = roomId ? roomPageStateByRoom[roomId] : undefined;
  const roomName = useMemo(() => {
    if (!room) return groupDraft?.title || draftPeer?.user_name || "Chat";
    if (room.type === "direct") return room.peer?.user_name || "Deleted User";
    return room.title || "Group Chat";
  }, [draftPeer, groupDraft, room]);
  const roomFeedUserId =
    room?.type === "direct" && room.peer?.user_id
      ? room.peer.user_id
      : draftPeer?.user_id ?? null;
  const roomProfileImageUrl =
    room?.type === "direct"
      ? room.peer?.profile_image_url || DEFAULT_PROFILE_IMAGE_URL
      : draftPeer?.profile_image_url || DEFAULT_PROFILE_IMAGE_URL;
  const participants = useMemo(
    () => getRoomParticipants(room, draftPeer, groupDraft, currentUserId, roomMembers),
    [currentUserId, draftPeer, groupDraft, room, roomMembers]
  );
  const resolveDisplayName = useCallback(
    (userId: string | null): string => {
      if (!userId) return "(Unknown)";
      if (userId === currentUserId) return "You";
      return knownUsers[userId]?.user_name || "Deleted User";
    },
    [currentUserId, knownUsers]
  );
  const visibleMessages = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    if (!query) return messages;

    return messages.filter((message) =>
      renderMessageContent(message, resolveDisplayName).toLowerCase().includes(query)
    );
  }, [messages, resolveDisplayName, searchQuery]);
  const creatorId = useMemo(() => getCreatorId(messages), [messages]);
  const canManageGroup = Boolean(room?.type === "group" && creatorId && creatorId === currentUserId);
  const participantIds = useMemo(
    () => new Set(participants.map((participant) => participant.user_id).filter(Boolean)),
    [participants]
  );
  const invitableFriends = useMemo(
    () =>
      friends.filter(
        (friend) =>
          friend.peer.user_id !== currentUserId && !participantIds.has(friend.peer.user_id)
      ),
    [currentUserId, friends, participantIds]
  );


  useEffect(() => {
    let cancelled = false;

    async function loadRoom(): Promise<void> {
      if (!id) return;

      try {
        if (id.startsWith("USER_")) {
          const detail = await getFriendDetail(id);
          if (cancelled) return;

          setDraftPeer(detail);
          setGroupDraft(null);
          setRoom(null);
          setRoomMembers([]);
          setSearchQuery("");
          return;
        }

        if (id.startsWith("GROUP_DRAFT_")) {
          const draft = readGroupDraft(id);
          if (!draft) {
            throw new Error("Group draft expired. Please create it again.");
          }
          if (cancelled) return;

          setGroupDraft(draft);
          setDraftPeer(null);
          setRoom(null);
          setRoomMembers([]);
          setSearchQuery("");
          return;
        }

        const nextRoom = await getChatRoom(id);
        if (cancelled) return;

        setDraftPeer(null);
        setGroupDraft(null);
        setRoom(nextRoom);
        if (nextRoom.type === "group") {
          const membersResponse = await getChatRoomMembers(nextRoom.chat_room_id);
          if (!cancelled) {
            setRoomMembers(membersResponse.items);
          }
        } else {
          setRoomMembers([]);
        }
        if (id !== nextRoom.chat_room_id) {
          navigate(`/chat/${nextRoom.chat_room_id}`, { replace: true });
        }
      } catch (error) {
        if (!cancelled) {
          setErrorMessage(toErrorMessage(error, "Failed to open chat room."));
        }
      }
    }

    void loadRoom();

    return () => {
      cancelled = true;
    };
  }, [id, navigate]);

  useEffect(() => {
    if (!roomId) return;

    shouldForceScrollToBottomRef.current = true;
    setActiveRoomId(roomId);
    void loadInitialMessages(roomId);

    return () => {
      setActiveRoomId("");
    };
  }, [loadInitialMessages, roomId, setActiveRoomId]);

  useEffect(() => {
    if (room?.type !== "group" || friends.length > 0 || friendsLoading) return;

    setFriendsLoading(true);
    getFriends()
      .then((response) => setFriends(response.items))
      .catch(() => {
        // Friend cache is only used for display-name lookup.
      })
      .finally(() => setFriendsLoading(false));
  }, [friends.length, friendsLoading, room?.type]);

  useEffect(() => {
    if (!roomId) return;

    const lastSeq = getLastServerSeq(messages);
    if (lastSeq > 0) {
      sendRead(roomId, lastSeq);
    }
  }, [messages, roomId, sendRead]);

  useEffect(() => {
    const nextKnownUsers: Record<string, ChatPeer> = {};

    if (draftPeer) {
      nextKnownUsers[draftPeer.user_id] = {
        user_id: draftPeer.user_id,
        user_name: draftPeer.user_name,
        profile_image_url: draftPeer.profile_image_url,
      };
    }

    groupDraft?.members.forEach((member) => {
      nextKnownUsers[member.user_id] = {
        user_id: member.user_id,
        user_name: member.user_name,
        profile_image_url: member.profile_image_url,
      };
    });

    friends.forEach((friend) => {
      nextKnownUsers[friend.peer.user_id] = {
        user_id: friend.peer.user_id,
        user_name: friend.peer.user_name,
        profile_image_url: friend.peer.profile_image_url,
      };
    });

    participants.forEach((participant) => {
      if (participant.user_id) {
        nextKnownUsers[participant.user_id] = participant;
      }
    });

    if (Object.keys(nextKnownUsers).length > 0) {
      setKnownUsers((current) => ({ ...current, ...nextKnownUsers }));
    }
  }, [draftPeer, friends, groupDraft, participants]);

  useEffect(() => {
    const missingIds = Array.from(getMessageUserIds(messages)).filter(
      (userId) => userId !== currentUserId && !knownUsers[userId]
    );
    if (missingIds.length === 0) return;

    let cancelled = false;
    missingIds.slice(0, 20).forEach((userId) => {
      getFriendDetail(userId)
        .then((detail) => {
          if (cancelled) return;
          setKnownUsers((current) => ({
            ...current,
            [userId]: {
              user_id: detail.user_id,
              user_name: detail.user_name,
              profile_image_url: detail.profile_image_url,
            },
          }));
        })
        .catch(() => {
          if (cancelled) return;
          setKnownUsers((current) => ({
            ...current,
            [userId]: {
              user_id: userId,
              user_name: "Deleted User",
              profile_image_url: null,
            },
          }));
        });
    });

    return () => {
      cancelled = true;
    };
  }, [currentUserId, knownUsers, messages]);

  useLayoutEffect(() => {
    if (scrollModeRef.current === "preserve") {
      const snapshot = scrollSnapshotRef.current;
      const scroller = messageListRef.current;
      scrollModeRef.current = "bottom";
      scrollSnapshotRef.current = null;

      if (snapshot && scroller) {
        scroller.scrollTop = snapshot.top + scroller.scrollHeight - snapshot.height;
      }

      return;
    }

    const shouldForceScroll = shouldForceScrollToBottomRef.current;
    if (shouldForceScroll) {
      shouldForceScrollToBottomRef.current = false;
    }

    if (shouldForceScroll || isNearBottom(messageListRef.current)) {
      bottomRef.current?.scrollIntoView({
        behavior: shouldForceScroll ? "auto" : "smooth",
        block: "end",
      });
    }
  }, [messages]);

  async function handleLoadOlderMessages(): Promise<void> {
    if (!roomId) return;

    const scroller = messageListRef.current;
    scrollModeRef.current = "preserve";
    scrollSnapshotRef.current = {
      height: scroller?.scrollHeight ?? 0,
      top: scroller?.scrollTop ?? 0,
    };
    await loadOlderMessages(roomId);
  }

  async function handleSend(): Promise<void> {
    const content = input.trim();
    if (!content || content.length > 2000) return;

    if (roomId) {
      sendMessage(roomId, content);
      setInput("");
      return;
    }

    if (!draftPeer?.user_id && !groupDraft) return;

    try {
      const nextRoom = groupDraft
        ? await createGroupChatRoom(groupDraft.title, groupDraft.memberIds)
        : await openDirectChat(draftPeer.user_id);
      setRoom(nextRoom);
      if (nextRoom.type === "group") {
        const membersResponse = await getChatRoomMembers(nextRoom.chat_room_id);
        setRoomMembers(membersResponse.items);
      } else {
        setRoomMembers([]);
      }
      setDraftPeer(null);
      if (groupDraft) {
        window.sessionStorage.removeItem(`krip-chat-group-draft:${groupDraft.draftId}`);
      }
      setGroupDraft(null);
      navigate(`/chat/${nextRoom.chat_room_id}`, { replace: true });
      setActiveRoomId(nextRoom.chat_room_id);
      sendMessage(nextRoom.chat_room_id, content);
    } catch (error) {
      setErrorMessage(toErrorMessage(error, "Failed to create chat room."));
      return;
    }
    setInput("");
  }

  function openUserFeed(userId?: string | null): void {
    if (userId && userId !== currentUserId) {
      setFeedPopupUserId(userId);
    }
  }

  async function openMenu(): Promise<void> {
    setIsMenuOpen(true);
    setInviteMessage("");
    if (room?.type !== "group") {
      return;
    }
    setFriendsLoading(true);
    try {
      const response = await getFriends();
      setFriends(response.items);
    } catch (error) {
      setInviteMessage(toErrorMessage(error, "Failed to load friends."));
    } finally {
      setFriendsLoading(false);
    }
  }

  function closeMenu(): void {
    setIsMenuOpen(false);
    setSelectedInviteIds(new Set());
    setInviteMessage("");
  }

  function toggleInviteFriend(userId: string): void {
    setSelectedInviteIds((current) => {
      const next = new Set(current);
      if (next.has(userId)) {
        next.delete(userId);
      } else {
        if (next.size >= 50) {
          setInviteMessage("You can invite up to 50 friends at once.");
          return next;
        }
        next.add(userId);
      }
      return next;
    });
  }

  async function handleInviteFriends(): Promise<void> {
    if (!roomId || selectedInviteIds.size === 0) return;

    setInviteBusy(true);
    setInviteMessage("");
    try {
      const result = await inviteChatRoomMembers(roomId, Array.from(selectedInviteIds));
      const refreshedRoom = await getChatRoom(roomId);
      const membersResponse = await getChatRoomMembers(roomId);
      setRoom(refreshedRoom);
      setRoomMembers(membersResponse.items);
      setSelectedInviteIds(new Set());
      setInviteMessage(
        result.invited_user_ids.length > 0
          ? "Friends invited."
          : "Selected friends are already in this chat."
      );
    } catch (error) {
      setInviteMessage(toErrorMessage(error, "Failed to invite friends."));
    } finally {
      setInviteBusy(false);
    }
  }

  async function handleLeaveGroup(): Promise<void> {
    if (!roomId || room?.type !== "group") return;
    if (!window.confirm("Leave this group chat?")) return;

    setRoomActionBusy(true);
    try {
      await leaveChatRoom(roomId);
      navigate("/chat", { replace: true });
    } catch (error) {
      setInviteMessage(toErrorMessage(error, "Failed to leave group chat."));
    } finally {
      setRoomActionBusy(false);
    }
  }

  async function handleKickMember(userId: string): Promise<void> {
    if (!roomId || room?.type !== "group" || !canManageGroup) return;
    if (!window.confirm("Remove this participant from the group chat?")) return;

    setRoomActionBusy(true);
    try {
      await kickChatRoomMember(roomId, userId);
      const refreshedRoom = await getChatRoom(roomId);
      const membersResponse = await getChatRoomMembers(roomId);
      setRoom(refreshedRoom);
      setRoomMembers(membersResponse.items);
    } catch (error) {
      setInviteMessage(toErrorMessage(error, "Failed to remove participant."));
    } finally {
      setRoomActionBusy(false);
    }
  }

  function startEditMessage(message: ChatMessage): void {
    if (typeof message.content !== "string") return;
    setMessageActionId(null);
    setEditingMessageId(message.message_id);
    setEditingContent(message.content);
  }

  async function handleEditMessage(messageId: string): Promise<void> {
    const nextContent = editingContent.trim();
    if (!nextContent || nextContent.length > 2000) return;

    setMessageBusyId(messageId);
    try {
      await editChatMessage(messageId, nextContent);
      if (roomId) {
        await loadInitialMessages(roomId);
      }
      setEditingMessageId(null);
      setEditingContent("");
    } catch (error) {
      setErrorMessage(toErrorMessage(error, "Failed to edit message."));
    } finally {
      setMessageBusyId(null);
    }
  }

  async function handleDeleteMessage(messageId: string): Promise<void> {
    if (!window.confirm("Delete this message?")) return;

    setMessageBusyId(messageId);
    setMessageActionId(null);
    try {
      await deleteChatMessage(messageId);
      if (roomId) {
        await loadInitialMessages(roomId);
      }
    } catch (error) {
      setErrorMessage(toErrorMessage(error, "Failed to delete message."));
    } finally {
      setMessageBusyId(null);
    }
  }

  return (
    <div style={styles.page}>
      <section style={styles.phoneShell}>
        <header style={styles.header}>
          <button type="button" style={styles.iconButton} onClick={() => navigate("/chat")} aria-label="Back">
            <span aria-hidden="true">{"<"}</span>
          </button>
          <button
            type="button"
            style={styles.roomProfileButton}
            onClick={() => openUserFeed(roomFeedUserId)}
            disabled={!roomFeedUserId}
          >
            <img src={roomProfileImageUrl} alt="" style={styles.headerAvatar} />
            <span style={styles.roomName}>{roomName}</span>
          </button>
          <div style={styles.headerActions}>
            <button
              type="button"
              style={styles.iconButton}
              onClick={() => setIsSearchOpen((current) => !current)}
              aria-label="Search messages"
            >
              <span aria-hidden="true">o</span>
            </button>
            <button type="button" style={styles.iconButton} onClick={() => void openMenu()} aria-label="Menu">
              <span aria-hidden="true">=</span>
            </button>
          </div>
        </header>

        {isSearchOpen ? (
          <div style={styles.searchBar}>
            <input
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
              placeholder="Search messages"
              style={styles.searchInput}
              autoFocus
            />
            <span style={styles.searchCount}>
              {searchQuery.trim() ? `${visibleMessages.length}/${messages.length}` : `${messages.length}`}
            </span>
            <button
              type="button"
              style={styles.searchCloseButton}
              onClick={() => {
                setSearchQuery("");
                setIsSearchOpen(false);
              }}
            >
              Close
            </button>
          </div>
        ) : null}

        <main ref={messageListRef} style={styles.messageList}>
          <div style={styles.dateDivider}>
            <span style={styles.dateLine} />
            <span>Today</span>
            <span style={styles.dateLine} />
          </div>

          {errorMessage ? <div style={styles.error}>{errorMessage}</div> : null}
          {roomPageState?.isLoadingInitialMessages ? (
            <p style={styles.mutedText}>Loading messages...</p>
          ) : null}
          {roomPageState?.hasMoreOlderMessages ? (
            <button
              type="button"
              style={styles.loadOlderButton}
              onClick={() => void handleLoadOlderMessages()}
              disabled={roomPageState.isLoadingOlderMessages}
            >
              {roomPageState.isLoadingOlderMessages ? "Loading..." : "Load earlier messages"}
            </button>
          ) : null}

          {visibleMessages.map((message) => {
            if (message.type === "system") {
              return (
                <div key={message.client_msg_id || message.message_id} style={styles.systemMessageRow}>
                  <span style={styles.systemMessageBar}>
                    {renderMessageContent(message, resolveDisplayName)}
                  </span>
                  <span style={styles.systemMessageTime}>{formatTime(message.created_at)}</span>
                </div>
              );
            }

            const mine = Boolean(currentUserId && message.sender_id === currentUserId);
            const sender = getMessageSender(room, message) || (message.sender_id ? knownUsers[message.sender_id] : null);
            const senderName = mine ? "Me" : sender?.user_name || "Deleted User";
            const senderImageUrl = sender?.profile_image_url || roomProfileImageUrl;

            return (
              <div
                key={message.client_msg_id || message.message_id}
                style={{
                  ...styles.messageRow,
                  ...(mine ? styles.messageRowMine : {}),
                }}
              >
                {!mine ? (
                  <button
                    type="button"
                    style={styles.messageAvatarButton}
                    onClick={() => openUserFeed(message.sender_id)}
                    aria-label={`${senderName} feed`}
                  >
                    <img src={senderImageUrl} alt={senderName} style={styles.messageAvatar} />
                  </button>
                ) : null}
                <div style={styles.bubbleBlock}>
                  {!mine && room?.type === "group" ? (
                    <span style={styles.senderName}>{senderName}</span>
                  ) : null}
                  <div
                    style={{
                      ...styles.bubble,
                      ...(mine ? styles.bubbleMine : {}),
                      ...(message.deleted_at ? styles.deletedBubble : {}),
                    }}
                  >
                    {editingMessageId === message.message_id ? (
                      <div style={styles.editBox}>
                        <textarea
                          value={editingContent}
                          onChange={(event) => setEditingContent(event.target.value)}
                          maxLength={2000}
                          style={styles.editTextarea}
                        />
                        <div style={styles.editActions}>
                          <button
                            type="button"
                            style={styles.editActionButton}
                            onClick={() => void handleEditMessage(message.message_id)}
                            disabled={messageBusyId === message.message_id}
                          >
                            Save
                          </button>
                          <button
                            type="button"
                            style={styles.editActionButton}
                            onClick={() => {
                              setEditingMessageId(null);
                              setEditingContent("");
                            }}
                          >
                            Cancel
                          </button>
                        </div>
                      </div>
                    ) : (
                      renderMessageContent(message, resolveDisplayName)
                    )}
                  </div>
                  {mine && canShowMessageActions(message, currentUserId) ? (
                    <div style={styles.messageActions}>
                      <button
                        type="button"
                        style={styles.messageActionButton}
                        onClick={() =>
                          setMessageActionId((current) =>
                            current === message.message_id ? null : message.message_id
                          )
                        }
                      >
                        More
                      </button>
                      {messageActionId === message.message_id ? (
                        <div style={styles.messageActionMenu}>
                          <button
                            type="button"
                            style={styles.messageActionMenuButton}
                            onClick={() => startEditMessage(message)}
                            disabled={!canEditMessage(message, currentUserId)}
                          >
                            Edit
                          </button>
                          <button
                            type="button"
                            style={styles.messageActionMenuDanger}
                            onClick={() => void handleDeleteMessage(message.message_id)}
                            disabled={
                              messageBusyId === message.message_id ||
                              !canDeleteMessage(message, currentUserId)
                            }
                          >
                            Delete
                          </button>
                        </div>
                      ) : null}
                    </div>
                  ) : null}
                </div>
                <span style={styles.time}>
                  {formatTime(message.created_at)}
                  {message.status === "sending" ? " sending" : ""}
                  {message.status === "failed" ? " failed" : ""}
                  {message.edited_at && !message.deleted_at ? " edited" : ""}
                </span>
              </div>
            );
          })}
          <div ref={bottomRef} />
        </main>

        <footer style={styles.composer}>
          <button type="button" style={styles.plusButton} aria-label="Add attachment">
            +
          </button>
          <input
            value={input}
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.nativeEvent.isComposing) return;
              if (event.key === "Enter") void handleSend();
            }}
            maxLength={2000}
            placeholder="Type a message"
            style={styles.input}
          />
          <button
            type="button"
            style={{
              ...styles.sendButton,
              ...(!input.trim() || connectionState === "closed" ? styles.sendButtonDisabled : {}),
            }}
            onClick={() => void handleSend()}
            disabled={!input.trim() || connectionState === "closed"}
            aria-label="Send message"
          >
            <span aria-hidden="true">{"^"}</span>
          </button>
        </footer>
      </section>

      {isMenuOpen ? (
        <aside style={styles.menuBackdrop}>
          <button type="button" style={styles.menuScrim} onClick={closeMenu} aria-label="Close chat menu" />
          <section style={styles.menuPanel}>
            <header style={styles.menuHeader}>
              <div>
                <p style={styles.menuEyebrow}>Chat Room</p>
                <h2 style={styles.menuTitle}>Participants</h2>
              </div>
              <button type="button" style={styles.menuCloseButton} onClick={closeMenu}>
                Close
              </button>
            </header>

            <div style={styles.memberList}>
              {participants.map((participant) => (
                <div
                  key={participant.user_id || participant.user_name}
                  style={styles.memberRow}
                >
                  <button
                    type="button"
                    style={styles.memberProfileButton}
                    onClick={() => openUserFeed(participant.user_id)}
                    disabled={!participant.user_id || participant.user_id === currentUserId}
                  >
                    <img
                      src={participant.profile_image_url || DEFAULT_PROFILE_IMAGE_URL}
                      alt={participant.user_name || "Participant"}
                      style={styles.memberAvatar}
                    />
                    <span style={styles.memberName}>
                      {participant.user_name || "Deleted User"}
                      {participant.user_id === currentUserId ? " (You)" : ""}
                    </span>
                  </button>
                  {canManageGroup && participant.user_id && participant.user_id !== currentUserId ? (
                    <button
                      type="button"
                      style={styles.kickButton}
                      onClick={() => void handleKickMember(participant.user_id as string)}
                      disabled={roomActionBusy}
                    >
                      Kick
                    </button>
                  ) : null}
                </div>
              ))}
            </div>

            {room?.type === "group" ? (
            <div style={styles.inviteSection}>
              <button
                type="button"
                style={styles.leaveButton}
                onClick={() => void handleLeaveGroup()}
                disabled={roomActionBusy}
              >
                Leave Group
              </button>
              <h3 style={styles.inviteTitle}>Add Chatters</h3>
              <p style={styles.inviteCopy}>Only friends can be invited.</p>
              {inviteMessage ? <p style={styles.inviteMessage}>{inviteMessage}</p> : null}

              {friendsLoading ? (
                <p style={styles.mutedText}>Loading friends...</p>
              ) : invitableFriends.length > 0 ? (
                <div style={styles.friendInviteList}>
                  {invitableFriends.map((friend) => {
                    const selected = selectedInviteIds.has(friend.peer.user_id);
                    return (
                      <button
                        key={friend.friendship_id}
                        type="button"
                        style={{
                          ...styles.friendInviteRow,
                          ...(selected ? styles.friendInviteRowSelected : {}),
                        }}
                        onClick={() => toggleInviteFriend(friend.peer.user_id)}
                      >
                        <img
                          src={friend.peer.profile_image_url || DEFAULT_PROFILE_IMAGE_URL}
                          alt={friend.peer.user_name}
                          style={styles.memberAvatar}
                        />
                        <span style={styles.memberName}>{friend.peer.user_name}</span>
                        <span style={selected ? styles.checkedCircle : styles.emptyCircle}>
                          {selected ? "✓" : ""}
                        </span>
                      </button>
                    );
                  })}
                </div>
              ) : (
                <p style={styles.mutedText}>No friends available to invite.</p>
              )}

              <button
                type="button"
                style={{
                  ...styles.inviteButton,
                  ...(selectedInviteIds.size === 0 || inviteBusy ? styles.inviteButtonDisabled : {}),
                }}
                onClick={() => void handleInviteFriends()}
                disabled={selectedInviteIds.size === 0 || inviteBusy}
              >
                {inviteBusy ? "Inviting..." : "Invite Selected"}
              </button>
            </div>
            ) : (
              <p style={styles.inviteCopy}>Direct chats are limited to two participants.</p>
            )}
          </section>
        </aside>
      ) : null}

      {feedPopupUserId ? (
        <FeedPopup
          key={feedPopupUserId}
          userId={feedPopupUserId}
          onClose={() => setFeedPopupUserId(null)}
        />
      ) : null}
    </div>
  );
}

function getLastServerSeq(messages: ChatMessage[]): number {
  return messages.reduce(
    (maxSeq, message) =>
      message.server_seq === Number.MAX_SAFE_INTEGER
        ? maxSeq
        : Math.max(maxSeq, message.server_seq),
    0
  );
}

function isNearBottom(scroller: HTMLElement | null): boolean {
  if (!scroller) return true;
  return scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight <= BOTTOM_THRESHOLD_PX;
}

function getRoomParticipants(
  room: ChatRoom | null,
  draftPeer: FriendPeer | null,
  groupDraft: GroupDraft | null,
  currentUserId: string | null,
  roomMembers: ChatRoomMember[]
): ChatPeer[] {
  const currentPeer: ChatPeer | null = currentUserId
    ? { user_id: currentUserId, user_name: "You", profile_image_url: null }
    : null;

  if (!room) {
    if (groupDraft) {
      return [currentPeer, ...groupDraft.members].filter(Boolean) as ChatPeer[];
    }
    return [currentPeer, draftPeer].filter(Boolean) as ChatPeer[];
  }

  if (room.type === "direct") {
    return [currentPeer, room.peer].filter(Boolean) as ChatPeer[];
  }
  return roomMembers.length > 0 ? roomMembers : room.members ?? [];
}

function readGroupDraft(draftId: string): GroupDraft | null {
  try {
    const raw = window.sessionStorage.getItem(`krip-chat-group-draft:${draftId}`);
    const parsed = raw ? (JSON.parse(raw) as Partial<GroupDraft>) : null;
    if (!parsed || !Array.isArray(parsed.memberIds) || parsed.memberIds.length === 0) {
      return null;
    }

    return {
      draftId,
      title: typeof parsed.title === "string" && parsed.title.trim() ? parsed.title : "Group Chat",
      memberIds: parsed.memberIds.filter((id): id is string => typeof id === "string"),
      members: Array.isArray(parsed.members)
        ? parsed.members.filter((member): member is FriendPeer =>
            Boolean(member && typeof member.user_id === "string" && typeof member.user_name === "string")
          )
        : [],
    };
  } catch {
    return null;
  }
}

function getMessageSender(room: ChatRoom | null, message: ChatMessage): ChatRoomMember | null {
  if (!message.sender_id) return null;
  if (room?.type === "direct" && room.peer?.user_id === message.sender_id) {
    return {
      user_id: room.peer.user_id,
      user_name: room.peer.user_name,
      profile_image_url: room.peer.profile_image_url,
    };
  }
  return room?.members?.find((member) => member.user_id === message.sender_id) ?? null;
}

function canShowMessageActions(message: ChatMessage, currentUserId: string | null): boolean {
  return canEditMessage(message, currentUserId) || canDeleteMessage(message, currentUserId);
}

function canEditMessage(message: ChatMessage, currentUserId: string | null): boolean {
  return isOwnTextMessage(message, currentUserId) && isWithinFiveMinutes(message.created_at);
}

function canDeleteMessage(message: ChatMessage, currentUserId: string | null): boolean {
  return isOwnTextMessage(message, currentUserId) && isWithinFiveMinutes(message.created_at);
}

function isOwnTextMessage(message: ChatMessage, currentUserId: string | null): boolean {
  return Boolean(
    currentUserId &&
      message.sender_id === currentUserId &&
      message.type === "text" &&
      !message.deleted_at &&
      typeof message.content === "string" &&
      message.server_seq !== Number.MAX_SAFE_INTEGER
  );
}

function isWithinFiveMinutes(value: string): boolean {
  const createdAt = new Date(value).getTime();
  if (!Number.isFinite(createdAt)) return false;

  return Date.now() - createdAt <= 5 * 60 * 1000;
}

function getCreatorId(messages: ChatMessage[]): string | null {
  const createdMessage = messages.find((message) => {
    if (message.type !== "system" || !message.content || typeof message.content !== "object") {
      return false;
    }
    return (message.content as { action?: string }).action === "created";
  });

  if (!createdMessage?.content || typeof createdMessage.content !== "object") return null;
  const actorId = (createdMessage.content as { actor_id?: unknown }).actor_id;
  return typeof actorId === "string" ? actorId : null;
}

function getMessageUserIds(messages: ChatMessage[]): Set<string> {
  const userIds = new Set<string>();

  messages.forEach((message) => {
    if (message.sender_id) userIds.add(message.sender_id);
    if (message.type !== "system" || !message.content || typeof message.content !== "object") {
      return;
    }

    const content = message.content as { actor_id?: unknown; target_ids?: unknown };
    if (typeof content.actor_id === "string") userIds.add(content.actor_id);
    if (Array.isArray(content.target_ids)) {
      content.target_ids.forEach((targetId) => {
        if (typeof targetId === "string") userIds.add(targetId);
      });
    }
  });

  return userIds;
}

function renderMessageContent(
  message: ChatMessage,
  resolveDisplayName: (userId: string | null) => string
): string {
  if (message.deleted_at) return "Deleted message.";
  if (message.type === "system") return renderSystemMessage(message.content, resolveDisplayName);
  if (typeof message.content === "string") return message.content;
  return "";
}

function renderSystemMessage(
  content: unknown,
  resolveDisplayName: (userId: string | null) => string
): string {
  if (!content || typeof content !== "object") return "System message";

  const value = content as { action?: string; actor_id?: string | null; target_ids?: string[] };
  const actorName = resolveDisplayName(value.actor_id ?? null);
  const targetNames = Array.isArray(value.target_ids)
    ? value.target_ids.map(resolveDisplayName).join(", ")
    : "";

  if (value.action === "created") return `${actorName} created the chat room.`;
  if (value.action === "join") return `${actorName} invited ${targetNames || "members"}.`;
  if (value.action === "leave") return `${actorName} left.`;
  if (value.action === "kick") return `${actorName} removed ${targetNames || "members"}.`;
  return "System message";
}

function formatTime(value: string): string {
  if (!value) return "";
  return new Date(value).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });
}

function toErrorMessage(error: unknown, fallback: string): string {
  const apiError = error as {
    response?: { data?: { detail?: string; message?: string } };
    message?: string;
  };
  return apiError.response?.data?.detail || apiError.response?.data?.message || apiError.message || fallback;
}

const styles: Record<string, CSSProperties> = {
  page: {
    height: "100dvh",
    overflow: "hidden",
    padding: "18px 12px",
    display: "flex",
    justifyContent: "center",
    background: "linear-gradient(90deg, rgba(249,222,222,0.6), rgba(255,255,255,0.72))",
    fontFamily: "'Nunito', 'Apple SD Gothic Neo', sans-serif",
  },
  phoneShell: {
    width: "100%",
    maxWidth: 430,
    height: "calc(100dvh - 36px)",
    display: "flex",
    flexDirection: "column",
    overflow: "hidden",
    borderRadius: 34,
    background: "#ffffff",
    boxShadow: "0 24px 70px rgba(25,28,32,0.18)",
    border: "1px solid rgba(255,255,255,0.86)",
  },
  header: {
    minHeight: 76,
    flexShrink: 0,
    display: "grid",
    gridTemplateColumns: "44px minmax(0, 1fr) 92px",
    alignItems: "center",
    gap: 8,
    padding: "12px 14px",
    borderBottom: "1px solid #eeeeee",
    background: "#ffffff",
  },
  headerActions: {
    display: "flex",
    justifyContent: "flex-end",
    gap: 4,
  },
  iconButton: {
    width: 40,
    height: 40,
    border: "none",
    borderRadius: "50%",
    display: "grid",
    placeItems: "center",
    background: "transparent",
    color: "#6f7479",
    fontSize: "1.55rem",
    fontWeight: 900,
    cursor: "pointer",
  },
  roomProfileButton: {
    minWidth: 0,
    border: "none",
    background: "transparent",
    color: "#242424",
    fontWeight: 900,
    cursor: "pointer",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
  },
  headerAvatar: {
    width: 30,
    height: 30,
    borderRadius: "50%",
    objectFit: "cover",
  },
  roomName: {
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
    fontSize: "1rem",
  },
  searchBar: {
    flexShrink: 0,
    display: "grid",
    gridTemplateColumns: "minmax(0, 1fr) auto auto",
    alignItems: "center",
    gap: 8,
    padding: "10px 14px",
    borderBottom: "1px solid #eeeeee",
    background: "#ffffff",
  },
  searchInput: {
    minHeight: 36,
    border: "none",
    borderRadius: 999,
    padding: "0 14px",
    background: "#f4f4f4",
    color: "#242424",
    outline: "none",
    fontWeight: 700,
  },
  searchCount: {
    color: "#8a8f94",
    fontSize: "0.78rem",
    fontWeight: 800,
    whiteSpace: "nowrap",
  },
  searchCloseButton: {
    border: "none",
    borderRadius: 999,
    padding: "8px 10px",
    background: "#eef0f2",
    color: "#555",
    fontSize: "0.78rem",
    fontWeight: 900,
    cursor: "pointer",
  },
  messageList: {
    minHeight: 0,
    flex: 1,
    display: "flex",
    flexDirection: "column",
    gap: 14,
    padding: "0 16px 18px",
    overflowY: "auto",
    background: "#ffffff",
  },
  dateDivider: {
    display: "grid",
    gridTemplateColumns: "1fr auto 1fr",
    alignItems: "center",
    gap: 12,
    padding: "0 0 6px",
    color: "#d1d5db",
    fontSize: "0.72rem",
    fontWeight: 800,
  },
  dateLine: {
    height: 1,
    background: "#eeeeee",
  },
  error: {
    padding: "12px 14px",
    borderRadius: 16,
    background: "rgba(220,38,38,0.1)",
    color: "#b91c1c",
    fontWeight: 800,
  },
  mutedText: {
    margin: 0,
    color: "#8a8f94",
    lineHeight: 1.5,
  },
  loadOlderButton: {
    alignSelf: "center",
    border: "1px solid rgba(5,181,187,0.18)",
    borderRadius: 999,
    padding: "9px 14px",
    background: "#ffffff",
    color: "#078f94",
    fontWeight: 800,
    cursor: "pointer",
  },
  systemMessageRow: {
    alignSelf: "stretch",
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    gap: 4,
    padding: "2px 0",
  },
  systemMessageBar: {
    maxWidth: "100%",
    borderRadius: 999,
    padding: "8px 12px",
    background: "#f2f4f5",
    color: "#7a8087",
    fontSize: "0.76rem",
    fontWeight: 800,
    lineHeight: 1.35,
    textAlign: "center",
    overflowWrap: "anywhere",
  },
  systemMessageTime: {
    color: "#c0c5ca",
    fontSize: "0.66rem",
    fontWeight: 800,
  },
  messageRow: {
    display: "flex",
    alignItems: "flex-end",
    gap: 8,
  },
  messageRowMine: {
    flexDirection: "row-reverse",
  },
  messageAvatarButton: {
    width: 38,
    height: 38,
    padding: 0,
    border: "none",
    borderRadius: "50%",
    background: "transparent",
    cursor: "pointer",
    flexShrink: 0,
  },
  messageAvatar: {
    width: "100%",
    height: "100%",
    borderRadius: "50%",
    objectFit: "cover",
    background: "#9ae5e7",
  },
  bubbleBlock: {
    maxWidth: "72%",
    display: "flex",
    flexDirection: "column",
    gap: 4,
  },
  senderName: {
    color: "#8a8f94",
    fontSize: "0.72rem",
    fontWeight: 800,
  },
  bubble: {
    padding: "12px 16px",
    borderRadius: "18px 18px 18px 6px",
    background: "#f3f3f3",
    color: "#222222",
    overflowWrap: "anywhere",
    whiteSpace: "pre-wrap",
    wordBreak: "break-word",
    lineHeight: 1.45,
  },
  bubbleMine: {
    borderRadius: "18px 18px 6px 18px",
    background: "#08bfc4",
    color: "#ffffff",
  },
  deletedBubble: {
    opacity: 0.62,
    fontStyle: "italic",
  },
  time: {
    color: "#b6bbc1",
    fontSize: "0.68rem",
    whiteSpace: "nowrap",
    paddingBottom: 2,
  },
  composer: {
    flexShrink: 0,
    display: "grid",
    gridTemplateColumns: "34px minmax(0, 1fr) 34px",
    alignItems: "center",
    gap: 8,
    padding: "10px 14px 16px",
    borderTop: "1px solid #eeeeee",
    background: "#ffffff",
  },
  plusButton: {
    width: 34,
    height: 34,
    border: "none",
    borderRadius: "50%",
    background: "#f1f1f1",
    color: "#a3a7ab",
    fontSize: "1.4rem",
    lineHeight: 1,
    cursor: "pointer",
  },
  input: {
    minHeight: 38,
    border: "none",
    borderRadius: 999,
    padding: "0 16px",
    outline: "none",
    color: "#242424",
    background: "#f4f4f4",
    fontWeight: 700,
  },
  sendButton: {
    width: 34,
    height: 34,
    border: "none",
    borderRadius: "50%",
    background: "#eef0f2",
    color: "#9aa1aa",
    fontWeight: 900,
    cursor: "pointer",
  },
  sendButtonDisabled: {
    opacity: 0.55,
    cursor: "not-allowed",
  },
  menuBackdrop: {
    position: "fixed",
    inset: 0,
    zIndex: 80,
  },
  menuScrim: {
    position: "absolute",
    inset: 0,
    border: "none",
    background: "rgba(24,26,32,0.36)",
    cursor: "pointer",
  },
  menuPanel: {
    position: "absolute",
    top: 0,
    right: 0,
    width: "min(86vw, 360px)",
    height: "100%",
    display: "flex",
    flexDirection: "column",
    gap: 16,
    padding: 18,
    background: "#ffffff",
    boxShadow: "-20px 0 50px rgba(24,26,32,0.18)",
    overflowY: "auto",
  },
  menuHeader: {
    display: "flex",
    alignItems: "flex-start",
    justifyContent: "space-between",
    gap: 12,
  },
  menuEyebrow: {
    margin: 0,
    color: "#078f94",
    fontSize: "0.72rem",
    fontWeight: 900,
    textTransform: "uppercase",
    letterSpacing: "0.12em",
  },
  menuTitle: {
    margin: "5px 0 0",
    color: "#242424",
    fontSize: "1.25rem",
  },
  menuCloseButton: {
    border: "1px solid rgba(5,181,187,0.16)",
    borderRadius: 999,
    padding: "9px 12px",
    background: "#ffffff",
    color: "#444",
    fontWeight: 800,
    cursor: "pointer",
  },
  memberList: {
    display: "flex",
    flexDirection: "column",
    gap: 8,
  },
  memberRow: {
    width: "100%",
    minHeight: 54,
    display: "flex",
    alignItems: "center",
    gap: 10,
    border: "1px solid #eeeeee",
    borderRadius: 16,
    padding: "8px 10px",
    background: "#ffffff",
    color: "#242424",
    textAlign: "left",
    cursor: "pointer",
  },
  memberProfileButton: {
    minWidth: 0,
    flex: 1,
    display: "flex",
    alignItems: "center",
    gap: 10,
    border: "none",
    background: "transparent",
    padding: 0,
    textAlign: "left",
    cursor: "pointer",
  },
  memberAvatar: {
    width: 36,
    height: 36,
    borderRadius: "50%",
    objectFit: "cover",
    background: "#eef0f2",
    flexShrink: 0,
  },
  memberName: {
    minWidth: 0,
    flex: 1,
    color: "#242424",
    fontWeight: 800,
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  inviteSection: {
    display: "flex",
    flexDirection: "column",
    gap: 10,
    paddingTop: 8,
    borderTop: "1px solid #eeeeee",
  },
  leaveButton: {
    minHeight: 42,
    border: "1px solid rgba(220,38,38,0.18)",
    borderRadius: 14,
    background: "rgba(220,38,38,0.08)",
    color: "#dc2626",
    fontWeight: 900,
    cursor: "pointer",
  },
  kickButton: {
    border: "1px solid rgba(220,38,38,0.18)",
    borderRadius: 999,
    padding: "7px 10px",
    background: "#ffffff",
    color: "#dc2626",
    fontSize: "0.75rem",
    fontWeight: 900,
    cursor: "pointer",
  },
  inviteTitle: {
    margin: 0,
    color: "#242424",
    fontSize: "1rem",
  },
  inviteCopy: {
    margin: 0,
    color: "#777",
    fontSize: "0.82rem",
    fontWeight: 700,
  },
  inviteMessage: {
    margin: 0,
    padding: "9px 10px",
    borderRadius: 12,
    background: "rgba(5,181,187,0.1)",
    color: "#078f94",
    fontSize: "0.82rem",
    fontWeight: 800,
  },
  friendInviteList: {
    display: "flex",
    flexDirection: "column",
    gap: 8,
  },
  friendInviteRow: {
    width: "100%",
    minHeight: 54,
    display: "flex",
    alignItems: "center",
    gap: 10,
    border: "1px solid #eeeeee",
    borderRadius: 16,
    padding: "8px 10px",
    background: "#ffffff",
    textAlign: "left",
    cursor: "pointer",
  },
  friendInviteRowSelected: {
    borderColor: "rgba(5,181,187,0.34)",
    background: "rgba(228,247,247,0.7)",
  },
  emptyCircle: {
    width: 22,
    height: 22,
    borderRadius: "50%",
    border: "2px solid rgba(5,181,187,0.2)",
    flexShrink: 0,
  },
  checkedCircle: {
    width: 22,
    height: 22,
    borderRadius: "50%",
    display: "grid",
    placeItems: "center",
    background: "#08bfc4",
    color: "#ffffff",
    fontSize: "0.72rem",
    fontWeight: 900,
    flexShrink: 0,
  },
  inviteButton: {
    minHeight: 44,
    border: "none",
    borderRadius: 16,
    background: "#08bfc4",
    color: "#ffffff",
    fontWeight: 900,
    cursor: "pointer",
  },
  inviteButtonDisabled: {
    opacity: 0.48,
    cursor: "not-allowed",
  },
  messageActions: {
    position: "relative",
    alignSelf: "flex-end",
    marginTop: 4,
  },
  messageActionButton: {
    border: "none",
    borderRadius: 999,
    padding: "4px 8px",
    background: "rgba(238,240,242,0.9)",
    color: "#667",
    fontSize: "0.68rem",
    fontWeight: 900,
    cursor: "pointer",
  },
  messageActionMenu: {
    position: "absolute",
    right: 0,
    top: 26,
    zIndex: 5,
    display: "flex",
    flexDirection: "column",
    minWidth: 96,
    overflow: "hidden",
    border: "1px solid #eeeeee",
    borderRadius: 12,
    background: "#ffffff",
    boxShadow: "0 12px 28px rgba(24,26,32,0.14)",
  },
  messageActionMenuButton: {
    border: "none",
    background: "transparent",
    padding: "9px 11px",
    color: "#242424",
    fontWeight: 800,
    textAlign: "left",
    cursor: "pointer",
  },
  messageActionMenuDanger: {
    border: "none",
    background: "transparent",
    padding: "9px 11px",
    color: "#dc2626",
    fontWeight: 800,
    textAlign: "left",
    cursor: "pointer",
  },
  editBox: {
    display: "flex",
    flexDirection: "column",
    gap: 8,
  },
  editTextarea: {
    width: "100%",
    minHeight: 72,
    border: "1px solid rgba(5,181,187,0.22)",
    borderRadius: 12,
    padding: 10,
    resize: "vertical",
    outline: "none",
    color: "#242424",
    background: "#ffffff",
  },
  editActions: {
    display: "flex",
    gap: 6,
  },
  editActionButton: {
    border: "none",
    borderRadius: 999,
    padding: "7px 10px",
    background: "#eef0f2",
    color: "#242424",
    fontSize: "0.76rem",
    fontWeight: 900,
    cursor: "pointer",
  },
};
