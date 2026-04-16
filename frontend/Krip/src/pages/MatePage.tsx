import type { CSSProperties } from "react";

export default function MatePage() {
  return (
    <div style={styles.page}>
      <div style={styles.header}>
        <p style={styles.eyebrow}>Trip Mate</p>
        <h1 style={styles.title}>Travel Mate</h1>
      </div>

      <section style={styles.searchCard}>
        <input style={styles.searchInput} placeholder="Search by location, date, or keyword" />
        <button type="button" style={styles.searchButton}>Search</button>
      </section>

      <div style={styles.filterRow}>
        {["All", "Solo", "Friends", "Couple", "Family"].map((label, index) => (
          <button
            key={label}
            type="button"
            style={{
              ...styles.filterChip,
              ...(index === 0 ? styles.filterChipActive : {}),
            }}
          >
            {label}
          </button>
        ))}
      </div>

      <section style={styles.feed}>
        <div style={styles.emptyCard}>
          <p style={styles.emptyTitle}>No mate posts yet</p>
          <p style={styles.emptyCopy}>Travel mate posts will appear here once the API is connected.</p>
        </div>
      </section>

      <button type="button" style={styles.fab}>Write Post</button>
    </div>
  );
}

const styles: Record<string, CSSProperties> = {
  page: {
    minHeight: "100dvh",
    padding: "24px 16px 0",
    background: "transparent",
    fontFamily: "'Nunito', 'Apple SD Gothic Neo', sans-serif",
    position: "relative",
  },
  header: {
    maxWidth: 720,
    margin: "0 auto 16px",
  },
  eyebrow: {
    margin: 0,
    color: "var(--brand-primary-deep)",
    fontSize: "0.78rem",
    fontWeight: 800,
    letterSpacing: "0.12em",
    textTransform: "uppercase",
  },
  title: {
    margin: "8px 0 0",
    color: "var(--text-primary)",
    fontSize: "2rem",
  },
  searchCard: {
    maxWidth: 720,
    margin: "0 auto 14px",
    padding: 10,
    borderRadius: 22,
    background: "rgba(255,255,255,0.86)",
    display: "grid",
    gridTemplateColumns: "1fr auto",
    gap: 10,
    border: "1px solid var(--border-soft)",
    boxShadow: "var(--shadow-soft)",
  },
  searchInput: {
    border: "1px solid rgba(5,181,187,0.18)",
    outline: "none",
    background: "var(--surface-panel)",
    borderRadius: 16,
    padding: "0 14px",
    minHeight: 48,
    color: "var(--text-primary)",
  },
  searchButton: {
    border: "1px solid rgba(5,181,187,0.22)",
    borderRadius: 16,
    padding: "0 16px",
    background: "linear-gradient(135deg, var(--brand-primary), #12c0c6)",
    color: "#ffffff",
    fontWeight: 800,
    cursor: "pointer",
  },
  filterRow: {
    maxWidth: 720,
    margin: "0 auto 14px",
    display: "flex",
    flexWrap: "wrap",
    gap: 8,
  },
  filterChip: {
    border: "1px solid rgba(5,181,187,0.16)",
    borderRadius: 999,
    padding: "10px 14px",
    background: "rgba(255,255,255,0.82)",
    color: "var(--neutral-700)",
    fontWeight: 700,
    cursor: "pointer",
  },
  filterChipActive: {
    background: "linear-gradient(135deg, rgba(5,181,187,0.18), rgba(228,247,247,0.96))",
    color: "var(--text-primary)",
  },
  feed: {
    maxWidth: 720,
    margin: "0 auto",
    display: "flex",
    flexDirection: "column",
    gap: 12,
  },
  emptyCard: {
    padding: 22,
    borderRadius: 24,
    background: "rgba(255,255,255,0.88)",
    border: "1px solid var(--border-soft)",
    boxShadow: "var(--shadow-soft)",
  },
  emptyTitle: {
    margin: 0,
    color: "var(--text-primary)",
    fontWeight: 800,
    fontSize: "1rem",
  },
  emptyCopy: {
    margin: "8px 0 0",
    color: "var(--neutral-700)",
    lineHeight: 1.55,
  },
  fab: {
    position: "fixed",
    right: 24,
    bottom: 104,
    border: "1px solid rgba(5,181,187,0.18)",
    borderRadius: 999,
    padding: "15px 20px",
    background: "linear-gradient(135deg, var(--brand-primary), #12c0c6)",
    color: "#ffffff",
    fontWeight: 800,
    cursor: "pointer",
    boxShadow: "0 16px 30px rgba(5,181,187,0.24)",
  },
};
