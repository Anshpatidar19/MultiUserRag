import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { apiGet, apiPost, apiPatch, apiDelete } from "../api/client";

/**
 * Chat sessions used to live only inside Chat.jsx, with their own rail.
 * Now that the sidebar shows sessions ChatGPT-style on every page, the
 * list needs to be shared state rather than re-fetched/duplicated per
 * page -- this context is that single source of truth.
 */
const SessionsContext = createContext(null);

export function SessionsProvider({ children }) {
  const [sessions, setSessions] = useState([]);
  const [activeId, setActiveId] = useState(null);
  const [loaded, setLoaded] = useState(false);

  const refresh = useCallback(async () => {
    const data = await apiGet("/sessions");
    setSessions(data);
    setLoaded(true);
    return data;
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const createSession = useCallback(async (title = "New chat") => {
    const s = await apiPost("/sessions", { title });
    setSessions((prev) => [s, ...prev]);
    setActiveId(s.id);
    return s;
  }, []);

  const renameSession = useCallback(async (id, title) => {
    await apiPatch(`/sessions/${id}`, { title });
    setSessions((prev) => prev.map((s) => (s.id === id ? { ...s, title } : s)));
  }, []);

  const deleteSession = useCallback(
    async (id) => {
      await apiDelete(`/sessions/${id}`);
      setSessions((prev) => prev.filter((s) => s.id !== id));
      if (activeId === id) setActiveId(null);
    },
    [activeId]
  );

  // A session created via "+ New chat" starts with a placeholder title;
  // once the first message is sent, Chat.jsx calls this to give it a
  // real name derived from that message, same pattern ChatGPT uses.
  const autoNameFromMessage = useCallback(
    async (id, message) => {
      const title = message.trim().slice(0, 48) || "New chat";
      await renameSession(id, title);
    },
    [renameSession]
  );

  return (
    <SessionsContext.Provider
      value={{ sessions, activeId, setActiveId, loaded, refresh, createSession, renameSession, deleteSession, autoNameFromMessage }}
    >
      {children}
    </SessionsContext.Provider>
  );
}

export function useSessions() {
  const ctx = useContext(SessionsContext);
  if (!ctx) throw new Error("useSessions must be used within SessionsProvider");
  return ctx;
}