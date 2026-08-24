import { useState } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { supabase } from "../api/supabase";
import { useSessions } from "../context/SessionsContext";
import {
  ChatIcon,
  UploadIcon,
  SessionsIcon,
  SettingsIcon,
  LogoutIcon,
  ShieldIcon,
  PlusIcon,
  TrashIcon,
  PanelIcon,
} from "./Icons";

const NAV_ITEMS = [
  { to: "/knowledge-base", label: "Knowledge Base", icon: SessionsIcon },
  { to: "/upload", label: "Upload", icon: UploadIcon },
  { to: "/settings", label: "Settings", icon: SettingsIcon },
];

export default function Sidebar() {
  const [collapsed, setCollapsed] = useState(false);
  const navigate = useNavigate();
  const { sessions, activeId, setActiveId, createSession, renameSession, deleteSession } = useSessions();

  async function handleLogout() {
    await supabase.auth.signOut();
    navigate("/login");
  }

  async function handleNewChat() {
    await createSession("New chat");
    navigate("/chat");
  }

  function handleSelectSession(id) {
    setActiveId(id);
    navigate("/chat");
  }

  return (
    <aside className={`sidebar${collapsed ? " collapsed" : ""}`}>
      <div className="sidebar-top">
        {!collapsed && (
          <div className="sidebar-brand">
            <span className="sidebar-brand-mark">
              <ShieldIcon width={16} height={16} />
            </span>
            KnowledgeBase AI
          </div>
        )}
        <button className="icon-btn sidebar-toggle" onClick={() => setCollapsed((c) => !c)} title={collapsed ? "Expand sidebar" : "Collapse sidebar"}>
          <PanelIcon width={17} height={17} />
        </button>
      </div>

      <button className="new-chat-btn" onClick={handleNewChat} title="New chat">
        <PlusIcon width={16} height={16} />
        {!collapsed && <span>New chat</span>}
      </button>

      <ul className="nav-list">
        {NAV_ITEMS.map(({ to, label, icon: Icon }) => (
          <li key={to}>
            <NavLink to={to} className={({ isActive }) => `nav-item${isActive ? " active" : ""}`} title={label}>
              <Icon width={17} height={17} />
              {!collapsed && label}
            </NavLink>
          </li>
        ))}
      </ul>

      {!collapsed && (
        <>
          <div className="sidebar-section-label">Chats</div>
          <div className="session-scroll">
            {sessions.map((s) => (
              <div key={s.id} className={`session-item${s.id === activeId ? " active" : ""}`} onClick={() => handleSelectSession(s.id)}>
                <ChatIcon width={14} height={14} className="session-item-icon" />
                <span
                  className="session-item-title"
                  onDoubleClick={(e) => {
                    e.stopPropagation();
                    const title = prompt("Rename chat", s.title);
                    if (title) renameSession(s.id, title);
                  }}
                >
                  {s.title}
                </span>
                <button
                  className="icon-mini"
                  onClick={(e) => {
                    e.stopPropagation();
                    if (confirm("Delete this chat?")) deleteSession(s.id);
                  }}
                >
                  <TrashIcon width={13} height={13} />
                </button>
              </div>
            ))}
            {!sessions.length && <div className="session-empty">No chats yet</div>}
          </div>
        </>
      )}

      <div className="sidebar-footer">
        <button className="nav-item" onClick={handleLogout} title="Log out">
          <LogoutIcon width={17} height={17} />
          {!collapsed && "Log out"}
        </button>
      </div>
    </aside>
  );
}