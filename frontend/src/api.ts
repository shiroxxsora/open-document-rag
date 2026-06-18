import { parseApiError } from './utils/apiError';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api/v1';

export type HealthComponent = {
  name: string;
  status: string;
  latency_ms: number;
  message: string | null;
};

export type HealthResponse = {
  status: string;
  overall?: string;
  index_ready: boolean;
  indexing_started: boolean;
  indexing_done: boolean;
  rag_chunk_count: number;
  document_count: number;
  indexing_count: number;
  pending_count: number;
  index_error: string | null;
  queue_pending?: number;
  queue_failed?: number;
  components?: HealthComponent[];
};

export type DocumentInfo = {
  document_id: string;
  file_name: string;
  content_hash: string | null;
  chunk_count: number;
  status: string;
  error: string | null;
  created_at: string | null;
  updated_at: string | null;
};

export type RAGMatch = {
  document_id: string;
  document_name: string;
  content: string;
  source_page: string | null;
  chunk_index: number;
  score: number;
};

export type ChatResponse = {
  answer: string;
  matches: RAGMatch[];
  session_id: string;
  index_ready: boolean;
  index_chunk_count: number;
  index_error: string | null;
};

export type MeResponse = {
  user_id: string;
  email: string;
  display_name: string | null;
};

export type UserSettingsPublic = {
  llm_api_url: string | null;
  llm_model: string | null;
  llm_api_key_masked: string | null;
  embedding_api_url: string | null;
  embedding_model: string | null;
  embedding_api_key_masked: string | null;
  has_llm_api_key: boolean;
  has_embedding_api_key: boolean;
};

export type ApiApplication = {
  app_id: string;
  name: string;
  description: string | null;
  webhook_url: string | null;
  created_at: string;
};

export type ApiTokenInfo = {
  token_id: string;
  app_id: string;
  token_prefix: string;
  scopes: string[];
  label: string | null;
  expires_at: string | null;
  revoked_at: string | null;
  created_at: string;
  last_used_at: string | null;
};

export type ApiTokenCreated = ApiTokenInfo & {
  raw_token: string;
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    credentials: 'include',
    ...init,
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(parseApiError(text, response.status));
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return response.json() as Promise<T>;
}

export function getHealth(): Promise<HealthResponse> {
  return request<HealthResponse>('/health');
}

export function getMe(): Promise<MeResponse> {
  return request<MeResponse>('/me');
}

export function devLogin(email: string, displayName?: string): Promise<MeResponse> {
  return request<MeResponse>('/auth/dev/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, display_name: displayName }),
  });
}

export function logout(): Promise<{ status: string }> {
  return request<{ status: string }>('/auth/logout', { method: 'POST' });
}

export function getSettings(): Promise<UserSettingsPublic> {
  return request<UserSettingsPublic>('/me/settings');
}

export function updateSettings(body: Record<string, string | boolean | null>): Promise<UserSettingsPublic> {
  return request<UserSettingsPublic>('/me/settings', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

export async function listDocuments(): Promise<DocumentInfo[]> {
  const response = await request<{ documents: DocumentInfo[] }>('/documents');
  return response.documents;
}

export async function askQuestion(
  question: string,
  sessionId?: string,
  signal?: AbortSignal,
): Promise<ChatResponse> {
  return request<ChatResponse>('/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, session_id: sessionId ?? null }),
    signal,
  });
}

export async function uploadDocuments(files: FileList): Promise<string> {
  const formData = new FormData();
  Array.from(files).forEach((file) => formData.append('files', file));
  const response = await request<{ message: string }>('/documents/upload', {
    method: 'POST',
    body: formData,
  });
  return response.message;
}

export async function startReindex(): Promise<string> {
  const response = await request<{ message: string }>('/reindex', { method: 'POST' });
  return response.message;
}

export async function cancelIndexing(): Promise<string> {
  const response = await request<{ message: string }>('/cancel-indexing', { method: 'POST' });
  return response.message;
}

export async function cancelDocumentIndexing(documentId: string): Promise<string> {
  const response = await request<{ message: string }>(
    `/documents/${encodeURIComponent(documentId)}/cancel-indexing`,
    { method: 'POST' },
  );
  return response.message;
}

export async function deleteDocument(documentId: string): Promise<string> {
  const response = await request<{ message: string }>(
    `/documents/${encodeURIComponent(documentId)}`,
    { method: 'DELETE' },
  );
  return response.message;
}

export async function reindexDocument(documentId: string): Promise<string> {
  const response = await request<{ message: string }>(
    `/documents/${encodeURIComponent(documentId)}/reindex`,
    { method: 'POST' },
  );
  return response.message;
}

export function listApplications(): Promise<ApiApplication[]> {
  return request<ApiApplication[]>('/developer/applications');
}

export function createApplication(name: string): Promise<ApiApplication> {
  return request<ApiApplication>('/developer/applications', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  });
}

export function listTokens(appId: string): Promise<ApiTokenInfo[]> {
  return request<ApiTokenInfo[]>(`/developer/applications/${encodeURIComponent(appId)}/tokens`);
}

export function createToken(appId: string, scopes: string[]): Promise<ApiTokenCreated> {
  return request<ApiTokenCreated>(`/developer/applications/${encodeURIComponent(appId)}/tokens`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ scopes }),
  });
}

export function revokeToken(tokenId: string): Promise<void> {
  return request<void>(`/developer/tokens/${encodeURIComponent(tokenId)}`, { method: 'DELETE' });
}
