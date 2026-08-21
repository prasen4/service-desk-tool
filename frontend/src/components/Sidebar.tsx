import { useState } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { useTheme } from "../hooks/useTheme";
import { useJobActivity } from "../hooks/useJobActivity";

const NAV_ITEMS = [
  { to: "/", label: "Dashboard", end: true },
  { to: "/research", label: "Research" },
  { to: "/reports", label: "Reports" },
  { to: "/updates", label: "Updates Feed" },
  { to: "/vendors", label: "Vendor News" },
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

  return (
    <aside className="sidebar">
      <div className="logo">
        <svg viewBox="0 0 130 32" height="30" xmlns="http://www.w3.org/2000/svg">
          <text x="0" y="23" fontFamily="Nunito Sans, Arial, sans-serif" fontSize="18" fontWeight="800" fill="#F6F6F7">
            cotiviti
          </text>
        </svg>
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
    </aside>
  );
}

