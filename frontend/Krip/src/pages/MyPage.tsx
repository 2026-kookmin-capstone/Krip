import type { CSSProperties } from "react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getMyProfile, logoutUser, type UserProfile } from "../api/auth/auth";

export default function MyPage() {
  const navigate = useNavigate();
  const [profile, setProfile] = useState<UserProfile | null>(null);

  useEffect(() => {
    getMyProfile()
      .then((data) => {
        if (data) {
          setProfile(data);
        }
      })
      .catch(() => {
        setProfile(null);
      });
  }, []);

  async function handleLogout(): Promise<void> {
    try {
      await logoutUser();
    } finally {
      navigate("/login");
    }
  }

  const avatarText = profile?.user_name?.slice(0, 2) ?? "";
  const nameText = profile?.user_name ?? "";
  const metaText = [
    profile?.nationality,
    profile?.age ? `${profile.age}` : "",
    profile?.gender === "male"
      ? "Male"
      : profile?.gender === "female"
        ? "Female"
        : "",
  ]
    .filter(Boolean)
    .join(" / ");

  const infoItems = [
    { label: "Email", value: profile?.email ?? "" },
    { label: "Phone", value: profile?.phone_number ?? "" },
    {
      label: "Gender",
      value:
        profile?.gender === "male"
          ? "Male"
          : profile?.gender === "female"
            ? "Female"
            : "",
    },
    { label: "Nationality", value: profile?.nationality ?? "" },
  ].filter((item) => item.value);

  return (
    <div style={styles.page}>
      <div style={styles.profileCard}>
        <div style={styles.avatar}>{avatarText}</div>
        <h1 style={styles.name}>{nameText}</h1>
        <p style={styles.meta}>{metaText}</p>
      </div>

      {profile?.travel_styles?.length ? (
        <section style={styles.section}>
          <h2 style={styles.sectionTitle}>Travel Styles</h2>
          <div style={styles.tagWrap}>
            {profile.travel_styles.map((style) => (
              <span key={style} style={styles.tag}>
                {style}
              </span>
            ))}
          </div>
        </section>
      ) : null}

      {infoItems.length ? (
        <section style={styles.section}>
          <h2 style={styles.sectionTitle}>Basic Information</h2>
          <div style={styles.infoList}>
            {infoItems.map((item, index) => (
              <div
                key={item.label}
                style={{
                  ...styles.infoRow,
                  ...(index === infoItems.length - 1 ? styles.infoRowLast : {}),
                }}
              >
                <span style={styles.infoLabel}>{item.label}</span>
                <span style={styles.infoValue}>{item.value}</span>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      <button type="button" style={styles.logoutButton} onClick={handleLogout}>
        Log Out
      </button>
    </div>
  );
}

const styles: Record<string, CSSProperties> = {
  page: {
    minHeight: "100dvh",
    padding: "24px 16px 0",
    background: "transparent",
    fontFamily: "'Nunito', 'Apple SD Gothic Neo', sans-serif",
  },
  profileCard: {
    maxWidth: 720,
    margin: "0 auto",
    padding: 28,
    borderRadius: 32,
    background:
      "linear-gradient(180deg, rgba(5,181,187,0.12), rgba(255,255,255,0.98) 38%)",
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    textAlign: "center",
    border: "1px solid rgba(5,181,187,0.14)",
    boxShadow: "var(--shadow-soft)",
  },
  avatar: {
    width: 88,
    height: 88,
    borderRadius: "50%",
    display: "grid",
    placeItems: "center",
    background: "linear-gradient(135deg, var(--brand-primary), var(--brand-primary-deep))",
    color: "#ffffff",
    fontWeight: 800,
    fontSize: "1.6rem",
    boxShadow: "0 12px 24px rgba(5,181,187,0.24)",
  },
  name: {
    margin: "14px 0 0",
    color: "var(--text-primary)",
    fontSize: "1.6rem",
  },
  meta: {
    margin: "8px 0 0",
    color: "var(--neutral-700)",
  },
  section: {
    maxWidth: 720,
    margin: "18px auto 0",
  },
  sectionTitle: {
    margin: "0 0 10px",
    color: "var(--text-primary)",
    fontSize: "1rem",
    fontWeight: 800,
  },
  tagWrap: {
    display: "flex",
    flexWrap: "wrap",
    gap: 8,
  },
  tag: {
    padding: "8px 12px",
    borderRadius: 999,
    background: "var(--brand-primary-soft)",
    color: "var(--brand-primary-deep)",
    fontSize: "0.86rem",
    fontWeight: 700,
    border: "1px solid rgba(5,181,187,0.08)",
  },
  infoList: {
    borderRadius: 24,
    background: "rgba(255,255,255,0.88)",
    border: "1px solid var(--border-soft)",
    overflow: "hidden",
    boxShadow: "var(--shadow-soft)",
  },
  infoRow: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 16,
    padding: "14px 16px",
    borderBottom: "1px solid var(--neutral-200)",
  },
  infoRowLast: {
    borderBottom: "none",
  },
  infoLabel: {
    color: "var(--neutral-700)",
    fontSize: "0.9rem",
  },
  infoValue: {
    color: "var(--text-secondary)",
    fontWeight: 700,
    textAlign: "right",
  },
  logoutButton: {
    display: "block",
    width: "100%",
    maxWidth: 720,
    margin: "18px auto 0",
    border: "1px solid rgba(5,181,187,0.18)",
    borderRadius: 18,
    padding: "15px 16px",
    background: "linear-gradient(135deg, var(--brand-primary), #12c0c6)",
    color: "#ffffff",
    fontWeight: 800,
    cursor: "pointer",
    boxShadow: "0 12px 24px rgba(5,181,187,0.22)",
  },
};
