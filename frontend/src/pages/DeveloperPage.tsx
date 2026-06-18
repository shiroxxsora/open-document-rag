import { FormEvent, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  ApiApplication,
  ApiTokenCreated,
  ApiTokenInfo,
  createApplication,
  createToken,
  listApplications,
  listTokens,
  revokeToken,
} from '../api';

const SCOPES = ['chat:write', 'documents:read', 'documents:write', 'settings:read'];

export function DeveloperPage() {
  const [apps, setApps] = useState<ApiApplication[]>([]);
  const [selectedAppId, setSelectedAppId] = useState<string>('');
  const [tokens, setTokens] = useState<ApiTokenInfo[]>([]);
  const [appName, setAppName] = useState('');
  const [selectedScopes, setSelectedScopes] = useState<string[]>(['chat:write']);
  const [createdToken, setCreatedToken] = useState<ApiTokenCreated | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function refreshApps() {
    const next = await listApplications();
    setApps(next);
    if (!selectedAppId && next.length) {
      setSelectedAppId(next[0].app_id);
    }
  }

  async function refreshTokens(appId: string) {
    if (!appId) {
      setTokens([]);
      return;
    }
    setTokens(await listTokens(appId));
  }

  useEffect(() => {
    refreshApps().catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, []);

  useEffect(() => {
    refreshTokens(selectedAppId).catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, [selectedAppId]);

  async function handleCreateApp(event: FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      await createApplication(appName.trim());
      setAppName('');
      await refreshApps();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function handleCreateToken(event: FormEvent) {
    event.preventDefault();
    if (!selectedAppId) {
      return;
    }
    setError(null);
    try {
      const token = await createToken(selectedAppId, selectedScopes);
      setCreatedToken(token);
      await refreshTokens(selectedAppId);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  function toggleScope(scope: string) {
    setSelectedScopes((current) =>
      current.includes(scope) ? current.filter((item) => item !== scope) : [...current, scope],
    );
  }

  return (
    <main className="shell">
      <section className="panel">
        <div className="panelHeader">
          <div>
            <p className="eyebrow">Developer</p>
            <h1>API applications</h1>
          </div>
          <Link className="secondary inlineBtn" to="/">
            Back to chat
          </Link>
        </div>
        <form className="stackForm" onSubmit={handleCreateApp}>
          <label>
            Application name
            <input value={appName} onChange={(event) => setAppName(event.target.value)} />
          </label>
          <button type="submit" disabled={!appName.trim()}>
            Create application
          </button>
        </form>

        <div className="stackForm">
          <label>
            Select application
            <select value={selectedAppId} onChange={(event) => setSelectedAppId(event.target.value)}>
              <option value="">Choose...</option>
              {apps.map((app) => (
                <option key={app.app_id} value={app.app_id}>
                  {app.name}
                </option>
              ))}
            </select>
          </label>
        </div>

        {selectedAppId ? (
          <form className="stackForm" onSubmit={handleCreateToken}>
            <fieldset>
              <legend>Token scopes</legend>
              {SCOPES.map((scope) => (
                <label key={scope} className="checkboxRow">
                  <input
                    type="checkbox"
                    checked={selectedScopes.includes(scope)}
                    onChange={() => toggleScope(scope)}
                  />
                  {scope}
                </label>
              ))}
            </fieldset>
            <button type="submit" disabled={!selectedScopes.length}>
              Create token
            </button>
          </form>
        ) : null}

        {createdToken ? (
          <div className="tokenReveal">
            <p className="okText">Copy this token now. It will not be shown again.</p>
            <code>{createdToken.raw_token}</code>
          </div>
        ) : null}

        {tokens.length ? (
          <div className="history">
            <h4>Tokens</h4>
            {tokens.map((token) => (
              <div key={token.token_id} className="documentCard">
                <strong>{token.token_prefix}...</strong>
                <p>{token.scopes.join(', ')}</p>
                {token.revoked_at ? (
                  <p className="muted">Revoked</p>
                ) : (
                  <button type="button" className="secondary inlineBtn" onClick={() => revokeToken(token.token_id).then(() => refreshTokens(selectedAppId))}>
                    Revoke
                  </button>
                )}
              </div>
            ))}
          </div>
        ) : null}

        {error ? <p className="errorText">{error}</p> : null}
      </section>
    </main>
  );
}
