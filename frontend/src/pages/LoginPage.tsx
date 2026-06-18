import { FormEvent, useState } from 'react';
import { Link, Navigate } from 'react-router-dom';
import { useAuth } from '../auth/AuthProvider';

export function LoginPage() {
  const { user, loginDev } = useAuth();
  const [email, setEmail] = useState('dev@example.com');
  const [displayName, setDisplayName] = useState('Developer');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  if (user) {
    return <Navigate to="/" replace />;
  }

  async function handleDevLogin(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await loginDev(email.trim(), displayName.trim() || undefined);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="shell narrow">
      <section className="panel">
        <p className="eyebrow">Sign in</p>
        <h1>Universal RAG MVP</h1>
        <p className="subtitle">Use dev login locally or OAuth providers when configured.</p>

        <form className="stackForm" onSubmit={handleDevLogin}>
          <label>
            Email
            <input value={email} onChange={(event) => setEmail(event.target.value)} />
          </label>
          <label>
            Display name
            <input value={displayName} onChange={(event) => setDisplayName(event.target.value)} />
          </label>
          <button type="submit" disabled={submitting}>
            {submitting ? 'Signing in...' : 'Dev login'}
          </button>
        </form>

        <div className="oauthButtons">
          <a className="secondary inlineBtn" href="/api/v1/auth/login/google">
            Continue with Google
          </a>
          <a className="secondary inlineBtn" href="/api/v1/auth/login/github">
            Continue with GitHub
          </a>
        </div>

        {error ? <p className="errorText">{error}</p> : null}
        <p className="muted">
          Need an account? Dev mode creates one on first login.{' '}
          <Link to="/">Back home</Link>
        </p>
      </section>
    </main>
  );
}
