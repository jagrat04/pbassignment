import { useState } from "react";
import { ApiError } from "../api";
import { useAuth } from "../auth";
import { Field } from "../components";

export function Login() {
  const { login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<ApiError | Error | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email, password);
    } catch (err) {
      setError(err as Error);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page" style={{ maxWidth: 420, paddingTop: 64 }}>
      <h1>Peblo CMS</h1>
      <p className="sub">Sign in to manage shows and publish the catalogue.</p>

      <form className="panel" onSubmit={submit}>
        {error && (
          <div className="notice error">
            <strong>{error instanceof ApiError ? error.problem : error.message}</strong>
            {error instanceof ApiError && error.fix && <p className="fix">{error.fix}</p>}
          </div>
        )}
        <Field label="Email">
          <input
            type="email"
            value={email}
            autoComplete="username"
            required
            onChange={(e) => setEmail(e.target.value)}
          />
        </Field>
        <Field label="Password">
          <input
            type="password"
            value={password}
            autoComplete="current-password"
            required
            onChange={(e) => setPassword(e.target.value)}
          />
        </Field>
        <button className="primary" disabled={busy} style={{ width: "100%" }}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>

      <div className="notice info">
        <strong>Demo accounts</strong>
        <p className="fix">
          <code>admin@peblo.test</code> / <code>peblo-admin</code> — can publish.
          <br />
          <code>editor@peblo.test</code> / <code>peblo-editor</code> — can edit but not publish.
        </p>
      </div>
    </div>
  );
}
