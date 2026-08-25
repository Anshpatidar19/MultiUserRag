import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { supabase } from "../api/supabase";
import { ShieldIcon } from "../components/Icons";

export default function Signup() {
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    if (password.length < 6) {
      setError("Password must be at least 6 characters.");
      return;
    }
    if (password !== confirm) {
      setError("Passwords don't match.");
      return;
    }
    setLoading(true);
    const { error } = await supabase.auth.signUp({
      email,
      password,
      options: { data: { full_name: fullName } },
    });
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
        <h1 className="auth-title">Create your account</h1>
        <p className="auth-subtitle">
          Every account gets its own private, isolated knowledge base — no one else can see your documents or chats.
        </p>

        <form onSubmit={handleSubmit}>
          <div className="field">
            <label>Full name</label>
            <input value={fullName} onChange={(e) => setFullName(e.target.value)} placeholder="Jane Okafor" required />
          </div>
          <div className="field">
            <label>Work email</label>
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@company.com" required />
          </div>
          <div className="field">
            <label>Password</label>
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="At least 6 characters" required />
          </div>
          <div className="field">
            <label>Confirm password</label>
            <input type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} required />
          </div>

          {error && (
            <div style={{ background: "var(--danger-soft)", color: "var(--danger)", padding: "10px 14px", borderRadius: 8, fontSize: 13, marginBottom: 16 }}>
              {error}
            </div>
          )}

          <button className="btn-primary" style={{ width: "100%" }} disabled={loading} type="submit">
            {loading ? "Creating account…" : "Create account"}
          </button>
        </form>

        <p className="auth-footer">
          Already have an account? <Link to="/login">Sign in</Link>
        </p>
      </div>
    </div>
  );
}
