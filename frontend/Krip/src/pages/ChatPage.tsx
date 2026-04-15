import type { CSSProperties } from "react";
import { useState } from "react";

export default function ChatPage() {
  const [tab, setTab] = useState<"chat" | "request">("chat");

  return (
    <div style={styles.page}>
      <div style={styles.header}>
        <p style={styles.eyebrow}>Conversation</p>
        <h1 style={styles.title}>Chat</h1>
      </div>

      <div style={styles.segment}>
        <button
          type="button"
          onClick={() => setTab("chat")}
          style={{ ...styles.segmentButton, ...(tab === "chat" ? styles.segmentButtonActive : {}) }}
        >
          Chats
        </button>
        <button
          type="button"
          onClick={() => setTab("request")}
          style={{ ...styles.segmentButton, ...(tab === "request" ? styles.segmentButtonActive : {}) }}
        >
          Requests
        </button>
      </div>

      {tab === "chat" ? (
        <div style={styles.list}>
          <div style={styles.emptyCard}>
            <p style={styles.emptyTitle}>No chats yet</p>
            <p style={styles.emptyCopy}>Your recent conversations will appear here once chat data is connected.</p>
          </div>
        </div>
      ) : (
        <div style={styles.emptyCard}>
          <p style={styles.emptyTitle}>No friend requests yet</p>
          <p style={styles.emptyCopy}>Incoming requests will show up here once the requests API is connected.</p>
        </div>
      )}
    </div>
  );
}

const styles: Record<string, CSSProperties> = {
  page: {
    minHeight: "100dvh",
    padding: "24px 16px 0",
    background: "#ffffff",
    fontFamily: "'Nunito', 'Apple SD Gothic Neo', sans-serif",
  },
  header: {
    maxWidth: 720,
    margin: "0 auto 14px",
  },
  eyebrow: {
    margin: 0,
    color: "#8a8a8a",
    fontSize: "0.78rem",
    fontWeight: 800,
    letterSpacing: "0.12em",
    textTransform: "uppercase",
  },
  title: {
    margin: "8px 0 0",
    color: "#222222",
    fontSize: "2rem",
  },
  segment: {
    maxWidth: 720,
    margin: "0 auto 14px",
    padding: 6,
    borderRadius: 18,
    background: "#f7f7f7",
    display: "grid",
    gridTemplateColumns: "1fr 1fr",
    gap: 6,
    border: "1px solid #ececec",
  },
  segmentButton: {
    border: "1px solid transparent",
    borderRadius: 14,
    minHeight: 44,
    background: "transparent",
    color: "#777777",
    fontWeight: 800,
    cursor: "pointer",
  },
  segmentButtonActive: {
    background: "#d9d9d9",
    color: "#222222",
  },
  list: {
    maxWidth: 720,
    margin: "0 auto",
    display: "flex",
    flexDirection: "column",
    gap: 12,
  },
  emptyCard: {
    maxWidth: 720,
    margin: "0 auto",
    padding: 22,
    borderRadius: 24,
    background: "#f7f7f7",
    border: "1px solid #ececec",
  },
  emptyTitle: {
    margin: 0,
    color: "#333333",
    fontWeight: 800,
  },
  emptyCopy: {
    margin: "8px 0 0",
    color: "#777777",
    lineHeight: 1.55,
  },
};
