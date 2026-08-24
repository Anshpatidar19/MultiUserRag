import { useEffect, useState } from "react";
import { supabase } from "../api/supabase";
import { UserIcon } from "../components/Icons";

export default function Settings() {
  const [email, setEmail] = useState("");

  useEffect(() => {
    supabase.auth.getUser().then(({ data }) => setEmail(data.user?.email || ""));
  }, []);

  return (
    <div className="content">
      <div className="topbar" style={{ padding: 0, border: "none", marginBottom: 20 }}>
        <h1>Settings</h1>
      </div>

      <div className="card" style={{ padding: 24, maxWidth: 520 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 14, marginBottom: 18 }}>
          <div className="doc-icon" style={{ width: 44, height: 44 }}>
            <UserIcon width={20} height={20} />
          </div>
          <div>
            <div style={{ fontWeight: 700 }}>{email}</div>
            <div className="doc-sub">Signed in via Supabase Auth</div>
          </div>
        </div>

        <div className="stat-label" style={{ marginTop: 8 }}>About this workspace</div>
        <p style={{ fontSize: 13.5, color: "var(--text-secondary)", lineHeight: 1.6 }}>
          Your documents, chat sessions, and messages are private to your account and
          isolated at both the vector-store and database level — no other user can
          query or view them.
        </p>
      </div>
    </div>
  );
}
