import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { createLoginUrl } from "../api/auth/auth";
import { saveTokenFromParams } from "../utils/tokens";

export default function LoginPage() {
  const navigate = useNavigate();

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const status = params.get("status");
    saveTokenFromParams(params);

    if (!status) return;

    const email = decodeURIComponent(params.get("email") || "");
    const name = decodeURIComponent(params.get("name") || "");

    window.history.replaceState({}, "", window.location.pathname);

    if (status === "complete") {
      navigate("/home");
    } else if (status === "new" || status === "in_progress") {
      navigate("/register", { state: { email, name } });
    }
  }, [navigate]);

  function handleGoogleLogin() {
    window.location.href = createLoginUrl();
  }

  return (
    <div style={styles.wrapper}>
      <div style={styles.bgTopRight} />
      <div style={styles.bgBottomLeft} />

      <div style={styles.center}>
        <img src="/logo.png" alt="Krip 로고" style={styles.logo} />
        <h1 style={styles.appName}>KRIP</h1>
        <p style={styles.tagline}>KOREA-TRIP</p>
      </div>

      <div style={styles.bottom}>
        <button style={styles.googleBtn} onClick={handleGoogleLogin}>
          <GoogleIcon />
          Sign in with Google
        </button>
      </div>
    </div>
  );
}

function GoogleIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 48 48" style={{ marginRight: 10, flexShrink: 0 }}>
      <path fill="#EA4335" d="M24 9.5c3.14 0 5.95 1.08 8.17 2.85l6.09-6.09C34.46 3.09 29.5 1 24 1 14.82 1 6.97 6.48 3.28 14.38l7.09 5.51C12.12 13.71 17.6 9.5 24 9.5z"/>
      <path fill="#4285F4" d="M46.52 24.5c0-1.64-.15-3.22-.42-4.74H24v8.98h12.68c-.55 2.94-2.2 5.43-4.68 7.1l7.19 5.59C43.18 37.64 46.52 31.55 46.52 24.5z"/>
      <path fill="#FBBC05" d="M10.37 28.11A14.6 14.6 0 0 1 9.5 24c0-1.42.24-2.8.67-4.11L3.08 14.38A23.94 23.94 0 0 0 0 24c0 3.87.92 7.52 2.54 10.73l7.83-6.62z"/>
      <path fill="#34A853" d="M24 47c5.52 0 10.15-1.83 13.54-4.97l-7.19-5.59c-1.83 1.23-4.17 1.96-6.35 1.96-6.4 0-11.88-4.21-13.63-9.89l-7.83 6.62C6.97 41.52 14.82 47 24 47z"/>
    </svg>
  );
}

const styles = {
  wrapper: {
    position: "relative", width: "100vw", height: "100dvh",
    background: "linear-gradient(160deg, #dff0fb 0%, #c8e6f5 50%, #b8d8ef 100%)",
    display: "flex", flexDirection: "column", alignItems: "center",
    justifyContent: "space-between", overflow: "hidden",
    fontFamily: "'Nunito', 'Apple SD Gothic Neo', sans-serif",
  },
  bgTopRight: {
    position: "absolute", top: -80, right: -80, width: 280, height: 280,
    borderRadius: "50%", background: "rgba(255,255,255,0.35)",
  },
  bgBottomLeft: {
    position: "absolute", bottom: -60, left: -60, width: 200, height: 200,
    borderRadius: "50%", background: "rgba(255,255,255,0.25)",
  },
  center: {
    flex: 1, display: "flex", flexDirection: "column",
    alignItems: "center", justifyContent: "center", gap: 12,
  },
  logo: { width: 110, height: 110, borderRadius: 24, boxShadow: "0 8px 30px rgba(0,100,200,0.15)" },
  appName: { margin: 0, fontSize: "2.2rem", fontWeight: 800, color: "#1a2d45", letterSpacing: "-0.5px" },
  tagline: { margin: 0, fontSize: "0.9rem", color: "#7a99b5", letterSpacing: "0.08em", textTransform: "uppercase" },
  bottom: {
    width: "100%", maxWidth: 400, padding: "0 24px 48px",
    display: "flex", flexDirection: "column", alignItems: "center", position: "relative", zIndex: 1,
  },
  googleBtn: {
    display: "flex", alignItems: "center", justifyContent: "center",
    width: "100%", padding: "14px 0", borderRadius: 14, border: "none",
    background: "#ffffff", color: "#1a2d45", fontSize: "1rem", fontWeight: 700,
    cursor: "pointer", boxShadow: "0 4px 20px rgba(0,80,160,0.12)",
  },
};
