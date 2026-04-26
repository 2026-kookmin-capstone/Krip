import type { CSSProperties } from "react";
import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

interface Message {
  id: number;
  text: string;
  mine: boolean;
  time: string;
}

const MOCK_MESSAGES: Message[] = [
  { id: 1, text: "Can I join your route?", mine: false, time: "10:00" },
  { id: 2, text: "Sure, let's plan it together.", mine: true, time: "10:01" },
];

export default function ChatRoomPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const bottomRef = useRef<HTMLDivElement>(null);
  const [messages, setMessages] = useState<Message[]>(MOCK_MESSAGES);
  const [input, setInput] = useState("");

  // Until the chat API is connected, use the route id as a stable room label.
  const roomName = id ? `Friend ${id.slice(0, 8)}` : "Chat";

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  function handleSend(): void {
    const text = input.trim();
    if (!text) return;

    const now = new Date();
    const time = `${now.getHours()}:${String(now.getMinutes()).padStart(2, "0")}`;
    setMessages((current) => [...current, { id: Date.now(), text, mine: true, time }]);
    setInput("");
  }

  return (
    <div style={styles.page}>
      <header style={styles.header}>
        <button type="button" style={styles.backButton} onClick={() => navigate("/chat")}>
          Back
        </button>
        <div style={styles.avatar}>{roomName.slice(0, 1).toUpperCase()}</div>
        <strong style={styles.roomName}>{roomName}</strong>
      </header>

      <main style={styles.messageList}>
        {messages.map((message) => (
          <div
            key={message.id}
            style={{
              ...styles.messageRow,
              ...(message.mine ? styles.messageRowMine : {}),
            }}
          >
            <div
              style={{
                ...styles.bubble,
                ...(message.mine ? styles.bubbleMine : {}),
              }}
            >
              {message.text}
            </div>
            <span style={styles.time}>{message.time}</span>
          </div>
        ))}
        <div ref={bottomRef} />
      </main>

      <footer style={styles.composer}>
        <input
          value={input}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") handleSend();
          }}
          placeholder="Write a message"
          style={styles.input}
        />
        <button
          type="button"
          style={{
            ...styles.sendButton,
            ...(!input.trim() ? styles.sendButtonDisabled : {}),
          }}
          onClick={handleSend}
          disabled={!input.trim()}
        >
          Send
        </button>
      </footer>
    </div>
  );
}

const styles: Record<string, CSSProperties> = {
  page: {
    minHeight: "100dvh",
    display: "flex",
    flexDirection: "column",
    background: "transparent",
    fontFamily: "'Nunito', 'Apple SD Gothic Neo', sans-serif",
  },
  header: {
    position: "sticky",
    top: 0,
    zIndex: 5,
    display: "flex",
    alignItems: "center",
    gap: 12,
    padding: "14px 16px",
    background: "rgba(255,255,255,0.94)",
    borderBottom: "1px solid var(--border-soft)",
    backdropFilter: "blur(14px)",
  },
  backButton: {
    border: "1px solid rgba(5,181,187,0.18)",
    borderRadius: 14,
    padding: "9px 12px",
    background: "#ffffff",
    color: "var(--text-secondary)",
    fontWeight: 800,
    cursor: "pointer",
  },
  avatar: {
    width: 36,
    height: 36,
    borderRadius: "50%",
    display: "grid",
    placeItems: "center",
    background: "var(--brand-primary-soft)",
    color: "var(--brand-primary-deep)",
    fontWeight: 900,
  },
  roomName: {
    color: "var(--text-primary)",
  },
  messageList: {
    flex: 1,
    display: "flex",
    flexDirection: "column",
    gap: 12,
    padding: "18px 16px 110px",
  },
  messageRow: {
    display: "flex",
    alignItems: "flex-end",
    gap: 8,
  },
  messageRowMine: {
    flexDirection: "row-reverse",
  },
  bubble: {
    maxWidth: "min(72%, 420px)",
    padding: "11px 14px",
    borderRadius: "18px 18px 18px 6px",
    background: "#ffffff",
    color: "var(--text-secondary)",
    boxShadow: "var(--shadow-soft)",
  },
  bubbleMine: {
    borderRadius: "18px 18px 6px 18px",
    background: "linear-gradient(135deg, var(--brand-primary), #12c0c6)",
    color: "#ffffff",
  },
  time: {
    color: "var(--neutral-500)",
    fontSize: "0.72rem",
  },
  composer: {
    position: "fixed",
    left: 0,
    right: 0,
    bottom: 0,
    zIndex: 20,
    display: "grid",
    gridTemplateColumns: "1fr auto",
    gap: 10,
    padding: "12px 16px",
    background: "rgba(255,255,255,0.96)",
    borderTop: "1px solid var(--border-soft)",
  },
  input: {
    minHeight: 44,
    border: "1px solid rgba(5,181,187,0.16)",
    borderRadius: 999,
    padding: "0 16px",
    outline: "none",
    color: "var(--text-primary)",
  },
  sendButton: {
    border: "none",
    borderRadius: 999,
    padding: "0 18px",
    background: "var(--brand-primary)",
    color: "#ffffff",
    fontWeight: 900,
    cursor: "pointer",
  },
  sendButtonDisabled: {
    opacity: 0.5,
    cursor: "not-allowed",
  },
};
