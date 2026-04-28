import type { CSSProperties } from "react";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  deleteMyProfileImage,
  getMyProfile,
  logoutUser,
  replaceMyProfileImage,
  uploadMyProfileImage,
  withdrawUser,
  type UserProfile,
} from "../api/auth/auth";

export default function MyPage() {
  const navigate = useNavigate();
  const profileImageInputRef = useRef<HTMLInputElement>(null);
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [activeTab, setActiveTab] = useState<"styles" | "info">("styles");
  const [isWithdrawing, setIsWithdrawing] = useState(false);
  const [isUploadingProfileImage, setIsUploadingProfileImage] = useState(false);
  const [isDeletingProfileImage, setIsDeletingProfileImage] = useState(false);
  const [isProfileImageMenuOpen, setIsProfileImageMenuOpen] = useState(false);
  const [profileImagePreview, setProfileImagePreview] = useState("");

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

  async function handleWithdraw(): Promise<void> {
    const confirmed = window.confirm(
      "Delete your account permanently? All user data will be removed."
    );

    if (!confirmed || isWithdrawing) {
      return;
    }

    setIsWithdrawing(true);

    try {
      await withdrawUser();
      navigate("/login", { replace: true });
    } catch (error) {
      const message =
        error instanceof Error
          ? error.message
          : "Account withdrawal failed. Please try again.";
      window.alert(message);
      setIsWithdrawing(false);
    }
  }

  async function handleProfileImageChange(
    event: React.ChangeEvent<HTMLInputElement>
  ): Promise<void> {
    const file = event.target.files?.[0];
    if (!file) return;

    setIsProfileImageMenuOpen(false);

    if (!["image/jpeg", "image/png", "image/webp", "image/gif"].includes(file.type)) {
      window.alert("Please choose a JPG, PNG, WEBP, or GIF image.");
      event.target.value = "";
      return;
    }

    if (file.size > 5 * 1024 * 1024) {
      window.alert("Please choose an image smaller than 5MB.");
      event.target.value = "";
      return;
    }

    const previewUrl = URL.createObjectURL(file);
    setProfileImagePreview(previewUrl);
    setIsUploadingProfileImage(true);

    try {
      let updatedImage = null;

      if (getProfileImageUrl(profile)) {
        try {
          updatedImage = await replaceMyProfileImage(file);
        } catch (replaceError) {
          if (getApiStatus(replaceError) !== 404) {
            throw replaceError;
          }

          updatedImage = await uploadMyProfileImage(file);
        }
      } else {
        try {
          updatedImage = await uploadMyProfileImage(file);
        } catch (uploadError) {
          if (getApiStatus(uploadError) !== 409) {
            throw uploadError;
          }

          updatedImage = await replaceMyProfileImage(file);
        }
      }

      if (updatedImage) {
        setProfile((current) => ({ ...current, ...updatedImage }) as UserProfile);
      } else {
        const refreshedProfile = await getMyProfile();
        if (refreshedProfile) setProfile(refreshedProfile);
      }
    } catch (error) {
      setProfileImagePreview("");
      window.alert(toErrorMessage(error, "Profile photo upload failed. Please try again."));
    } finally {
      setIsUploadingProfileImage(false);
      event.target.value = "";
      URL.revokeObjectURL(previewUrl);
    }
  }

  async function handleProfileImageDelete(): Promise<void> {
    if (isDeletingProfileImage || isUploadingProfileImage) {
      return;
    }

    setIsDeletingProfileImage(true);

    try {
      await deleteMyProfileImage();
      setProfile((current) =>
        current
          ? {
              ...current,
              profile_image_url: null,
              profileImageUrl: "",
              avatar_url: "",
              image_url: "",
              imageUrl: "",
            }
          : current
      );
      setProfileImagePreview("");
      setIsProfileImageMenuOpen(false);
    } catch (error) {
      window.alert(toErrorMessage(error, "Profile photo delete failed. Please try again."));
    } finally {
      setIsDeletingProfileImage(false);
    }
  }

  const avatarText = profile?.user_name?.slice(0, 2) ?? "";
  const profileImageUrl = profileImagePreview || getProfileImageUrl(profile);
  const canDeleteProfileImage =
    Boolean(getProfileImageUrl(profile)) && !profileImagePreview;
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
    { label: "User ID", value: profile?.user_id ?? "" },
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
        <div style={styles.avatarWrap}>
          <button
            type="button"
            style={styles.avatarButton}
            onClick={() => setIsProfileImageMenuOpen((current) => !current)}
            disabled={isUploadingProfileImage || isDeletingProfileImage}
            aria-label="Change profile photo"
          >
            {profileImageUrl ? (
              <img src={profileImageUrl} alt="" style={styles.avatarImage} />
            ) : (
              <span style={styles.avatarText}>{avatarText}</span>
            )}
            {isUploadingProfileImage ? (
              <span style={styles.avatarOverlay}>Uploading...</span>
            ) : isDeletingProfileImage ? (
              <span style={styles.avatarOverlay}>Deleting...</span>
            ) : (
              <span style={styles.avatarEditBadge}>Change</span>
            )}
          </button>
          {isProfileImageMenuOpen ? (
            <div style={styles.avatarMenu}>
              <button
                type="button"
                style={styles.avatarMenuButton}
                onClick={() => profileImageInputRef.current?.click()}
              >
                Upload Photo
              </button>
              <button
                type="button"
                style={{
                  ...styles.avatarMenuButton,
                  ...styles.avatarMenuDanger,
                  ...(!canDeleteProfileImage ? styles.avatarMenuButtonDisabled : {}),
                }}
                onClick={() => void handleProfileImageDelete()}
                disabled={!canDeleteProfileImage || isDeletingProfileImage}
              >
                Delete Photo
              </button>
            </div>
          ) : null}
          <input
            ref={profileImageInputRef}
            type="file"
            accept="image/jpeg,image/png,image/webp,image/gif"
            style={styles.hiddenInput}
            onChange={(event) => void handleProfileImageChange(event)}
          />
        </div>
        <h1 style={styles.name}>{nameText}</h1>
        <p style={styles.meta}>{metaText}</p>
      </div>

      <section style={styles.tabSection}>
        <div style={styles.tabPanel}>
          <button
            type="button"
            style={{
              ...styles.tabButton,
              ...(activeTab === "styles" ? styles.tabButtonActive : {}),
            }}
            onClick={() => setActiveTab("styles")}
          >
            Travel Styles
          </button>
          <button
            type="button"
            style={{
              ...styles.tabButton,
              ...(activeTab === "info" ? styles.tabButtonActive : {}),
            }}
            onClick={() => setActiveTab("info")}
          >
            My Info
          </button>
        </div>
      </section>

      {activeTab === "styles" && profile?.travel_styles?.length ? (
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

      {activeTab === "styles" && !profile?.travel_styles?.length ? (
        <section style={styles.section}>
          <div style={styles.emptyPanel}>No travel styles yet.</div>
        </section>
      ) : null}

      {activeTab === "info" && infoItems.length ? (
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

      {activeTab === "info" && infoItems.length === 0 ? (
        <section style={styles.section}>
          <div style={styles.emptyPanel}>No basic information available.</div>
        </section>
      ) : null}

      <button type="button" style={styles.logoutButton} onClick={handleLogout}>
        Log Out
      </button>

      <button
        type="button"
        style={{
          ...styles.withdrawButton,
          ...(isWithdrawing ? styles.withdrawButtonDisabled : {}),
        }}
        onClick={handleWithdraw}
        disabled={isWithdrawing}
      >
        {isWithdrawing ? "Deleting Account..." : "Delete Account"}
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
  avatarWrap: {
    position: "relative",
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    gap: 10,
  },
  avatarButton: {
    width: 88,
    height: 88,
    position: "relative",
    padding: 0,
    border: "none",
    borderRadius: "50%",
    display: "grid",
    placeItems: "center",
    background: "linear-gradient(135deg, var(--brand-primary), var(--brand-primary-deep))",
    color: "#ffffff",
    overflow: "hidden",
    cursor: "pointer",
    boxShadow: "0 12px 24px rgba(5,181,187,0.24)",
  },
  avatarText: {
    fontWeight: 800,
    fontSize: "1.6rem",
  },
  avatarImage: {
    width: "100%",
    height: "100%",
    objectFit: "cover",
  },
  avatarEditBadge: {
    position: "absolute",
    left: 0,
    right: 0,
    bottom: 0,
    padding: "5px 4px 6px",
    background: "rgba(24,26,32,0.62)",
    color: "#ffffff",
    fontSize: "0.68rem",
    fontWeight: 800,
  },
  avatarOverlay: {
    position: "absolute",
    inset: 0,
    display: "grid",
    placeItems: "center",
    padding: 10,
    background: "rgba(24,26,32,0.58)",
    color: "#ffffff",
    fontSize: "0.72rem",
    fontWeight: 800,
    textAlign: "center",
  },
  avatarMenu: {
    zIndex: 6,
    width: 168,
    padding: 8,
    borderRadius: 16,
    background: "#ffffff",
    border: "1px solid var(--border-soft)",
    boxShadow: "0 16px 34px rgba(33,33,33,0.16)",
  },
  avatarMenuButton: {
    width: "100%",
    minHeight: 38,
    border: "none",
    borderRadius: 12,
    padding: "0 12px",
    background: "transparent",
    color: "var(--text-secondary)",
    fontWeight: 800,
    textAlign: "left",
    cursor: "pointer",
  },
  avatarMenuDanger: {
    color: "#dc2626",
  },
  avatarMenuButtonDisabled: {
    color: "var(--neutral-500)",
    cursor: "not-allowed",
    opacity: 0.58,
  },
  hiddenInput: {
    display: "none",
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
  tabSection: {
    maxWidth: 720,
    margin: "18px auto 0",
  },
  tabPanel: {
    display: "grid",
    gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
    gap: 8,
    padding: 8,
    borderRadius: 22,
    background: "rgba(255,255,255,0.88)",
    border: "1px solid var(--border-soft)",
    boxShadow: "var(--shadow-soft)",
  },
  tabButton: {
    minHeight: 44,
    border: "none",
    borderRadius: 16,
    background: "transparent",
    color: "var(--neutral-700)",
    fontWeight: 800,
    cursor: "pointer",
  },
  tabButtonActive: {
    background: "linear-gradient(135deg, rgba(5,181,187,0.16), rgba(228,247,247,0.96))",
    color: "var(--text-primary)",
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
    overflowWrap: "anywhere",
  },
  emptyPanel: {
    padding: 22,
    borderRadius: 24,
    background: "rgba(255,255,255,0.88)",
    border: "1px solid var(--border-soft)",
    color: "var(--neutral-700)",
    boxShadow: "var(--shadow-soft)",
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
  withdrawButton: {
    display: "block",
    width: "100%",
    maxWidth: 720,
    margin: "12px auto 0",
    border: "1px solid rgba(220,38,38,0.22)",
    borderRadius: 18,
    padding: "15px 16px",
    background: "rgba(255,255,255,0.92)",
    color: "#dc2626",
    fontWeight: 800,
    cursor: "pointer",
    boxShadow: "var(--shadow-soft)",
  },
  withdrawButtonDisabled: {
    opacity: 0.62,
    cursor: "not-allowed",
  },
};

function getProfileImageUrl(profile: UserProfile | null): string {
  if (!profile) return "";
  return (
    profile.profile_image_url ||
    profile.profileImageUrl ||
    profile.avatar_url ||
    profile.image_url ||
    profile.imageUrl ||
    ""
  );
}

function toErrorMessage(error: unknown, fallback: string): string {
  const apiError = error as { message?: string };
  return apiError.message || fallback;
}

function getApiStatus(error: unknown): number | undefined {
  const apiError = error as { status?: number; response?: { status?: number } };
  return apiError.status || apiError.response?.status;
}

const SAVED_PLAN_PANEL_ID = "krip-saved-plan-panel";
const SAVED_PLAN_STORAGE_KEY = "krip-saved-trip-plans";
const SAVED_PLAN_EVENT = "krip:saved-plans-updated";

interface MyPageSavedPlanRecord {
  id: string;
  type: "ai" | "manual";
  title: string;
  summary: string;
  updatedAt: string;
}

function readSavedPlanRecords(): MyPageSavedPlanRecord[] {
  try {
    const raw = window.localStorage.getItem(SAVED_PLAN_STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as MyPageSavedPlanRecord[];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function ensureSavedPlanPanel(): HTMLDivElement | null {
  if (window.location.pathname !== "/my") {
    document.getElementById(SAVED_PLAN_PANEL_ID)?.remove();
    return null;
  }

  let panel = document.getElementById(SAVED_PLAN_PANEL_ID) as HTMLDivElement | null;
  if (panel) return panel;

  panel = document.createElement("div");
  panel.id = SAVED_PLAN_PANEL_ID;
  panel.style.maxWidth = "720px";
  panel.style.margin = "18px auto 110px";
  panel.style.padding = "20px";
  panel.style.borderRadius = "24px";
  panel.style.background = "rgba(255,255,255,0.94)";
  panel.style.border = "1px solid var(--border-soft)";
  panel.style.boxShadow = "var(--shadow-soft)";

  const page = document.querySelector("div");
  if (!page || !page.parentElement) return null;
  page.parentElement.appendChild(panel);
  return panel;
}

function renderSavedPlanPanel(): void {
  const panel = ensureSavedPlanPanel();
  if (!panel) return;

  const plans = readSavedPlanRecords();
  const cards =
    plans.length > 0
      ? plans
          .map(
            (plan) => `
              <article style="padding:14px 0;border-top:1px solid #eef4f4;">
                <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;">
                  <div>
                    <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
                      <strong style="font-size:15px;color:#102223;">${plan.title}</strong>
                      <span style="padding:5px 9px;border-radius:999px;background:rgba(1,192,192,0.12);color:#01C0C0;font-size:11px;font-weight:800;text-transform:uppercase;">${plan.type}</span>
                    </div>
                    <p style="margin:6px 0 0;color:#577071;font-size:13px;line-height:1.5;">${plan.summary}</p>
                    <p style="margin:6px 0 0;color:#7a8f8f;font-size:12px;">${new Date(plan.updatedAt).toLocaleString()}</p>
                  </div>
                  <div style="display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end;">
                    <button data-plan-action="open" data-plan-id="${plan.id}" data-plan-type="${plan.type}" style="border:none;border-radius:12px;padding:10px 12px;background:#01C0C0;color:#fff;font-size:12px;font-weight:800;cursor:pointer;">Open</button>
                    <button data-plan-action="delete" data-plan-id="${plan.id}" style="border:none;border-radius:12px;padding:10px 12px;background:rgba(255,190,15,0.18);color:#7a5400;font-size:12px;font-weight:800;cursor:pointer;">Delete</button>
                  </div>
                </div>
              </article>
            `
          )
          .join("")
      : `<p style="margin:0;color:#577071;font-size:14px;line-height:1.6;">Saved AI and manual trip plans will appear here.</p>`;

  panel.innerHTML = `
    <div style="display:flex;flex-direction:column;gap:12px;">
      <div>
        <h2 style="margin:0;color:#102223;font-size:18px;">Saved Plans</h2>
        <p style="margin:6px 0 0;color:#577071;font-size:13px;line-height:1.5;">Review, reopen, or delete the itineraries you saved from AI and manual planning.</p>
      </div>
      ${cards}
    </div>
  `;

  panel.querySelectorAll<HTMLButtonElement>("[data-plan-action]").forEach((button) => {
    button.onclick = () => {
      const action = button.dataset.planAction;
      const planId = button.dataset.planId;
      const planType = button.dataset.planType;
      if (!planId) return;

      if (action === "delete") {
        const nextPlans = readSavedPlanRecords().filter((plan) => plan.id !== planId);
        window.localStorage.setItem(SAVED_PLAN_STORAGE_KEY, JSON.stringify(nextPlans));
        window.dispatchEvent(new CustomEvent(SAVED_PLAN_EVENT));
        renderSavedPlanPanel();
        return;
      }

      if (planType === "ai") {
        window.location.href = `/plan/ai/result?planId=${planId}`;
        return;
      }

      window.location.href = `/plan/manual?planId=${planId}`;
    };
  });
}

if (typeof window !== "undefined") {
  window.addEventListener("load", renderSavedPlanPanel);
  window.addEventListener(SAVED_PLAN_EVENT, renderSavedPlanPanel);
  window.setTimeout(renderSavedPlanPanel, 0);
  window.setInterval(renderSavedPlanPanel, 800);
}

const SAVED_PLAN_TOGGLE_ID = "krip-saved-plan-toggle";

function findLogoutButton(): HTMLButtonElement | null {
  const buttons = Array.from(document.querySelectorAll("button"));
  return (
    buttons.find((button) => button.textContent?.trim().toLowerCase() === "log out") || null
  );
}

function ensureSavedPlanToggle(): HTMLButtonElement | null {
  if (window.location.pathname !== "/my") {
    document.getElementById(SAVED_PLAN_TOGGLE_ID)?.remove();
    return null;
  }

  const logoutButton = findLogoutButton();
  if (!logoutButton?.parentElement) return null;

  let toggle = document.getElementById(SAVED_PLAN_TOGGLE_ID) as HTMLButtonElement | null;
  if (!toggle) {
    toggle = document.createElement("button");
    toggle.id = SAVED_PLAN_TOGGLE_ID;
    toggle.type = "button";
    toggle.textContent = "View Saved Plans";
    toggle.style.display = "block";
    toggle.style.width = "100%";
    toggle.style.maxWidth = "720px";
    toggle.style.margin = "18px auto 0";
    toggle.style.border = "1px solid rgba(1,192,192,0.18)";
    toggle.style.borderRadius = "18px";
    toggle.style.padding = "15px 16px";
    toggle.style.background = "#ffffff";
    toggle.style.color = "#0f5152";
    toggle.style.fontWeight = "800";
    toggle.style.cursor = "pointer";
    toggle.style.boxShadow = "var(--shadow-soft)";
  }

  logoutButton.parentElement.insertBefore(toggle, logoutButton);
  return toggle;
}

function positionSavedPlanPanel(): void {
  if (window.location.pathname !== "/my") return;

  const panel = document.getElementById(SAVED_PLAN_PANEL_ID) as HTMLDivElement | null;
  const toggle = ensureSavedPlanToggle();
  const logoutButton = findLogoutButton();

  if (!panel || !toggle || !logoutButton?.parentElement) return;

  panel.style.margin = "12px auto 0";
  panel.style.display = panel.dataset.open === "true" ? "block" : "none";

  logoutButton.parentElement.insertBefore(panel, logoutButton);

  toggle.textContent = panel.dataset.open === "true" ? "Hide Saved Plans" : "View Saved Plans";
  toggle.onclick = () => {
    const isOpen = panel.dataset.open === "true";
    panel.dataset.open = isOpen ? "false" : "true";
    panel.style.display = isOpen ? "none" : "block";
    toggle.textContent = isOpen ? "View Saved Plans" : "Hide Saved Plans";
  };
}

if (typeof window !== "undefined") {
  const syncSavedPlanUi = () => {
    renderSavedPlanPanel();
    positionSavedPlanPanel();
  };

  window.addEventListener("load", syncSavedPlanUi);
  window.addEventListener(SAVED_PLAN_EVENT, syncSavedPlanUi);
  window.setTimeout(syncSavedPlanUi, 30);
  window.setInterval(positionSavedPlanPanel, 800);
}
