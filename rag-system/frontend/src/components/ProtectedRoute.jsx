import { useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import { supabase } from "../api/supabase";
import Sidebar from "./Sidebar";

export default function ProtectedRoute({ children }) {
  const [session, setSession] = useState(undefined); // undefined = loading

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => setSession(data.session));
    const { data: sub } = supabase.auth.onAuthStateChange((_event, session) => setSession(session));
    return () => sub.subscription.unsubscribe();
  }, []);

  if (session === undefined) return null; // could render a spinner
  if (!session) return <Navigate to="/login" replace />;

  return (
    <div className="app-shell">
      <Sidebar />
      <div className="main-area">{children}</div>
    </div>
  );
}
