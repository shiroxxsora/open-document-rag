from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    question: str = Field(min_length=1)
    session_id: str | None = None


class RAGMatch(BaseModel):
    document_id: str
    document_name: str
    content: str
    source_page: str | None = None
    chunk_index: int
    score: float


class ChatResponse(BaseModel):
    answer: str
    matches: list[RAGMatch]
    session_id: str
    index_ready: bool
    index_chunk_count: int
    index_error: str | None = None


class DocumentInfo(BaseModel):
    document_id: str
    file_name: str
    content_hash: str | None = None
    chunk_count: int = 0
    status: str = "unknown"
    error: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class DocumentListResponse(BaseModel):
    documents: list[DocumentInfo]


class UploadResponse(BaseModel):
    status: str
    message: str
    documents: list[DocumentInfo]


class HealthComponent(BaseModel):
    name: str
    status: str
    latency_ms: int
    message: str | None = None


class HealthResponse(BaseModel):
    status: str
    overall: str = "ok"
    index_ready: bool
    indexing_started: bool
    indexing_done: bool
    rag_chunk_count: int
    document_count: int
    indexing_count: int = 0
    pending_count: int = 0
    index_error: str | None = None
    queue_pending: int = 0
    queue_failed: int = 0
    components: list[HealthComponent] = Field(default_factory=list)


class UsageSnapshot(BaseModel):
    date: str | None = None
    chat_requests: int = 0
    embedding_calls: int = 0
    upload_bytes: int = 0
    api_token_calls: int = 0


class UsageLimits(BaseModel):
    max_chat_per_day: int
    max_storage_mb: int
    max_documents: int
    max_concurrent_jobs: int


class UsageResponse(BaseModel):
    usage: UsageSnapshot
    limits: UsageLimits
    storage_used_mb: float
    document_count: int
    running_jobs: int


class UsageHistoryResponse(BaseModel):
    days: list[UsageSnapshot]


class DeleteDocumentResponse(BaseModel):
    status: str
    message: str


class ReindexDocumentResponse(BaseModel):
    status: str
    message: str


class ReindexResponse(BaseModel):
    status: str
    message: str


class CancelIndexingResponse(BaseModel):
    status: str
    message: str
    cancelled_jobs: int = 0
    cancelled_documents: int = 0


class DevLoginRequest(BaseModel):
    email: str
    display_name: str | None = None


class MeResponse(BaseModel):
    user_id: str
    email: str
    display_name: str | None = None


class UserSettingsUpdateRequest(BaseModel):
    llm_api_url: str | None = None
    llm_model: str | None = None
    llm_api_key: str | None = None
    clear_llm_api_key: bool = False
    embedding_api_url: str | None = None
    embedding_model: str | None = None
    embedding_api_key: str | None = None
    clear_embedding_api_key: bool = False


class UserSettingsPublicResponse(BaseModel):
    llm_api_url: str | None = None
    llm_model: str | None = None
    llm_api_key_masked: str | None = None
    embedding_api_url: str | None = None
    embedding_model: str | None = None
    embedding_api_key_masked: str | None = None
    has_llm_api_key: bool = False
    has_embedding_api_key: bool = False


class MeExportResponse(BaseModel):
    filename: str


class ApiApplicationCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None
    webhook_url: str | None = None


class ApiApplicationResponse(BaseModel):
    app_id: str
    name: str
    description: str | None = None
    webhook_url: str | None = None
    created_at: str


class ApiTokenCreateRequest(BaseModel):
    scopes: list[str] = Field(min_length=1)
    label: str | None = None


class ApiTokenResponse(BaseModel):
    token_id: str
    app_id: str
    token_prefix: str
    scopes: list[str]
    label: str | None = None
    expires_at: str | None = None
    revoked_at: str | None = None
    created_at: str
    last_used_at: str | None = None


class ApiTokenCreatedResponse(ApiTokenResponse):
    raw_token: str
