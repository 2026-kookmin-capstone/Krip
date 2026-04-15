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
    .join(" · ");
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
    {
      label: "Nationality",
      value: profile?.nationality ?? "",
    },
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
            {infoItems.map((item) => (
              <div key={item.label} style={styles.infoRow}>
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
    background: "#ffffff",
    fontFamily: "'Nunito', 'Apple SD Gothic Neo', sans-serif",
  },
  profileCard: {
    maxWidth: 720,
    margin: "0 auto",
    padding: 24,
    borderRadius: 30,
    background: "#f6f6f6",
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    textAlign: "center",
    border: "1px solid #ececec",
  },
  avatar: {
    width: 88,
    height: 88,
    borderRadius: "50%",
    display: "grid",
    placeItems: "center",
    background: "#d9d9d9",
    color: "#444444",
    fontWeight: 800,
    fontSize: "1.6rem",
  },
  name: {
    margin: "14px 0 0",
    color: "#222222",
    fontSize: "1.6rem",
  },
  meta: {
    margin: "8px 0 0",
    color: "#666666",
  },
  section: {
    maxWidth: 720,
    margin: "16px auto 0",
  },
  sectionTitle: {
    margin: "0 0 10px",
    color: "#333333",
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
    background: "#efefef",
    color: "#555555",
    fontSize: "0.86rem",
    fontWeight: 700,
  },
  infoList: {
    borderRadius: 20,
    background: "#f6f6f6",
    border: "1px solid #ececec",
    overflow: "hidden",
  },
  infoRow: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 16,
    padding: "14px 16px",
    borderBottom: "1px solid #e9e9e9",
  },
  infoLabel: {
    color: "#777777",
    fontSize: "0.9rem",
  },
  infoValue: {
    color: "#333333",
    fontWeight: 700,
    textAlign: "right",
  },
  logoutButton: {
    display: "block",
    width: "100%",
    maxWidth: 720,
    margin: "16px auto 0",
    border: "1px solid #d8d8d8",
    borderRadius: 18,
    padding: "15px 16px",
    background: "#d9d9d9",
    color: "#333333",
    fontWeight: 800,
    cursor: "pointer",
  },
};
