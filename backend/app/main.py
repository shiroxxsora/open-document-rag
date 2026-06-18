import logging
from contextlib import asynccontextmanager
import json

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse

from starlette.middleware.sessions import SessionMiddleware

from app.api_tokens import ApiTokenService
from app.auth import (
    AuthService,
    Principal,
    SYSTEM_USER_ID,
    build_auth_router,
    build_me_router,
    require_principal,
    require_scope,
)
from app.config import load_settings
from app.healthcheck import HealthChecker
from app.job_queue import JobQueue
from app.middleware import RequestLoggingMiddleware
from app.schemas import (
    ApiApplicationCreateRequest,
    ApiApplicationResponse,
    ApiTokenCreateRequest,
    ApiTokenCreatedResponse,
    ApiTokenResponse,
    CancelIndexingResponse,
    ChatRequest,
    ChatResponse,
    DeleteDocumentResponse,
    DocumentListResponse,
    HealthResponse,
    ReindexDocumentResponse,
    ReindexResponse,
    UploadResponse,
)
from app.service import RAGService
from app.usage import UsageService, build_usage_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

settings = load_settings()
usage_service = UsageService(settings)
job_queue = JobQueue(settings)
service = RAGService(settings, usage=usage_service)
health_checker = HealthChecker(settings, service.repo, job_queue)
auth_service = AuthService(settings)
api_token_service = ApiTokenService(settings)


def get_current_principal(request: Request) -> Principal:
    principal = require_principal(auth_service, request)
    request.state.user_id = principal.user_id
    return principal


def get_user_id(request: Request) -> str:
    return get_current_principal(request).user_id


@asynccontextmanager
async def lifespan(app: FastAPI):
    service.bootstrap()
    job_queue.enqueue(
        "full_reindex",
        {"full_resync": False},
        user_id=SYSTEM_USER_ID,
    )
    logger.info("Startup full_reindex job enqueued for system user.")
    yield


app = FastAPI(title="Universal RAG MVP", version="0.3.0", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=settings.auth_secret_key)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

api_v1 = APIRouter(prefix="/api/v1")


@app.get("/health/live")
@app.get("/api/v1/health/live")
def health_live() -> dict[str, str]:
    return health_checker.live()


@app.get("/health/ready")
@app.get("/api/v1/health/ready")
def health_ready():
    body, status_code = health_checker.ready()
    return JSONResponse(content=body, status_code=status_code)


@api_v1.get("/health", response_model=HealthResponse)
def health(request: Request, deep: bool = False, principal: Principal = Depends(get_current_principal)) -> HealthResponse:
    _ = principal
    return health_checker.build_health_response(deep=deep, user_id=principal.user_id)


@api_v1.get("/health/deep", response_model=HealthResponse)
def health_deep(principal: Principal = Depends(get_current_principal)) -> HealthResponse:
    return health_checker.build_health_response(deep=True, user_id=principal.user_id)


@api_v1.post("/chat", response_model=ChatResponse)
def chat(
    request: ChatRequest,
    principal: Principal = Depends(get_current_principal),
) -> ChatResponse:
    if principal.is_api_token:
        require_scope(principal, "chat:write")
    question = request.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="question must not be empty")
    usage_service.check_chat_quota(principal.user_id)
    answer, hits, session_id = service.ask_text(
        principal.user_id,
        question,
        session_id=request.session_id,
    )
    usage_service.increment(
        principal.user_id,
        chat_requests=1,
        api_token_calls=1 if principal.is_api_token else 0,
    )
    health = health_checker.build_health_response(user_id=principal.user_id)
    return ChatResponse(
        answer=answer,
        matches=service.to_matches(hits),
        session_id=session_id,
        index_ready=health.index_ready,
        index_chunk_count=health.rag_chunk_count,
        index_error=health.index_error,
    )


@api_v1.post("/chat/stream")
def chat_stream(
    request: ChatRequest,
    principal: Principal = Depends(get_current_principal),
):
    if principal.is_api_token:
        require_scope(principal, "chat:write")
    question = request.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="question must not be empty")
    usage_service.check_chat_quota(principal.user_id)

    def event_stream():
        try:
            for chunk in service.ask_stream(
                principal.user_id,
                question,
                session_id=request.session_id,
            ):
                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
            usage_service.increment(
                principal.user_id,
                chat_requests=1,
                api_token_calls=1 if principal.is_api_token else 0,
            )
        except HTTPException as exc:
            payload = {"type": "error", "detail": exc.detail}
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@api_v1.get("/documents", response_model=DocumentListResponse)
def documents(principal: Principal = Depends(get_current_principal)) -> DocumentListResponse:
    if principal.is_api_token:
        require_scope(principal, "documents:read")
    return DocumentListResponse(documents=service.list_documents(principal.user_id))


@api_v1.post("/documents/upload", response_model=UploadResponse)
async def upload_documents(
    files: list[UploadFile],
    principal: Principal = Depends(get_current_principal),
) -> UploadResponse:
    if principal.is_api_token:
        raise HTTPException(status_code=403, detail="API tokens cannot upload documents.")
    if not files:
        raise HTTPException(status_code=400, detail="Upload at least one file.")
    total_bytes = 0
    payloads: list[tuple[str, bytes]] = []
    for file in files:
        payload = await file.read()
        total_bytes += len(payload)
        payloads.append((file.filename or "document", payload))
    usage_service.check_upload_quota(principal.user_id, total_bytes, new_documents=len(payloads))
    uploaded = []
    for file_name, payload in payloads:
        info = service.save_upload(principal.user_id, file_name, payload)
        uploaded.append(info)
        job_queue.enqueue(
            "index_document",
            {"document_id": info.document_id, "user_id": principal.user_id},
            user_id=principal.user_id,
        )
    usage_service.increment(principal.user_id, upload_bytes=total_bytes)
    names = ", ".join(item.file_name for item in uploaded)
    return UploadResponse(
        status="accepted",
        message=f"Uploaded {len(uploaded)} file(s): {names}. Indexing queued.",
        documents=uploaded,
    )


@api_v1.delete("/documents/{document_id:path}", response_model=DeleteDocumentResponse)
def delete_document(document_id: str, principal: Principal = Depends(get_current_principal)) -> DeleteDocumentResponse:
    if principal.is_api_token:
        require_scope(principal, "documents:write")
    service.delete_document(principal.user_id, document_id)
    return DeleteDocumentResponse(status="deleted", message=f"Document {document_id} removed.")


@api_v1.post("/documents/{document_id:path}/reindex", response_model=ReindexDocumentResponse)
def reindex_document(
    document_id: str,
    principal: Principal = Depends(get_current_principal),
) -> ReindexDocumentResponse:
    if principal.is_api_token:
        raise HTTPException(status_code=403, detail="API tokens cannot trigger reindex.")
    usage_service.check_upload_quota(principal.user_id, 0, new_documents=0)
    service.reindex_document(principal.user_id, document_id)
    job_queue.enqueue(
        "index_document",
        {"document_id": document_id, "user_id": principal.user_id},
        user_id=principal.user_id,
    )
    return ReindexDocumentResponse(
        status="accepted",
        message=f"Reindex queued for {document_id}.",
    )


@api_v1.post("/reindex", response_model=ReindexResponse)
def reindex(principal: Principal = Depends(get_current_principal)) -> ReindexResponse:
    if principal.is_api_token:
        raise HTTPException(status_code=403, detail="API tokens cannot trigger reindex.")
    usage_service.check_upload_quota(principal.user_id, 0, new_documents=0)
    job_queue.enqueue(
        "full_reindex",
        {"full_resync": True, "user_id": principal.user_id},
        user_id=principal.user_id,
    )
    return ReindexResponse(status="accepted", message="Full reindex queued.")


@api_v1.post("/cancel-indexing", response_model=CancelIndexingResponse)
def cancel_indexing(principal: Principal = Depends(get_current_principal)) -> CancelIndexingResponse:
    if principal.is_api_token:
        raise HTTPException(status_code=403, detail="API tokens cannot cancel indexing.")
    cancelled_jobs, cancelled_documents = service.cancel_all_indexing(principal.user_id, job_queue)
    if cancelled_jobs == 0 and cancelled_documents == 0:
        raise HTTPException(status_code=400, detail="No indexing in progress.")
    return CancelIndexingResponse(
        status="cancelled",
        message=f"Cancelled {cancelled_documents} document(s) and {cancelled_jobs} queued job(s).",
        cancelled_jobs=cancelled_jobs,
        cancelled_documents=cancelled_documents,
    )


@api_v1.post("/documents/{document_id:path}/cancel-indexing", response_model=CancelIndexingResponse)
def cancel_document_indexing(
    document_id: str,
    principal: Principal = Depends(get_current_principal),
) -> CancelIndexingResponse:
    if principal.is_api_token:
        raise HTTPException(status_code=403, detail="API tokens cannot cancel indexing.")
    cancelled_jobs = service.cancel_document_indexing(principal.user_id, document_id, job_queue)
    return CancelIndexingResponse(
        status="cancelled",
        message=f"Indexing cancelled for {document_id}.",
        cancelled_jobs=cancelled_jobs,
        cancelled_documents=1,
    )


developer_router = APIRouter(prefix="/developer", tags=["developer"])


@developer_router.get("/applications", response_model=list[ApiApplicationResponse])
def list_applications(principal: Principal = Depends(get_current_principal)) -> list[ApiApplicationResponse]:
    if principal.is_api_token:
        raise HTTPException(status_code=403, detail="API tokens cannot access developer endpoints.")
    apps = api_token_service.list_applications(principal.user_id)
    return [
        ApiApplicationResponse(
            app_id=app.app_id,
            name=app.name,
            description=app.description,
            webhook_url=app.webhook_url,
            created_at=app.created_at,
        )
        for app in apps
    ]


@developer_router.post("/applications", response_model=ApiApplicationResponse)
def create_application(
    body: ApiApplicationCreateRequest,
    principal: Principal = Depends(get_current_principal),
) -> ApiApplicationResponse:
    if principal.is_api_token:
        raise HTTPException(status_code=403, detail="API tokens cannot access developer endpoints.")
    app = api_token_service.create_application(
        principal.user_id,
        name=body.name,
        description=body.description,
        webhook_url=body.webhook_url,
    )
    return ApiApplicationResponse(
        app_id=app.app_id,
        name=app.name,
        description=app.description,
        webhook_url=app.webhook_url,
        created_at=app.created_at,
    )


@developer_router.delete("/applications/{app_id}", status_code=204, response_class=Response)
def delete_application(app_id: str, principal: Principal = Depends(get_current_principal)) -> Response:
    if principal.is_api_token:
        raise HTTPException(status_code=403, detail="API tokens cannot access developer endpoints.")
    if not api_token_service.delete_application(principal.user_id, app_id):
        raise HTTPException(status_code=404, detail="Application not found.")
    return Response(status_code=204)


@developer_router.get("/applications/{app_id}/tokens", response_model=list[ApiTokenResponse])
def list_tokens(app_id: str, principal: Principal = Depends(get_current_principal)) -> list[ApiTokenResponse]:
    if principal.is_api_token:
        raise HTTPException(status_code=403, detail="API tokens cannot access developer endpoints.")
    tokens = api_token_service.list_tokens(principal.user_id, app_id)
    return [
        ApiTokenResponse(
            token_id=token.token_id,
            app_id=token.app_id,
            token_prefix=token.token_prefix,
            scopes=token.scopes,
            label=token.label,
            expires_at=token.expires_at,
            revoked_at=token.revoked_at,
            created_at=token.created_at,
            last_used_at=token.last_used_at,
        )
        for token in tokens
    ]


@developer_router.post("/applications/{app_id}/tokens", response_model=ApiTokenCreatedResponse)
def create_token(
    app_id: str,
    body: ApiTokenCreateRequest,
    principal: Principal = Depends(get_current_principal),
) -> ApiTokenCreatedResponse:
    if principal.is_api_token:
        raise HTTPException(status_code=403, detail="API tokens cannot access developer endpoints.")
    created = api_token_service.create_token(
        principal.user_id,
        app_id,
        scopes=body.scopes,
        label=body.label,
    )
    return ApiTokenCreatedResponse(
        token_id=created.token_id,
        app_id=created.app_id,
        token_prefix=created.token_prefix,
        scopes=created.scopes,
        label=created.label,
        expires_at=None,
        revoked_at=None,
        created_at=created.created_at,
        last_used_at=None,
        raw_token=created.raw_token,
    )


@developer_router.delete("/tokens/{token_id}", status_code=204, response_class=Response)
def revoke_token(token_id: str, principal: Principal = Depends(get_current_principal)) -> Response:
    if principal.is_api_token:
        raise HTTPException(status_code=403, detail="API tokens cannot access developer endpoints.")
    if not api_token_service.revoke_token(principal.user_id, token_id):
        raise HTTPException(status_code=404, detail="Token not found.")
    return Response(status_code=204)


api_v1.include_router(build_auth_router(auth_service, settings))
api_v1.include_router(build_me_router(auth_service, settings))
api_v1.include_router(build_usage_router(usage_service, get_user_id))
api_v1.include_router(developer_router)
app.include_router(api_v1)


def create_app() -> FastAPI:
    return app
