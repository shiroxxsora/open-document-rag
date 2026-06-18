import os

_test_dsn = os.getenv("TEST_POSTGRES_DSN")
if _test_dsn:
    os.environ["POSTGRES_DSN"] = _test_dsn
    os.environ.setdefault("AUTH_MODE", "dev")
    os.environ.setdefault("LLM_MOCK", "1")
    os.environ.setdefault("AUTH_SECRET_KEY", "test-secret-key")

import pytest

from app.config import Settings, load_settings


@pytest.fixture(scope="session")
def test_settings() -> Settings:
    return Settings(
        postgres_dsn=os.getenv(
            "TEST_POSTGRES_DSN",
            os.getenv(
                "POSTGRES_DSN",
                "postgresql://postgres:postgres@localhost:5432/rag",
            ),
        ),
        docs_dir=load_settings().docs_dir,
        page_cache_dir=load_settings().page_cache_dir,
        allowed_origins=["http://localhost:3000"],
        max_upload_mb=10,
        llm_api_url="http://localhost:9999/v1/chat/completions",
        llm_api_key="test-key",
        llm_model="test-model",
        llm_timeout_sec=5,
        embedding_api_url="http://localhost:9999/v1/embeddings",
        embedding_model="test-embedding",
        embedding_dim=int(os.getenv("EMBEDDING_DIM", "2048")),
        embedding_timeout_sec=5,
        embedding_batch_size=4,
        rag_top_k=5,
        rag_search_limit=20,
        rag_context_budget_chars=4000,
        rag_prompt_max_chunk_chars=1000,
        rag_max_distance=0.65,
        rag_fallback_on_empty=True,
        rag_fallback_max_distance=0.78,
        rag_neighbor_window=0,
        rerank_vector_weight=0.85,
        rerank_lexical_weight=0.15,
        rerank_min_lexical_overlap=0.0,
        chunk_size=500,
        chunk_overlap=50,
        chunk_min_merge_chars=100,
        prepare_page_engine="pdf_text",
        prepare_workers=1,
        tesseract_lang="eng",
        vl_api_url="",
        vl_api_key="",
        vl_model="test-model",
        vl_timeout_sec=5,
        vl_zoom=2.0,
        vl_min_quality=2.0,
        job_max_attempts=3,
        job_worker_poll_interval_sec=0.1,
        job_worker_concurrency=1,
        job_worker_id="test-worker",
        default_max_chat_per_day=100,
        default_max_storage_mb=500,
        default_max_documents=50,
        default_max_concurrent_jobs=2,
        health_worker_stale_sec=60,
        health_queue_stuck_sec=1800,
        auth_secret_key="test-secret-key",
        auth_mode="dev",
        auth_cookie_secure=False,
        google_client_id="",
        google_client_secret="",
        github_client_id="",
        github_client_secret="",
        oauth_redirect_base="http://localhost:3000",
        jwt_expire_minutes=60,
        chat_history_limit=4,
    )


@pytest.fixture
def job_queue(test_settings):
    from app.job_queue import JobQueue

    return JobQueue(test_settings)


@pytest.fixture
def health_checker(test_settings):
    from app.healthcheck import HealthChecker
    from app.job_queue import JobQueue
    from app.repository import RAGRepository

    repo = RAGRepository(test_settings)
    queue = JobQueue(test_settings)
    return HealthChecker(test_settings, repo, queue)


def _rebind_app_settings(settings: Settings) -> None:
    from app.api_tokens import ApiTokenService
    from app.auth import AuthService
    from app.healthcheck import HealthChecker
    from app.job_queue import JobQueue
    from app import main as main_module
    from app.service import RAGService
    from app.usage import UsageService

    usage = UsageService(settings)
    queue = JobQueue(settings)
    service = RAGService(settings, usage=usage)
    auth = AuthService(settings)
    tokens = ApiTokenService(settings)
    health = HealthChecker(settings, service.repo, queue)

    main_module.settings = settings
    main_module.usage_service = usage
    main_module.job_queue = queue
    main_module.service = service
    main_module.health_checker = health
    main_module.auth_service = auth
    main_module.api_token_service = tokens


@pytest.fixture(autouse=True)
def bind_integration_settings(request, test_settings):
    if "integration" in request.keywords:
        _rebind_app_settings(test_settings)


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from app.main import app

    return TestClient(app)
