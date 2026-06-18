import { FormEvent, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { UserSettingsPublic, getSettings, updateSettings } from '../api';

export function SettingsPage() {
  const [settings, setSettings] = useState<UserSettingsPublic | null>(null);
  const [llmApiUrl, setLlmApiUrl] = useState('');
  const [llmModel, setLlmModel] = useState('');
  const [llmApiKey, setLlmApiKey] = useState('');
  const [embeddingApiUrl, setEmbeddingApiUrl] = useState('');
  const [embeddingModel, setEmbeddingModel] = useState('');
  const [embeddingApiKey, setEmbeddingApiKey] = useState('');
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getSettings()
      .then((data) => {
        setSettings(data);
        setLlmApiUrl(data.llm_api_url ?? '');
        setLlmModel(data.llm_model ?? '');
        setEmbeddingApiUrl(data.embedding_api_url ?? '');
        setEmbeddingModel(data.embedding_model ?? '');
      })
      .catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, []);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setMessage(null);
    setError(null);
    try {
      const updated = await updateSettings({
        llm_api_url: llmApiUrl || null,
        llm_model: llmModel || null,
        llm_api_key: llmApiKey || null,
        embedding_api_url: embeddingApiUrl || null,
        embedding_model: embeddingModel || null,
        embedding_api_key: embeddingApiKey || null,
      });
      setSettings(updated);
      setLlmApiKey('');
      setEmbeddingApiKey('');
      setMessage('Settings saved.');
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <main className="shell">
      <section className="panel">
        <div className="panelHeader">
          <div>
            <p className="eyebrow">Account</p>
            <h1>LLM settings</h1>
          </div>
          <Link className="secondary inlineBtn" to="/">
            Back to chat
          </Link>
        </div>
        <p className="subtitle">
          Chat uses your personal LLM key and model. Embeddings fall back to your embedding key or LLM key.
        </p>
        {settings ? (
          <p className="muted">
            Current keys: LLM {settings.has_llm_api_key ? settings.llm_api_key_masked : 'not set'} | Embedding{' '}
            {settings.has_embedding_api_key ? settings.embedding_api_key_masked : 'not set'}
          </p>
        ) : null}
        <form className="stackForm" onSubmit={handleSubmit}>
          <label>
            LLM API URL
            <input value={llmApiUrl} onChange={(event) => setLlmApiUrl(event.target.value)} />
          </label>
          <label>
            LLM model
            <input value={llmModel} onChange={(event) => setLlmModel(event.target.value)} />
          </label>
          <label>
            LLM API key
            <input type="password" value={llmApiKey} onChange={(event) => setLlmApiKey(event.target.value)} />
          </label>
          <label>
            Embedding API URL
            <input value={embeddingApiUrl} onChange={(event) => setEmbeddingApiUrl(event.target.value)} />
          </label>
          <label>
            Embedding model
            <input value={embeddingModel} onChange={(event) => setEmbeddingModel(event.target.value)} />
          </label>
          <label>
            Embedding API key
            <input type="password" value={embeddingApiKey} onChange={(event) => setEmbeddingApiKey(event.target.value)} />
          </label>
          <button type="submit">Save settings</button>
        </form>
        {message ? <p className="okText">{message}</p> : null}
        {error ? <p className="errorText">{error}</p> : null}
      </section>
    </main>
  );
}
