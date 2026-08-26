import { useState } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { supabase } from "../api/supabase";
import { useSessions } from "../context/SessionsContext";
import { useDocuments } from "../context/DocumentsContext";
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
];

export default function Sidebar() {
  const [collapsed, setCollapsed] = useState(false);
  const navigate = useNavigate();
  const { sessions, activeId, setActiveId, createSession, renameSession, deleteSession } = useSessions();
  // Read here (rather than just on Upload/Knowledge Base) so a document
  // that's still being chunked/embedded is visible from every page,
  // including Chat -- the sidebar is the one thing mounted everywhere.
  const { processingCount } = useDocuments();

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
            MultiUserRag
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
            <NavLink
              to={to}
              className={({ isActive }) => `nav-item${isActive ? " active" : ""}`}
              title={
                to === "/knowledge-base" && processingCount > 0
                  ? `${label} (${processingCount} processing)`
                  : label
              }
            >
              <Icon width={17} height={17} />
              {!collapsed && (
                <span style={{ display: "flex", alignItems: "center", gap: 6, flex: 1, minWidth: 0 }}>
                  <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{label}</span>
                  {to === "/knowledge-base" && processingCount > 0 && (
                    <span className="nav-badge">{processingCount}</span>
                  )}
                </span>
              )}
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
        <NavLink
          to="/settings"
          className={({ isActive }) => `nav-item${isActive ? " active" : ""}`}
          title="Settings"
        >
          <SettingsIcon width={17} height={17} />
          {!collapsed && "Settings"}
        </NavLink>

        <button className="nav-item" onClick={handleLogout} title="Log out">
          <LogoutIcon width={17} height={17} />
          {!collapsed && "Log out"}
        </button>
      </div>
    </aside>
  );
}