import { NavLink, useNavigate } from "react-router-dom";
import { supabase } from "../api/supabase";
import { ChatIcon, UploadIcon, SessionsIcon, SettingsIcon, LogoutIcon, ShieldIcon } from "./Icons";

const NAV_ITEMS = [
  { to: "/chat", label: "Chat", icon: ChatIcon },
  { to: "/documents", label: "Knowledge Base", icon: SessionsIcon },
  { to: "/upload", label: "Upload", icon: UploadIcon },
  { to: "/settings", label: "Settings", icon: SettingsIcon },
];

export default function Sidebar() {
  const navigate = useNavigate();

  async function handleLogout() {
    await supabase.auth.signOut();
    navigate("/login");
  }

  return (
    <aside className="sidebar">
      <div className="sidebar-brand">
        <span className="sidebar-brand-mark">
          <ShieldIcon width={16} height={16} />
        </span>
        KnowledgeBase AI
      </div>
      <div className="sidebar-subtitle">Your Private RAG Assistant</div>

      <ul className="nav-list">
        {NAV_ITEMS.map(({ to, label, icon: Icon }) => (
          <li key={to}>
            <NavLink to={to} className={({ isActive }) => `nav-item${isActive ? " active" : ""}`}>
              <Icon width={17} height={17} />
              {label}
            </NavLink>
          </li>
        ))}
      </ul>

      <div className="sidebar-footer">
        <button className="nav-item" onClick={handleLogout}>
          <LogoutIcon width={17} height={17} />
          Log out
        </button>
      </div>
    </aside>
  );
}
