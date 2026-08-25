import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { supabase } from "../api/supabase";
import { ShieldIcon } from "../components/Icons";

export default function Login() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(true);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    setLoading(true);
    const { error } = await supabase.auth.signInWithPassword({ email, password });
    setLoading(false);
    if (error) {
      setError(error.message);
      return;
    }
    navigate("/chat");
  }

  return (
    <div className="auth-shell">
      <div className="auth-card">
        <div className="auth-icon">
          <ShieldIcon width={26} height={26} />
        </div>
        <h1 className="auth-title">Sign in to MultiUserRag</h1>
        <p className="auth-subtitle">Your private, AI-powered document assistant</p>

        <form onSubmit={handleSubmit}>
          <div className="field">
            <label>Work email</label>
            <input type="email" placeholder="you@company.com" value={email} onChange={(e) => setEmail(e.target.value)} required />
          </div>
          <div className="field">
            <label>Password</label>
            <input type="password" placeholder="••••••••••" value={password} onChange={(e) => setPassword(e.target.value)} required />
          </div>

          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 22, fontSize: 13.5 }}>
            <label style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--text-secondary)" }}>
              <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
              Remember me
            </label>
            <a href="#" style={{ fontWeight: 600 }}>Forgot password?</a>
          </div>

          {error && (
            <div style={{ background: "var(--danger-soft)", color: "var(--danger)", padding: "10px 14px", borderRadius: 8, fontSize: 13, marginBottom: 16 }}>
              {error}
            </div>
          )}

          <button className="btn-primary" style={{ width: "100%" }} disabled={loading} type="submit">
            {loading ? "Signing in…" : "Sign in"}
          </button>
        </form>

        <p className="auth-footer">
          Don't have an account? <Link to="/signup">Create one</Link>
        </p>
      </div>
    </div>
  );
}
