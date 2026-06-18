import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ChatResponse, HealthResponse, cancelIndexing, getHealth, getSettings, listDocuments } from '../api';
import { useAuth } from '../auth/AuthProvider';
import { ChatPanel } from '../components/ChatPanel';
import { DocumentsPanel } from '../components/DocumentsPanel';
import { OnboardingWizard } from '../components/OnboardingWizard';
import { SourcesPanel } from '../components/SourcesPanel';
import { StatusCard } from '../components/StatusCard';
import { ToastStack } from '../components/ToastStack';
import { useToasts } from '../hooks/useToasts';

export function HomePage() {
  const { user, logout } = useAuth();
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [documents, setDocuments] = useState<Awaited<ReturnType<typeof listDocuments>>>([]);
  const [chat, setChat] = useState<ChatResponse | null>(null);
  const [question, setQuestion] = useState('');
  const [showOnboarding, setShowOnboarding] = useState(false);
  const [isCancelling, setIsCancelling] = useState(false);
  const { toasts, push, dismiss } = useToasts();

  async function refreshStatus() {
    const [nextHealth, nextDocuments] = await Promise.all([getHealth(), listDocuments()]);
    setHealth(nextHealth);
    setDocuments(nextDocuments);
  }

  useEffect(() => {
    getSettings()
      .then((settings) => setShowOnboarding(!settings.has_llm_api_key))
      .catch(() => undefined);
    refreshStatus().catch((error: unknown) => {
      push('error', error instanceof Error ? error.message : String(error));
    });
    const id = window.setInterval(() => {
      refreshStatus().catch(() => undefined);
    }, 5000);
    return () => window.clearInterval(id);
  }, [push]);

  async function handleCancelIndexing() {
    setIsCancelling(true);
    try {
      const message = await cancelIndexing();
      push('info', message);
      await refreshStatus();
    } catch (error: unknown) {
      push('error', error instanceof Error ? error.message : String(error));
    } finally {
      setIsCancelling(false);
    }
  }

  return (
    <main className="shell">
      <section className="hero">
        <div>
          <p className="eyebrow">Universal RAG MVP</p>
          <h1>Contextual Q&A over uploaded documents</h1>
          <p className="subtitle">
            Signed in as {user?.display_name || user?.email}. Upload PDF, DOCX or TXT files, index them, then ask questions with RAG sources.
          </p>
          <div className="heroLinks">
            <Link to="/settings">Settings</Link>
            <Link to="/developer">Developer</Link>
            <button type="button" className="secondary inlineBtn" onClick={() => logout().catch(() => undefined)}>
              Logout
            </button>
          </div>
        </div>
        <StatusCard
          health={health}
          onCancelIndexing={() => {
            void handleCancelIndexing();
          }}
          isCancelling={isCancelling}
        />
      </section>

      <ToastStack toasts={toasts} onDismiss={dismiss} />

      {showOnboarding ? <OnboardingWizard onComplete={() => setShowOnboarding(false)} /> : null}

      <section className="grid">
        <ChatPanel
          health={health}
          documents={documents}
          onToast={push}
          onChatChange={setChat}
          onQuestionChange={setQuestion}
        />
        <DocumentsPanel documents={documents} onRefresh={refreshStatus} onToast={push} />
      </section>

      <SourcesPanel chat={chat} question={question} />
    </main>
  );
}
