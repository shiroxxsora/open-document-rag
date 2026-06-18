import { ChangeEvent, DragEvent, useMemo, useState } from 'react';
import {
  DocumentInfo,
  cancelDocumentIndexing,
  cancelIndexing,
  deleteDocument,
  reindexDocument,
  startReindex,
  uploadDocuments,
} from '../api';
import { FormattedContent } from '../formattedContent';
import { formatRelativeTime } from '../utils/formatRelativeTime';

type Props = {
  documents: DocumentInfo[];
  onRefresh: () => Promise<void>;
  onToast: (kind: 'ok' | 'error' | 'info', text: string) => void;
};

export function DocumentsPanel({ documents, onRefresh, onToast }: Props) {
  const [filter, setFilter] = useState('');
  const [isUploading, setIsUploading] = useState(false);
  const [isDragging, setIsDragging] = useState(false);

  const filtered = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q) {
      return documents;
    }
    return documents.filter(
      (doc) => doc.file_name.toLowerCase().includes(q) || doc.document_id.toLowerCase().includes(q),
    );
  }, [documents, filter]);

  async function handleFiles(files: FileList | null) {
    if (!files || files.length === 0) {
      return;
    }
    setIsUploading(true);
    try {
      const message = await uploadDocuments(files);
      onToast('ok', message);
      await onRefresh();
    } catch (error) {
      onToast('error', error instanceof Error ? error.message : String(error));
    } finally {
      setIsUploading(false);
    }
  }

  async function handleUpload(event: ChangeEvent<HTMLInputElement>) {
    await handleFiles(event.currentTarget.files);
    event.currentTarget.value = '';
  }

  function onDrop(event: DragEvent<HTMLLabelElement>) {
    event.preventDefault();
    setIsDragging(false);
    void handleFiles(event.dataTransfer.files);
  }

  async function handleDelete(doc: DocumentInfo) {
    if (!window.confirm(`Delete "${doc.file_name}"?`)) {
      return;
    }
    try {
      const message = await deleteDocument(doc.document_id);
      onToast('ok', message);
      await onRefresh();
    } catch (error) {
      onToast('error', error instanceof Error ? error.message : String(error));
    }
  }

  async function handleReindexOne(doc: DocumentInfo) {
    try {
      const message = await reindexDocument(doc.document_id);
      onToast('info', message);
      await onRefresh();
    } catch (error) {
      onToast('error', error instanceof Error ? error.message : String(error));
    }
  }

  async function handleReindexAll() {
    try {
      const message = await startReindex();
      onToast('info', message);
      await onRefresh();
    } catch (error) {
      onToast('error', error instanceof Error ? error.message : String(error));
    }
  }

  async function handleCancelOne(doc: DocumentInfo) {
    try {
      const message = await cancelDocumentIndexing(doc.document_id);
      onToast('info', message);
      await onRefresh();
    } catch (error) {
      onToast('error', error instanceof Error ? error.message : String(error));
    }
  }

  const hasActiveIndexing = documents.some(
    (doc) => doc.status === 'pending' || doc.status === 'indexing',
  );

  return (
    <div className="panel">
      <div className="panelHeader">
        <h2>Upload</h2>
        <span>PDF, DOCX, TXT</span>
      </div>
      <label
        className={`dropzone ${isDragging ? 'dragging' : ''}`}
        onDragOver={(event) => {
          event.preventDefault();
          setIsDragging(true);
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={onDrop}
      >
        <input type="file" multiple accept=".pdf,.docx,.txt" onChange={handleUpload} disabled={isUploading} />
        <strong>{isUploading ? 'Uploading...' : 'Choose or drop documents'}</strong>
        <span>Files are indexed in the background after upload.</span>
      </label>
      <button className="secondary" onClick={handleReindexAll}>
        Reindex all documents
      </button>
      {hasActiveIndexing ? (
        <button
          type="button"
          className="secondary"
          onClick={() => {
            void cancelIndexing()
              .then(async (message) => {
                onToast('info', message);
                await onRefresh();
              })
              .catch((error: unknown) => {
                onToast('error', error instanceof Error ? error.message : String(error));
              });
          }}
        >
          Cancel indexing
        </button>
      ) : null}

      <div className="documents">
        <div className="documentsHeader">
          <h3>Documents</h3>
          <input
            className="docFilter"
            placeholder="Filter..."
            value={filter}
            onChange={(event) => setFilter(event.currentTarget.value)}
          />
        </div>
        {filtered.length === 0 ? <p className="muted">No documents uploaded yet.</p> : null}
        {filtered.map((doc) => (
          <article key={doc.document_id} className="documentCard">
            <div className="documentMain">
              <strong className="documentTitle">{doc.file_name}</strong>
              {doc.document_id !== doc.file_name ? (
                <code className="documentId" title={doc.document_id}>
                  {doc.document_id}
                </code>
              ) : null}
              {doc.updated_at ? <span className="docTime">{formatRelativeTime(doc.updated_at)}</span> : null}
            </div>
            <div className="docMeta">
              <span className={`badge ${doc.status}`}>{doc.status}</span>
              <span className="chunkCount">{doc.chunk_count} chunks</span>
              <div className="docActions">
                {doc.status === 'pending' || doc.status === 'indexing' ? (
                  <button type="button" className="secondary inlineBtn" onClick={() => handleCancelOne(doc)}>
                    Cancel
                  </button>
                ) : null}
                <button type="button" className="secondary inlineBtn" onClick={() => handleReindexOne(doc)}>
                  Reindex
                </button>
                <button type="button" className="danger inlineBtn" onClick={() => handleDelete(doc)}>
                  Delete
                </button>
              </div>
            </div>
            {doc.error ? (
              <div className="documentError">
                <FormattedContent text={doc.error} />
                <button type="button" className="secondary inlineBtn" onClick={() => handleReindexOne(doc)}>
                  Retry
                </button>
              </div>
            ) : null}
          </article>
        ))}
      </div>
    </div>
  );
}
