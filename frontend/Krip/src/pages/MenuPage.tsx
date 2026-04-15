import type { CSSProperties } from "react";

export default function MenuPage() {
  return (
    <div style={styles.page}>
      <div style={styles.header}>
        <p style={styles.eyebrow}>Menu OCR</p>
        <h1 style={styles.title}>Menu Translation</h1>
        <p style={styles.copy}>Capture a menu and review the translated result in one simple flow.</p>
      </div>

      <section style={styles.heroCard}>
        <div style={styles.cameraFrame}>
          <div style={styles.cameraIcon}>+</div>
          <p style={styles.cameraTitle}>Upload a Menu Image</p>
          <p style={styles.cameraCopy}>Take a photo or choose one from your gallery</p>
        </div>
        <button type="button" style={styles.primaryButton}>Choose Menu Image</button>
      </section>

      <section style={styles.section}>
        <div style={styles.sectionHeader}>
          <h2 style={styles.sectionTitle}>Translation History</h2>
        </div>

        <div style={styles.emptyCard}>
          <p style={styles.emptyTitle}>No translated menus yet</p>
          <p style={styles.emptyCopy}>Once you upload a menu image, the result will appear here.</p>
        </div>
      </section>
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
    margin: "0 auto 18px",
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
    margin: "8px 0 8px",
    color: "#222222",
    fontSize: "2rem",
    lineHeight: 1.05,
  },
  copy: {
    margin: 0,
    color: "#6f6f6f",
    lineHeight: 1.55,
  },
  heroCard: {
    maxWidth: 720,
    margin: "0 auto",
    padding: 18,
    borderRadius: 30,
    background: "#f7f7f7",
    boxShadow: "0 10px 24px rgba(0, 0, 0, 0.05)",
    border: "1px solid #ececec",
  },
  cameraFrame: {
    minHeight: 280,
    borderRadius: 24,
    border: "2px dashed #d8d8d8",
    background: "#ffffff",
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    justifyContent: "center",
    gap: 10,
  },
  cameraIcon: {
    width: 64,
    height: 64,
    borderRadius: 20,
    display: "grid",
    placeItems: "center",
    background: "#d9d9d9",
    color: "#444444",
    fontSize: "2rem",
  },
  cameraTitle: {
    margin: 0,
    color: "#333333",
    fontWeight: 800,
    fontSize: "1rem",
  },
  cameraCopy: {
    margin: 0,
    color: "#777777",
    fontSize: "0.88rem",
  },
  primaryButton: {
    width: "100%",
    marginTop: 16,
    border: "1px solid #d8d8d8",
    borderRadius: 18,
    padding: "15px 16px",
    background: "#d9d9d9",
    color: "#222222",
    fontWeight: 800,
    cursor: "pointer",
  },
  section: {
    maxWidth: 720,
    margin: "18px auto 0",
  },
  sectionHeader: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 12,
    marginBottom: 10,
  },
  sectionTitle: {
    margin: 0,
    color: "#333333",
    fontSize: "1rem",
    fontWeight: 800,
  },
  emptyCard: {
    padding: 20,
    borderRadius: 22,
    background: "#f7f7f7",
    border: "1px solid #ececec",
  },
  emptyTitle: {
    margin: 0,
    color: "#333333",
    fontSize: "1rem",
    fontWeight: 800,
  },
  emptyCopy: {
    margin: "8px 0 0",
    color: "#777777",
    fontSize: "0.9rem",
    lineHeight: 1.5,
  },
};
