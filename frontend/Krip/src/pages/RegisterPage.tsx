import type { CSSProperties, ReactNode } from "react";
import { useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { registerUser } from "../api/auth/auth";

type TravelStyleKey =
  | "activity"
  | "relaxation"
  | "tourism"
  | "shopping"
  | "food";

interface RegisterLocationState {
  email?: string;
  name?: string;
}

interface RegisterFormState {
  email: string;
  user_name: string;
  phone_number: string;
  age: string;
  gender: string;
  nationality: string;
  travel_styles: TravelStyleKey[];
}

const TRAVEL_STYLES: Array<{ key: TravelStyleKey; label: string }> = [
  { key: "activity", label: "⚡ Activity" },
  { key: "relaxation", label: "🏖️ Relaxation" },
  { key: "tourism", label: "🏛️ Sightseeing" },
  { key: "shopping", label: "🛍️ Shopping" },
  { key: "food", label: "🍜 Food" },
];

export default function RegisterPage() {
  const navigate = useNavigate();
  const { state } = useLocation() as { state: RegisterLocationState | null };
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const [form, setForm] = useState<RegisterFormState>({
    email: state?.email || "",
    user_name: state?.name || "",
    phone_number: "",
    age: "",
    gender: "",
    nationality: "korea",
    travel_styles: [],
  });

  function setField<Key extends keyof RegisterFormState>(
    key: Key,
    value: RegisterFormState[Key]
  ): void {
    setForm((f) => ({ ...f, [key]: value }));
  }

  function toggleStyle(key: TravelStyleKey): void {
    setForm((f) => ({
      ...f,
      travel_styles: f.travel_styles.includes(key)
        ? f.travel_styles.filter((s) => s !== key)
        : [...f.travel_styles, key],
    }));
  }

  async function handleSubmit(): Promise<void> {
    setError("");
    if (!form.email || !form.user_name || !form.phone_number || !form.age || !form.gender || !form.nationality) {
      setError("Please fill in all required fields.");
      return;
    }

    setLoading(true);
    try {
      await registerUser({ ...form, age: Number(form.age) });
      navigate("/home");
    } catch (e) {
      const message =
        e instanceof Error ? e.message : "Something went wrong while completing sign up.";
      setError(message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={s.wrapper}>
      <div style={s.card}>
        <div style={s.header}>
          <span style={s.step}>Sign Up</span>
          <h2 style={s.title}>Traveler Details</h2>
          <p style={s.sub}>Tell us a little about yourself to personalize your trip.</p>
        </div>

        <div style={s.fields}>
          <Field label="Email *">
            <input
              style={s.input}
              type="email"
              value={form.email}
              onChange={(e) => setField("email", e.target.value)}
              placeholder="example@gmail.com"
            />
          </Field>

          <Field label="Name *">
            <input
              style={s.input}
              value={form.user_name}
              onChange={(e) => setField("user_name", e.target.value)}
              placeholder="Your name"
            />
          </Field>

          <Field label="Phone Number *">
            <input
              style={s.input}
              type="tel"
              value={form.phone_number}
              onChange={(e) => setField("phone_number", e.target.value)}
                placeholder="+82 10-1234-5678"
            />
          </Field>

          <div
            style={
              {
                display: "grid",
                gridTemplateColumns: "1fr 1fr",
                gap: 12,
              } as CSSProperties
            }
          >
            <Field label="Age *">
              <input
                style={s.input}
                type="number"
                value={form.age}
                onChange={(e) => setField("age", e.target.value)}
                placeholder="25"
                min={1}
              />
            </Field>

            <Field label="Gender *">
              <div style={{ display: "flex", gap: 8 } as CSSProperties}>
                {[["male", "Male"], ["female", "Female"]].map(([val, label]) => (
                  <button
                    type="button"
                    key={val}
                    style={{ ...s.genderBtn, ...(form.gender === val ? s.genderBtnActive : {}) }}
                    onClick={() => setField("gender", val)}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </Field>
          </div>

          <Field label="Nationality *">
            <select
              style={s.input}
              value={form.nationality}
              onChange={(e) => setField("nationality", e.target.value)}
            >
              <option value="korea">Korea</option>
              <option value="japan">Japan</option>
              <option value="china">China</option>
              <option value="usa">United States</option>
              <option value="other">Other</option>
            </select>
          </Field>

          <Field label="Travel Styles (multiple choice)">
            <div style={s.styleGrid}>
              {TRAVEL_STYLES.map(({ key, label }) => (
                <button
                  key={key}
                  type="button"
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
          {loading ? "Submitting..." : "Complete Sign Up"}
        </button>
      </div>
    </div>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <div
      style={{ display: "flex", flexDirection: "column", gap: 6 } as CSSProperties}
    >
      <label
        style={
          {
            fontSize: "0.8rem",
            fontWeight: 600,
            color: "#666666",
            letterSpacing: "0.03em",
          } as CSSProperties
        }
      >
        {label}
      </label>
      {children}
    </div>
  );
}

const s: Record<string, CSSProperties> = {
  wrapper: {
    minHeight: "100dvh",
    background: "#ffffff",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    padding: "24px 16px",
    fontFamily: "'Nunito', 'Apple SD Gothic Neo', sans-serif",
  },
  card: {
    background: "#ffffff",
    borderRadius: 24,
    padding: "32px 28px",
    width: "100%",
    maxWidth: 420,
    boxShadow: "0 12px 32px rgba(0,0,0,0.07)",
    border: "1px solid #ededed",
  },
  header: { marginBottom: 24 },
  step: { fontSize: "0.75rem", fontWeight: 700, color: "#8a8a8a", textTransform: "uppercase", letterSpacing: "0.1em" },
  title: { margin: "6px 0 4px", fontSize: "1.5rem", fontWeight: 800, color: "#222222" },
  sub: { margin: 0, fontSize: "0.85rem", color: "#777777" },
  fields: { display: "flex", flexDirection: "column", gap: 16 },
  input: {
    width: "100%", padding: "11px 14px", borderRadius: 10,
    border: "1.5px solid #dfdfdf", fontSize: "0.95rem",
    outline: "none", background: "#f7f7f7", color: "#222222",
    boxSizing: "border-box",
  },
  genderBtn: {
    flex: 1, padding: "11px 0", borderRadius: 10,
    border: "1.5px solid #dfdfdf", background: "#f3f3f3",
    color: "#666666", fontWeight: 700, cursor: "pointer", fontSize: "0.9rem",
  },
  genderBtnActive: {
    background: "#d9d9d9", border: "1.5px solid #d9d9d9", color: "#222222",
  },
  styleGrid: { display: "flex", flexWrap: "wrap", gap: 8 },
  styleBtn: {
    padding: "8px 14px", borderRadius: 20,
    border: "1.5px solid #dfdfdf", background: "#f3f3f3",
    color: "#555555", fontWeight: 600, cursor: "pointer", fontSize: "0.85rem",
  },
  styleBtnActive: {
    background: "#d9d9d9", border: "1.5px solid #d9d9d9", color: "#222222",
  },
  error: { margin: "12px 0 0", color: "#e05555", fontSize: "0.85rem", textAlign: "center" },
  submitBtn: {
    marginTop: 24, width: "100%", padding: "14px 0",
    borderRadius: 14, border: "1px solid #d8d8d8",
    background: "#d9d9d9",
    color: "#222222", fontSize: "1rem", fontWeight: 800,
    cursor: "pointer", boxShadow: "0 6px 18px rgba(0,0,0,0.06)",
  },
};
