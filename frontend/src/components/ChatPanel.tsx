import { FormEvent, useMemo, useRef, useState } from 'react';
import { ChatResponse, DocumentInfo, HealthResponse, askQuestion } from '../api';
import { FormattedContent } from '../formattedContent';

const HISTORY_KEY = 'srbs_chat_history';
const MAX_HISTORY = 20;

export type ChatHistoryItem = {
  question: string;
  answer: string;
  at: string;
};

type Props = {
  health: HealthResponse | null;
  documents: DocumentInfo[];
  onToast: (kind: 'ok' | 'error' | 'info', text: string) => void;
  onChatChange?: (chat: ChatResponse | null) => void;
  onQuestionChange?: (question: string) => void;
};

function loadHistory(): ChatHistoryItem[] {
  try {
    const raw = localStorage.getItem(HISTORY_KEY);
    if (!raw) {
      return [];
    }
    return JSON.parse(raw) as ChatHistoryItem[];
  } catch {
    return [];
  }
}

function saveHistory(items: ChatHistoryItem[]) {
  localStorage.setItem(HISTORY_KEY, JSON.stringify(items.slice(0, MAX_HISTORY)));
}

export function ChatPanel({ health, documents, onToast, onChatChange, onQuestionChange }: Props) {
  const [question, setQuestion] = useState('');
  const [chat, setChat] = useState<ChatResponse | null>(null);
  const [history, setHistory] = useState<ChatHistoryItem[]>(() => loadHistory());
  const [sessionId, setSessionId] = useState<string | undefined>(undefined);
  const [isAsking, setIsAsking] = useState(false);
  const [elapsedSec, setElapsedSec] = useState(0);
  const abortRef = useRef<AbortController | null>(null);
  const timerRef = useRef<number | null>(null);

  const suggestions = useMemo(() => {
    if (!documents.length) {
      return [];
    }
    return ['Summarize all documents', 'What are the main topics?', 'List key definitions'];
  }, [documents]);

  function stopTimer() {
    if (timerRef.current !== null) {
      window.clearInterval(timerRef.current);
      timerRef.current = null;
    }
    setElapsedSec(0);
  }

  function cancelAsk() {
    abortRef.current?.abort();
    abortRef.current = null;
    setIsAsking(false);
    stopTimer();
  }

  function setChatState(next: ChatResponse | null) {
    setChat(next);
    onChatChange?.(next);
  }

  async function handleAsk(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = question.trim();
    if (!trimmed || isAsking) {
      return;
    }
    setIsAsking(true);
    stopTimer();
    const controller = new AbortController();
    abortRef.current = controller;
    timerRef.current = window.setInterval(() => setElapsedSec((s) => s + 1), 1000);
    try {
      const response = await askQuestion(trimmed, sessionId, controller.signal);
      setSessionId(response.session_id);
      setChatState(response);
      const entry: ChatHistoryItem = { question: trimmed, answer: response.answer, at: new Date().toISOString() };
      const next = [entry, ...history].slice(0, MAX_HISTORY);
      setHistory(next);
      saveHistory(next);
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') {
        onToast('info', 'Request cancelled.');
        return;
      }
      onToast('error', error instanceof Error ? error.message : String(error));
    } finally {
      setIsAsking(false);
      abortRef.current = null;
      stopTimer();
    }
  }

  function restoreHistory(item: ChatHistoryItem) {
    setQuestion(item.question);
    setChatState({
      answer: item.answer,
      matches: [],
      session_id: sessionId ?? '',
      index_ready: health?.index_ready ?? false,
      index_chunk_count: health?.rag_chunk_count ?? 0,
      index_error: health?.index_error ?? null,
    });
  }

  async function copyAnswer() {
    if (!chat?.answer) {
      return;
    }
    await navigator.clipboard.writeText(chat.answer);
    onToast('ok', 'Answer copied.');
  }

  return (
    <div className="panel">
      <div className="panelHeader">
        <h2>Ask</h2>
        <span>{health?.rag_chunk_count ?? 0} chunks</span>
      </div>
      <form onSubmit={handleAsk} className="chatForm">
        <textarea
          value={question}
          onChange={(event) => {
            setQuestion(event.currentTarget.value);
            onQuestionChange?.(event.currentTarget.value);
          }}
          onKeyDown={(event) => {
            if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
              event.currentTarget.form?.requestSubmit();
            }
          }}
          placeholder="Ask a question about the indexed documents..."
          rows={5}
        />
        <div className="chatActions">
          <button type="submit" disabled={isAsking || !question.trim()}>
            {isAsking ? `Thinking... ${elapsedSec}s` : 'Ask RAG'}
          </button>
          {isAsking ? (
            <button type="button" className="secondary inlineBtn" onClick={cancelAsk}>
              Cancel
            </button>
          ) : null}
        </div>
      </form>

      {!chat && suggestions.length ? (
        <div className="suggestions">
          {suggestions.map((item) => (
            <button key={item} type="button" className="chip" onClick={() => setQuestion(item)}>
              {item}
            </button>
          ))}
        </div>
      ) : null}

      {history.length ? (
        <div className="history">
          <h4>Recent</h4>
          {history.slice(0, 5).map((item) => (
            <button
              key={item.at + item.question}
              type="button"
              className="historyItem"
              onClick={() => restoreHistory(item)}
            >
              {item.question}
            </button>
          ))}
        </div>
      ) : null}

      {chat ? (
        <div className="answer">
          <div className="answerHeader">
            <h3>Answer</h3>
            <button type="button" className="secondary inlineBtn" onClick={copyAnswer}>
              Copy
            </button>
          </div>
          <div className="answerBody">
            <FormattedContent text={chat.answer} />
          </div>
          {chat.index_error ? <p className="errorText">Index warning: {chat.index_error}</p> : null}
        </div>
      ) : null}
    </div>
  );
}
