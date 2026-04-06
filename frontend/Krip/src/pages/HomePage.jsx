import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getMyProfile, logoutUser } from "../api/auth/auth";

export default function HomePage() {
  const navigate = useNavigate();
  const [user, setUser] = useState(null);

  useEffect(() => {
    getMyProfile()
      .then(setUser)
      .catch((error) => {
        if (error.status === 403 || error.status === 404) {
          navigate("/register");
          return;
        }

        navigate("/login");
      });
  }, [navigate]);

  async function handleLogout() {
    try {
      await logoutUser();
    } finally {
      navigate("/login");
    }
  }

  if (!user) {
    return (
      <div style={s.loading}>
        <span style={s.spinner} />
      </div>
    );
  }

  return (
    <div style={s.wrapper}>
      <div style={s.card}>
        <img src="/logo.png" alt="Krip" style={s.logo} />
        <h1 style={s.title}>안녕하세요, {user.user_name}님 👋</h1>
        <p style={s.email}>{user.email}</p>
        {user.travel_styles?.length > 0 && (
          <div style={s.styles}>
            {user.travel_styles.map((t) => (
              <span key={t} style={s.tag}>{t}</span>
            ))}
          </div>
        )}
        <button style={s.logoutBtn} onClick={handleLogout}>로그아웃</button>
      </div>
    </div>
  );
}

const s = {
  loading: {
    height: "100dvh", display: "flex", alignItems: "center", justifyContent: "center",
    background: "#dff0fb",
  },
  spinner: {
    display: "block", width: 36, height: 36, borderRadius: "50%",
    border: "4px solid #b8d8ef", borderTop: "4px solid #4a9fd4",
    animation: "spin 0.8s linear infinite",
  },
  wrapper: {
    minHeight: "100dvh", background: "linear-gradient(160deg, #dff0fb 0%, #c8e6f5 100%)",
    display: "flex", alignItems: "center", justifyContent: "center",
    fontFamily: "'Nunito', 'Apple SD Gothic Neo', sans-serif",
  },
  card: {
    background: "rgba(255,255,255,0.85)", backdropFilter: "blur(20px)",
    borderRadius: 24, padding: "40px 32px", textAlign: "center",
    width: "100%", maxWidth: 360, boxShadow: "0 8px 40px rgba(0,80,160,0.12)",
  },
  logo: { width: 72, height: 72, borderRadius: 16, marginBottom: 16 },
  title: { margin: "0 0 6px", fontSize: "1.4rem", fontWeight: 800, color: "#1a2d45" },
  email: { margin: "0 0 16px", fontSize: "0.85rem", color: "#7a99b5" },
  styles: { display: "flex", flexWrap: "wrap", gap: 8, justifyContent: "center", marginBottom: 24 },
  tag: {
    padding: "6px 12px", borderRadius: 20, background: "#e0f2ff",
    color: "#1a6fa8", fontSize: "0.8rem", fontWeight: 700,
  },
  logoutBtn: {
    padding: "12px 32px", borderRadius: 12, border: "none",
    background: "#f0f6fa", color: "#5a7a9a", fontWeight: 700,
    cursor: "pointer", fontSize: "0.9rem",
  },
};
