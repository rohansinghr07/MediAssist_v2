import { useState } from "react";
import { Alert, Button, Form } from "react-bootstrap";
import { api, setToken } from "../api.js";
import { Logo, LoginArt } from "../components/Art.jsx";

export default function Login({ onLogin }) {
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const res = await api("/auth/login", { method: "POST", body: { username, password } });
      setToken(res.token);
      onLogin();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-wrap">
      <div className="login-art">
        <div className="text-center">
          <LoginArt />
          <h3 className="mt-3 mb-1">AI clinic assistant</h3>
          <p className="text-muted mb-0">Telegram bookings, reminders, issues and emergency alerts – in one place.</p>
        </div>
      </div>
      <div className="login-form">
        <div className="login-card">
          <div className="d-flex align-items-center gap-2 mb-4">
            <Logo />
            <div>
              <div className="brand-name">MediAssist</div>
              <div className="brand-sub">City Clinic, Kota</div>
            </div>
          </div>
          <h3 className="mb-1">Welcome back</h3>
          <p className="text-muted mb-4">Sign in to the clinic staff dashboard.</p>
          {error && <Alert variant="danger" className="py-2 small">{error}</Alert>}
          <Form onSubmit={submit}>
            <Form.Group className="mb-3">
              <Form.Label className="small fw-semibold">Username</Form.Label>
              <Form.Control size="lg" value={username} onChange={(e) => setUsername(e.target.value)} autoFocus />
            </Form.Group>
            <Form.Group className="mb-4">
              <Form.Label className="small fw-semibold">Password</Form.Label>
              <Form.Control size="lg" type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
            </Form.Group>
            <Button type="submit" size="lg" className="w-100" disabled={busy}>
              {busy ? "Signing in…" : "Sign in"}
            </Button>
          </Form>
          <a href="/" className="d-inline-block mt-4 small text-decoration-none"><i className="bi bi-arrow-left me-1" />Back to clinic website</a>
        </div>
      </div>
    </div>
  );
}
