import { useEffect, useState } from "react";
import { Navigate, Outlet } from "react-router-dom";
import { supabase } from "../api/supabase";
import { SessionsProvider } from "../context/SessionsContext";
import { DocumentsProvider } from "../context/DocumentsContext";
import Sidebar from "./Sidebar";

/**
 * Rendered ONCE as a layout route wrapping all authenticated pages via
 * <Outlet/>, rather than individually around each page element. This
 * matters: if each page wrapped itself in a fresh ProtectedRoute, the
 * SessionsProvider/DocumentsProvider underneath would remount on every
 * navigation -- for Sessions that meant silently resetting which chat
 * session is "active" the moment you click into Knowledge Base or
 * Upload and back; for Documents it would mean losing the in-progress
 * poll (see DocumentsContext.jsx) that carries a just-uploaded
 * document from "processing" to "ready" across page switches. Mounting
 * both once at the layout level keeps the sidebar, active session, and
 * document list stable while only the inner page content swaps.
 */
export default function ProtectedRoute() {
  const [session, setSession] = useState(undefined); // undefined = loading

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => setSession(data.session));
    const { data: sub } = supabase.auth.onAuthStateChange((_event, session) => setSession(session));
    return () => sub.subscription.unsubscribe();
  }, []);

  if (session === undefined) return null; // could render a spinner
  if (!session) return <Navigate to="/login" replace />;

  return (
    <SessionsProvider>
      <DocumentsProvider>
        <div className="app-shell">
          <Sidebar />
          <div className="main-area">
            <Outlet />
          </div>
        </div>
      </DocumentsProvider>
    </SessionsProvider>
  );
}