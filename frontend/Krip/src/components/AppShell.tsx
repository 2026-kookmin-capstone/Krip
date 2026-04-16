import type { CSSProperties } from "react";
import { NavLink, Outlet } from "react-router-dom";

const TAB_ITEMS = [
  { to: "/home", label: "Home", icon: "●" },
  { to: "/menu", label: "Menu", icon: "◫" },
  { to: "/mate", label: "Mate", icon: "◎" },
  { to: "/chat", label: "Chat", icon: "◌" },
  { to: "/my", label: "My", icon: "◐" },
] as const;

export default function AppShell() {
  return (
    <div style={styles.shell}>
      <div style={styles.content}>
        <Outlet />
      </div>

      <nav style={styles.nav}>
        {TAB_ITEMS.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            style={({ isActive }) => ({
              ...styles.navItem,
              ...(isActive ? styles.navItemActive : {}),
            })}
          >
            <span style={styles.navIcon}>{item.icon}</span>
            <span>{item.label}</span>
          </NavLink>
        ))}
      </nav>
    </div>
  );
}

const styles: Record<string, CSSProperties> = {
  shell: {
    minHeight: "100dvh",
    background: "transparent",
  },
  content: {
    minHeight: "100dvh",
    paddingBottom: 96,
  },
  nav: {
    position: "fixed",
    left: 16,
    right: 16,
    bottom: 14,
    display: "grid",
    gridTemplateColumns: "repeat(5, minmax(0, 1fr))",
    gap: 8,
    padding: 10,
    borderRadius: 24,
    background: "rgba(255,255,255,0.94)",
    boxShadow: "var(--shadow-soft)",
    border: "1px solid var(--border-soft)",
    backdropFilter: "blur(16px)",
    zIndex: 15,
  },
  navItem: {
    textDecoration: "none",
    color: "var(--neutral-700)",
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    justifyContent: "center",
    gap: 4,
    minHeight: 58,
    borderRadius: 18,
    fontSize: "0.76rem",
    fontWeight: 800,
  },
  navItemActive: {
    background:
      "linear-gradient(135deg, rgba(5, 181, 187, 0.16), rgba(248, 180, 0, 0.18))",
    color: "var(--text-primary)",
  },
  navIcon: {
    fontSize: "1rem",
    lineHeight: 1,
  },
};
