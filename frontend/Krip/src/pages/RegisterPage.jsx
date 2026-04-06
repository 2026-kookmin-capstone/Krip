import { useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { registerUser } from "../api/auth/auth";

const TRAVEL_STYLES = [
  { key: "activity", label: "⚡ 액티비티" },
  { key: "relaxation", label: "🏖️ 휴양" },
  { key: "tourism", label: "🏛️ 관광" },
  { key: "shopping", label: "🛍️ 쇼핑" },
  { key: "food", label: "🍜 맛집" },
];

export default function RegisterPage() {
  const navigate = useNavigate();
  const { state } = useLocation(); // { email, name } from LoginPage
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const [form, setForm] = useState({
    email: state?.email || "",
    user_name: state?.name || "",
    phone_number: "",
    age: "",
    gender: "",
    travel_styles: [],
  });

  function set(key, value) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  function toggleStyle(key) {
    setForm((f) => ({
      ...f,
      travel_styles: f.travel_styles.includes(key)
        ? f.travel_styles.filter((s) => s !== key)
        : [...f.travel_styles, key],
    }));
  }

  async function handleSubmit() {
    setError("");
    if (!form.email || !form.user_name || !form.phone_number || !form.age || !form.gender) {
      setError("모든 필수 항목을 입력해주세요.");
      return;
    }

    setLoading(true);
    try {
      await registerUser({ ...form, age: Number(form.age) });
      navigate("/home");
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={s.wrapper}>
      <div style={s.card}>
        <div style={s.header}>
          <span style={s.step}>회원가입</span>
          <h2 style={s.title}>여행자 정보 입력</h2>
          <p style={s.sub}>Krip을 더 잘 활용하기 위해 정보를 알려주세요</p>
        </div>

        <div style={s.fields}>
          <Field label="이메일 *">
            <input
              style={s.input}
              type="email"
              value={form.email}
              onChange={(e) => set("email", e.target.value)}
              placeholder="example@gmail.com"
            />
          </Field>

          <Field label="이름 *">
            <input
              style={s.input}
              value={form.user_name}
              onChange={(e) => set("user_name", e.target.value)}
              placeholder="홍길동"
            />
          </Field>

          <Field label="전화번호 *">
            <input
              style={s.input}
              type="tel"
              value={form.phone_number}
              onChange={(e) => set("phone_number", e.target.value)}
              placeholder="010-1234-5678"
            />
          </Field>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            <Field label="나이 *">
              <input
                style={s.input}
                type="number"
                value={form.age}
                onChange={(e) => set("age", e.target.value)}
                placeholder="25"
                min={1}
              />
            </Field>

            <Field label="성별 *">
              <div style={{ display: "flex", gap: 8 }}>
                {[["male", "남성"], ["female", "여성"]].map(([val, label]) => (
                  <button
                    key={val}
                    style={{ ...s.genderBtn, ...(form.gender === val ? s.genderBtnActive : {}) }}
                    onClick={() => set("gender", val)}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </Field>
          </div>

          <Field label="여행 스타일 (복수 선택 가능)">
            <div style={s.styleGrid}>
              {TRAVEL_STYLES.map(({ key, label }) => (
                <button
                  key={key}
                  style={{
                    ...s.styleBtn,
                    ...(form.travel_styles.includes(key) ? s.styleBtnActive : {}),
                  }}
                  onClick={() => toggleStyle(key)}
                >
                  {label}
                </button>
              ))}
            </div>
          </Field>
        </div>

        {error && <p style={s.error}>{error}</p>}

        <button style={{ ...s.submitBtn, opacity: loading ? 0.7 : 1 }} onClick={handleSubmit} disabled={loading}>
          {loading ? "처리 중..." : "가입 완료하기"}
        </button>
      </div>
    </div>
  );
}

function Field({ label, children }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <label style={{ fontSize: "0.8rem", fontWeight: 600, color: "#5a7a9a", letterSpacing: "0.03em" }}>
        {label}
      </label>
      {children}
    </div>
  );
}

const s = {
  wrapper: {
    minHeight: "100dvh",
    background: "linear-gradient(160deg, #dff0fb 0%, #c8e6f5 60%, #b8d8ef 100%)",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    padding: "24px 16px",
    fontFamily: "'Nunito', 'Apple SD Gothic Neo', sans-serif",
  },
  card: {
    background: "rgba(255,255,255,0.85)",
    backdropFilter: "blur(20px)",
    borderRadius: 24,
    padding: "32px 28px",
    width: "100%",
    maxWidth: 420,
    boxShadow: "0 8px 40px rgba(0,80,160,0.12)",
  },
  header: { marginBottom: 24 },
  step: { fontSize: "0.75rem", fontWeight: 700, color: "#4a9fd4", textTransform: "uppercase", letterSpacing: "0.1em" },
  title: { margin: "6px 0 4px", fontSize: "1.5rem", fontWeight: 800, color: "#1a2d45" },
  sub: { margin: 0, fontSize: "0.85rem", color: "#7a99b5" },
  fields: { display: "flex", flexDirection: "column", gap: 16 },
  input: {
    width: "100%", padding: "11px 14px", borderRadius: 10,
    border: "1.5px solid #d0e8f5", fontSize: "0.95rem",
    outline: "none", background: "#f4f9fd", color: "#1a2d45",
    boxSizing: "border-box",
  },
  genderBtn: {
    flex: 1, padding: "11px 0", borderRadius: 10,
    border: "1.5px solid #d0e8f5", background: "#f4f9fd",
    color: "#7a99b5", fontWeight: 700, cursor: "pointer", fontSize: "0.9rem",
  },
  genderBtnActive: {
    background: "#4a9fd4", border: "1.5px solid #4a9fd4", color: "#fff",
  },
  styleGrid: { display: "flex", flexWrap: "wrap", gap: 8 },
  styleBtn: {
    padding: "8px 14px", borderRadius: 20,
    border: "1.5px solid #d0e8f5", background: "#f4f9fd",
    color: "#5a7a9a", fontWeight: 600, cursor: "pointer", fontSize: "0.85rem",
  },
  styleBtnActive: {
    background: "#e0f2ff", border: "1.5px solid #4a9fd4", color: "#1a6fa8",
  },
  error: { margin: "12px 0 0", color: "#e05555", fontSize: "0.85rem", textAlign: "center" },
  submitBtn: {
    marginTop: 24, width: "100%", padding: "14px 0",
    borderRadius: 14, border: "none",
    background: "linear-gradient(135deg, #4a9fd4, #2176ae)",
    color: "#fff", fontSize: "1rem", fontWeight: 800,
    cursor: "pointer", boxShadow: "0 4px 16px rgba(33,118,174,0.3)",
  },
};
