import { HealthResponse } from '../api';
import { useState } from 'react';

type Props = {
  health: HealthResponse | null;
  onCancelIndexing?: () => void;
  isCancelling?: boolean;
};

export function StatusCard({ health, onCancelIndexing, isCancelling = false }: Props) {
  const [expanded, setExpanded] = useState(false);

  if (!health) {
    return <aside className="statusCard">Loading status...</aside>;
  }
  const progress =
    health.document_count > 0
      ? `${health.document_count - health.pending_count}/${health.document_count} indexed`
      : 'no documents';
  const indexingActive = health.indexing_count > 0 || (health.queue_pending ?? 0) > 0;
  return (
    <aside className="statusCard">
      <span className={`statusDot ${health.status}`} />
      <div>
        <strong>{health.status}</strong>
        <p>
          {health.document_count} docs, {health.rag_chunk_count} chunks
        </p>
        <p>{health.index_ready ? 'Index ready' : 'Indexing or waiting for documents'}</p>
        {health.indexing_count > 0 ? <p className="muted">{progress}</p> : null}
        {health.queue_pending ? <p className="muted">Queue pending: {health.queue_pending}</p> : null}
        {indexingActive && onCancelIndexing ? (
          <button
            type="button"
            className="secondary inlineBtn"
            disabled={isCancelling}
            onClick={onCancelIndexing}
          >
            {isCancelling ? 'Cancelling...' : 'Cancel indexing'}
          </button>
        ) : null}
        {health.components?.length ? (
          <button type="button" className="secondary inlineBtn" onClick={() => setExpanded((value) => !value)}>
            {expanded ? 'Hide components' : 'Show components'}
          </button>
        ) : null}
        {expanded && health.components ? (
          <ul className="componentList">
            {health.components.map((component) => (
              <li key={component.name}>
                <strong>{component.name}</strong> — {component.status} ({component.latency_ms}ms)
                {component.message ? <span className="muted"> · {component.message}</span> : null}
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    </aside>
  );
}
