import os
from dataclasses import dataclass
from pathlib import Path


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _csv_env(name: str, default: str) -> list[str]:
    raw = os.getenv(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    postgres_dsn: str
    docs_dir: Path
    page_cache_dir: Path
    allowed_origins: list[str]
    max_upload_mb: int

    llm_api_url: str
    llm_api_key: str
    llm_model: str
    llm_timeout_sec: int

    embedding_api_url: str
    embedding_model: str
    embedding_dim: int
    embedding_timeout_sec: int
    embedding_batch_size: int

    rag_top_k: int
    rag_search_limit: int
    rag_context_budget_chars: int
    rag_prompt_max_chunk_chars: int
    rag_max_distance: float
    rag_fallback_on_empty: bool
    rag_fallback_max_distance: float
    rag_neighbor_window: int
    rerank_vector_weight: float
    rerank_lexical_weight: float
    rerank_min_lexical_overlap: float

    chunk_size: int
    chunk_overlap: int
    chunk_min_merge_chars: int

    prepare_page_engine: str
    prepare_workers: int
    tesseract_lang: str
    vl_api_url: str
    vl_api_key: str
    vl_model: str
    vl_timeout_sec: int
    vl_zoom: float
    vl_min_quality: float

    job_max_attempts: int
    job_worker_poll_interval_sec: float
    job_worker_concurrency: int
    job_worker_id: str

    default_max_chat_per_day: int
    default_max_storage_mb: int
    default_max_documents: int
    default_max_concurrent_jobs: int

    health_worker_stale_sec: int
    health_queue_stuck_sec: int

    auth_secret_key: str
    auth_mode: str
    auth_cookie_secure: bool
    google_client_id: str
    google_client_secret: str
    github_client_id: str
    github_client_secret: str
    oauth_redirect_base: str
    jwt_expire_minutes: int
    chat_history_limit: int


def load_settings() -> Settings:
    docs_dir = Path(os.getenv("RAG_DOCS_DIR", "/data/docs"))
    page_cache_dir = Path(os.getenv("RAG_PAGE_CACHE_DIR", "/data/page_cache"))
    llm_model = os.getenv("LLM_MODEL", "gpt-4o-mini")
    embedding_url = os.getenv("EMBEDDING_API_URL", "https://api.openai.com/v1/embeddings").strip()
    page_engine = os.getenv("PREPARE_PAGE_ENGINE", "auto").strip().lower()
    if page_engine not in {"auto", "pdf_text", "tesseract", "vl"}:
        page_engine = "auto"

    return Settings(
        postgres_dsn=os.getenv("POSTGRES_DSN", "postgresql://postgres:postgres@postgres:5432/rag"),
        docs_dir=docs_dir,
        page_cache_dir=page_cache_dir,
        allowed_origins=_csv_env(
            "CORS_ORIGINS",
            "http://localhost:3000,http://localhost:5173,http://127.0.0.1:3000,http://127.0.0.1:5173",
        ),
        max_upload_mb=int(os.getenv("MAX_UPLOAD_MB", "100")),
        llm_api_url=os.getenv("LLM_API_URL", "https://api.openai.com/v1/chat/completions").strip(),
        llm_api_key=os.getenv("LLM_API_KEY", ""),
        llm_model=llm_model,
        llm_timeout_sec=int(os.getenv("LLM_TIMEOUT_SEC", "240")),
        embedding_api_url=embedding_url,
        embedding_model=os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"),
        embedding_dim=int(os.getenv("EMBEDDING_DIM", "1536")),
        embedding_timeout_sec=int(os.getenv("EMBEDDING_TIMEOUT_SEC", "600")),
        embedding_batch_size=max(1, int(os.getenv("EMBEDDING_BATCH_SIZE", "32"))),
        rag_top_k=int(os.getenv("RAG_TOP_K", "12")),
        rag_search_limit=int(os.getenv("RAG_SEARCH_LIMIT", "120")),
        rag_context_budget_chars=int(os.getenv("RAG_CONTEXT_BUDGET_CHARS", "24000")),
        rag_prompt_max_chunk_chars=int(os.getenv("RAG_PROMPT_MAX_CHUNK_CHARS", "3500")),
        rag_max_distance=float(os.getenv("RAG_MAX_DISTANCE", "0.65")),
        rag_fallback_on_empty=_bool_env("RAG_FALLBACK_ON_EMPTY", True),
        rag_fallback_max_distance=float(os.getenv("RAG_FALLBACK_MAX_DISTANCE", "0.78")),
        rag_neighbor_window=max(0, int(os.getenv("RAG_NEIGHBOR_WINDOW", "1"))),
        rerank_vector_weight=float(os.getenv("RERANK_VECTOR_WEIGHT", "0.85")),
        rerank_lexical_weight=float(os.getenv("RERANK_LEXICAL_WEIGHT", "0.15")),
        rerank_min_lexical_overlap=float(os.getenv("RERANK_MIN_LEXICAL_OVERLAP", "0.0")),
        chunk_size=int(os.getenv("RAG_CHUNK_SIZE", "2800")),
        chunk_overlap=int(os.getenv("RAG_CHUNK_OVERLAP", "450")),
        chunk_min_merge_chars=int(os.getenv("RAG_CHUNK_MIN_MERGE_CHARS", "300")),
        prepare_page_engine=page_engine,
        prepare_workers=max(1, int(os.getenv("PREPARE_WORKERS", "2"))),
        tesseract_lang=os.getenv("TESSERACT_LANG", "rus+eng"),
        vl_api_url=os.getenv("PREPARE_VL_API_URL", "").strip(),
        vl_api_key=os.getenv("PREPARE_VL_API_KEY", os.getenv("LLM_API_KEY", "")),
        vl_model=os.getenv("PREPARE_VL_MODEL", llm_model),
        vl_timeout_sec=int(os.getenv("PREPARE_VL_TIMEOUT", "600")),
        vl_zoom=float(os.getenv("PREPARE_VL_ZOOM", "2.5")),
        vl_min_quality=float(os.getenv("PREPARE_VL_MIN_QUALITY", "2.1")),
        job_max_attempts=max(1, int(os.getenv("JOB_MAX_ATTEMPTS", "5"))),
        job_worker_poll_interval_sec=float(os.getenv("JOB_WORKER_POLL_INTERVAL_SEC", "2.0")),
        job_worker_concurrency=max(1, int(os.getenv("JOB_WORKER_CONCURRENCY", "2"))),
        job_worker_id=os.getenv("JOB_WORKER_ID", "worker-1"),
        default_max_chat_per_day=max(1, int(os.getenv("DEFAULT_MAX_CHAT_PER_DAY", "100"))),
        default_max_storage_mb=max(1, int(os.getenv("DEFAULT_MAX_STORAGE_MB", "500"))),
        default_max_documents=max(1, int(os.getenv("DEFAULT_MAX_DOCUMENTS", "50"))),
        default_max_concurrent_jobs=max(1, int(os.getenv("DEFAULT_MAX_CONCURRENT_JOBS", "2"))),
        health_worker_stale_sec=max(10, int(os.getenv("HEALTH_WORKER_STALE_SEC", "60"))),
        health_queue_stuck_sec=max(60, int(os.getenv("HEALTH_QUEUE_STUCK_SEC", "1800"))),
        auth_secret_key=os.getenv("AUTH_SECRET_KEY", "dev-secret-change-me"),
        auth_mode=os.getenv("AUTH_MODE", "dev").strip().lower(),
        auth_cookie_secure=_bool_env("AUTH_COOKIE_SECURE", False),
        google_client_id=os.getenv("GOOGLE_CLIENT_ID", "").strip(),
        google_client_secret=os.getenv("GOOGLE_CLIENT_SECRET", "").strip(),
        github_client_id=os.getenv("GITHUB_CLIENT_ID", "").strip(),
        github_client_secret=os.getenv("GITHUB_CLIENT_SECRET", "").strip(),
        oauth_redirect_base=os.getenv("OAUTH_REDIRECT_BASE", "http://localhost:3000").strip(),
        jwt_expire_minutes=max(5, int(os.getenv("JWT_EXPIRE_MINUTES", "10080"))),
        chat_history_limit=max(2, int(os.getenv("CHAT_HISTORY_LIMIT", "10"))),
    )
