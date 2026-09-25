import { useState } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { useTheme } from "../hooks/useTheme";
import { useJobActivity } from "../hooks/useJobActivity";
import { useAuthStatus } from "../hooks/useAuthStatus";
import cotivitiLogo from "../assets/cotiviti-logo.svg";

const NAV_ITEMS = [
  { to: "/", label: "Dashboard", end: true },
  { to: "/research", label: "Research" },
  { to: "/reports", label: "Reports" },
  { to: "/updates", label: "Updates Feed" },
  { to: "/vendors", label: "Vendors" },
  { to: "/desks", label: "Tech Desks" },
];

const SETTINGS_ITEMS = [
  { to: "/activity", label: "Activity", badge: true },
  { to: "/configure", label: "LLM Setup" },
];

export default function Sidebar() {
  const [isDark, toggleTheme] = useTheme();
  const { activeCount } = useJobActivity();
  const location = useLocation();
  const settingsActive = SETTINGS_ITEMS.some((item) => location.pathname.startsWith(item.to));
  const [settingsOpen, setSettingsOpen] = useState(settingsActive);
  const authStatus = useAuthStatus();

  return (
    <aside className="sidebar">
      <div className="logo">
        <img src={cotivitiLogo} alt="Cotiviti" className="logo-mark" />
      </div>
      <div className="logo-sub">Technology Desk Intelligence</div>
      <nav className="nav-list">
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) => "nav-item" + (isActive ? " active" : "")}
          >
            {item.label}
          </NavLink>
        ))}
        <button
          type="button"
          className={"nav-item nav-group-toggle" + (settingsActive ? " active" : "")}
          aria-expanded={settingsOpen}
          onClick={() => setSettingsOpen((open) => !open)}
        >
          Settings
          {activeCount > 0 && !settingsOpen && <span className="nav-badge visible">{activeCount}</span>}
          <span className={"nav-chevron" + (settingsOpen ? " open" : "")}>▾</span>
        </button>
        {settingsOpen && (
          <div className="nav-subgroup">
            {SETTINGS_ITEMS.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) => "nav-item nav-subitem" + (isActive ? " active" : "")}
              >
                {item.label}
                {item.badge && (
                  <span className={"nav-badge" + (activeCount > 0 ? " visible" : "")}>{activeCount}</span>
                )}
              </NavLink>
            ))}
          </div>
        )}
      </nav>
      <div className="theme-toggle">
        <span className="label">
          <span>{isDark ? "☀️" : "🌙"}</span> <span>{isDark ? "Light mode" : "Dark mode"}</span>
        </span>
        <button
          className="switch"
          role="switch"
          aria-checked={isDark}
          aria-label="Toggle dark mode"
          onClick={toggleTheme}
        />
      </div>
      {authStatus.enabled && authStatus.logged_in && (
        <div className="theme-toggle" style={{ flexDirection: "column", alignItems: "stretch", gap: 6 }}>
          <span className="label" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {String((authStatus.user?.name as string) || (authStatus.user?.email as string) || "Signed in")}
          </span>
          <a href="/api/auth/logout" onClick={(e) => { e.preventDefault(); fetch("/api/auth/logout", { method: "POST" }).then(() => (window.location.href = "/")); }}>
            Sign out
          </a>
        </div>
      )}
    </aside>
  );
}

