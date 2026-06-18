from __future__ import annotations

import io
import json
import logging
import secrets
import shutil
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, HTTPException, Request, Response
from jose import JWTError, jwt
from psycopg import connect
from starlette.responses import RedirectResponse, Response

from app.api_tokens import ApiTokenService
from app.config import Settings
from app.llm_client import LLMClient
from app.schemas import (
    DevLoginRequest,
    MeResponse,
    UserSettingsPublicResponse,
    UserSettingsUpdateRequest,
)
from app.user_settings import UserSettingsService

logger = logging.getLogger(__name__)

SYSTEM_USER_ID = "system"
COOKIE_NAME = "srbs_session"
OAUTH_STATE_COOKIE = "srbs_oauth_state"
ALGORITHM = "HS256"


@dataclass(frozen=True)
class Principal:
    user_id: str
    email: str
    display_name: str | None
    auth_type: str
    scopes: list[str] | None = None
    token_id: str | None = None

    @property
    def is_api_token(self) -> bool:
        return self.auth_type == "api_token"


class AuthService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.user_settings = UserSettingsService(settings)
        self.api_tokens = ApiTokenService(settings)
        self.oauth = OAuth()
        if settings.google_client_id and settings.google_client_secret:
            self.oauth.register(
                name="google",
                client_id=settings.google_client_id,
                client_secret=settings.google_client_secret,
                server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
                client_kwargs={"scope": "openid email profile"},
            )
        if settings.github_client_id and settings.github_client_secret:
            self.oauth.register(
                name="github",
                client_id=settings.github_client_id,
                client_secret=settings.github_client_secret,
                access_token_url="https://github.com/login/oauth/access_token",
                authorize_url="https://github.com/login/oauth/authorize",
                api_base_url="https://api.github.com/",
                client_kwargs={"scope": "read:user user:email"},
            )

    def create_access_token(self, user_id: str, email: str) -> str:
        expire = datetime.now(timezone.utc) + timedelta(minutes=self.settings.jwt_expire_minutes)
        payload = {"sub": user_id, "email": email, "exp": expire}
        return jwt.encode(payload, self.settings.auth_secret_key, algorithm=ALGORITHM)

    def decode_access_token(self, token: str) -> dict:
        return jwt.decode(token, self.settings.auth_secret_key, algorithms=[ALGORITHM])

    def set_session_cookie(self, response: Response, token: str) -> None:
        response.set_cookie(
            key=COOKIE_NAME,
            value=token,
            httponly=True,
            secure=self.settings.auth_cookie_secure,
            samesite="lax",
            max_age=self.settings.jwt_expire_minutes * 60,
            path="/",
        )

    def clear_session_cookie(self, response: Response) -> None:
        response.delete_cookie(key=COOKIE_NAME, path="/")

    def upsert_oauth_user(
        self,
        *,
        provider: str,
        provider_sub: str,
        email: str,
        display_name: str | None,
    ) -> Principal:
        user_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{provider}:{provider_sub}"))
        with connect(self.settings.postgres_dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO users (user_id, email, display_name, provider, provider_sub)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (provider, provider_sub) DO UPDATE SET
                        email = EXCLUDED.email,
                        display_name = COALESCE(EXCLUDED.display_name, users.display_name),
                        updated_at = now()
                    RETURNING user_id, email, display_name
                    """,
                    (user_id, email, display_name, provider, provider_sub),
                )
                row = cur.fetchone()
        return Principal(
            user_id=str(row[0]),
            email=str(row[1]),
            display_name=str(row[2]) if row[2] is not None else None,
            auth_type="jwt",
        )

    def get_user(self, user_id: str) -> Principal | None:
        with connect(self.settings.postgres_dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT user_id, email, display_name FROM users WHERE user_id = %s",
                    (user_id,),
                )
                row = cur.fetchone()
        if row is None:
            return None
        return Principal(
            user_id=str(row[0]),
            email=str(row[1]),
            display_name=str(row[2]) if row[2] is not None else None,
            auth_type="jwt",
        )

    def dev_login(self, email: str, display_name: str | None) -> Principal:
        normalized = email.strip().lower()
        if not normalized:
            raise HTTPException(status_code=400, detail="email is required")
        return self.upsert_oauth_user(
            provider="dev",
            provider_sub=normalized,
            email=normalized,
            display_name=display_name or normalized.split("@")[0],
        )

    def resolve_principal(self, request: Request) -> Principal | None:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.lower().startswith("bearer "):
            raw_token = auth_header[7:].strip()
            token_principal = self.api_tokens.authenticate(raw_token)
            if token_principal is None:
                return None
            user = self.get_user(token_principal.user_id)
            if user is None:
                return None
            return Principal(
                user_id=user.user_id,
                email=user.email,
                display_name=user.display_name,
                auth_type="api_token",
                scopes=token_principal.scopes,
                token_id=token_principal.token_id,
            )
        cookie = request.cookies.get(COOKIE_NAME)
        if not cookie:
            return None
        try:
            payload = self.decode_access_token(cookie)
        except JWTError:
            return None
        user_id = str(payload.get("sub", ""))
        user = self.get_user(user_id)
        if user is None:
            return None
        return user

    def delete_user_data(self, user_id: str) -> None:
        docs_dir = self.settings.docs_dir / user_id
        if docs_dir.exists():
            shutil.rmtree(docs_dir, ignore_errors=True)
        with connect(self.settings.postgres_dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM users WHERE user_id = %s", (user_id,))

    def export_user_data(self, user_id: str) -> bytes:
        with connect(self.settings.postgres_dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT user_id, email, display_name, provider, created_at::text FROM users WHERE user_id = %s",
                    (user_id,),
                )
                user_row = cur.fetchone()
                if user_row is None:
                    raise HTTPException(status_code=404, detail="User not found.")
                cur.execute(
                    """
                    SELECT document_id, file_name, status, created_at::text
                    FROM rag_documents WHERE user_id = %s ORDER BY created_at
                    """,
                    (user_id,),
                )
                documents = cur.fetchall()
                cur.execute(
                    """
                    SELECT s.session_id, s.title, s.created_at::text,
                           m.role, m.content, m.created_at::text
                    FROM chat_sessions s
                    LEFT JOIN chat_messages m ON m.session_id = s.session_id
                    WHERE s.user_id = %s
                    ORDER BY s.created_at, m.id
                    """,
                    (user_id,),
                )
                chat_rows = cur.fetchall()
        settings_record = self.user_settings.get_record(user_id)
        public_settings = self.user_settings.to_public(settings_record)
        payload = {
            "user": {
                "user_id": user_row[0],
                "email": user_row[1],
                "display_name": user_row[2],
                "provider": user_row[3],
                "created_at": user_row[4],
            },
            "settings": public_settings.__dict__,
            "documents": [
                {
                    "document_id": row[0],
                    "file_name": row[1],
                    "status": row[2],
                    "created_at": row[3],
                }
                for row in documents
            ],
            "chat": [
                {
                    "session_id": row[0],
                    "title": row[1],
                    "session_created_at": row[2],
                    "role": row[3],
                    "content": row[4],
                    "message_created_at": row[5],
                }
                for row in chat_rows
            ],
        }
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("export.json", json.dumps(payload, indent=2, ensure_ascii=False))
        return buffer.getvalue()


def require_principal(
    auth_service: AuthService,
    request: Request,
    *,
    allow_api_token: bool = True,
) -> Principal:
    principal = auth_service.resolve_principal(request)
    if principal is None:
        raise HTTPException(status_code=401, detail="Authentication required.")
    if principal.is_api_token and not allow_api_token:
        raise HTTPException(status_code=403, detail="API tokens cannot access this endpoint.")
    return principal


def require_scope(principal: Principal, scope: str) -> None:
    if not principal.is_api_token:
        return
    if scope not in (principal.scopes or []):
        raise HTTPException(status_code=403, detail=f"Missing required scope: {scope}")


def build_auth_router(auth_service: AuthService, settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/auth", tags=["auth"])

    @router.get("/login/google")
    async def login_google(request: Request):
        if "google" not in auth_service.oauth._clients:  # noqa: SLF001
            raise HTTPException(status_code=501, detail="Google OAuth is not configured.")
        redirect_uri = f"{settings.oauth_redirect_base.rstrip('/')}/api/v1/auth/callback/google"
        state = secrets.token_urlsafe(32)
        response = await auth_service.oauth.google.authorize_redirect(request, redirect_uri, state=state)
        response.set_cookie(
            OAUTH_STATE_COOKIE,
            state,
            httponly=True,
            secure=settings.auth_cookie_secure,
            samesite="lax",
            max_age=600,
            path="/",
        )
        return response

    @router.get("/login/github")
    async def login_github(request: Request):
        if "github" not in auth_service.oauth._clients:  # noqa: SLF001
            raise HTTPException(status_code=501, detail="GitHub OAuth is not configured.")
        redirect_uri = f"{settings.oauth_redirect_base.rstrip('/')}/api/v1/auth/callback/github"
        state = secrets.token_urlsafe(32)
        response = await auth_service.oauth.github.authorize_redirect(request, redirect_uri, state=state)
        response.set_cookie(
            OAUTH_STATE_COOKIE,
            state,
            httponly=True,
            secure=settings.auth_cookie_secure,
            samesite="lax",
            max_age=600,
            path="/",
        )
        return response

    async def _oauth_callback(request: Request, provider: str) -> RedirectResponse:
        expected_state = request.cookies.get(OAUTH_STATE_COOKIE)
        state = request.query_params.get("state")
        if not expected_state or state != expected_state:
            raise HTTPException(status_code=400, detail="Invalid OAuth state.")
        client = auth_service.oauth.create_client(provider)
        token = await client.authorize_access_token(request)
        if provider == "google":
            userinfo = token.get("userinfo") or await client.parse_id_token(request, token)
            email = str(userinfo.get("email", "")).lower()
            provider_sub = str(userinfo.get("sub", ""))
            display_name = userinfo.get("name")
        else:
            resp = await client.get("user", token=token)
            profile = resp.json()
            email = str(profile.get("email") or f"{profile.get('id')}@users.noreply.github.com").lower()
            provider_sub = str(profile.get("id", ""))
            display_name = profile.get("name") or profile.get("login")
        if not email or not provider_sub:
            raise HTTPException(status_code=400, detail="OAuth provider did not return required profile fields.")
        principal = auth_service.upsert_oauth_user(
            provider=provider,
            provider_sub=provider_sub,
            email=email,
            display_name=display_name,
        )
        jwt_token = auth_service.create_access_token(principal.user_id, principal.email)
        redirect = RedirectResponse(url=f"{settings.oauth_redirect_base.rstrip('/')}/")
        auth_service.set_session_cookie(redirect, jwt_token)
        redirect.delete_cookie(OAUTH_STATE_COOKIE, path="/")
        return redirect

    @router.get("/callback/google")
    async def callback_google(request: Request):
        return await _oauth_callback(request, "google")

    @router.get("/callback/github")
    async def callback_github(request: Request):
        return await _oauth_callback(request, "github")

    if settings.auth_mode == "dev":

        @router.post("/dev/login")
        def dev_login(body: DevLoginRequest, response: Response) -> MeResponse:
            principal = auth_service.dev_login(body.email, body.display_name)
            token = auth_service.create_access_token(principal.user_id, principal.email)
            auth_service.set_session_cookie(response, token)
            return MeResponse(
                user_id=principal.user_id,
                email=principal.email,
                display_name=principal.display_name,
            )

    @router.post("/logout")
    def logout(response: Response) -> dict[str, str]:
        auth_service.clear_session_cookie(response)
        return {"status": "logged_out"}

    return router


def build_me_router(auth_service: AuthService, settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/me", tags=["me"])
    user_settings = UserSettingsService(settings)

    def _current(request: Request) -> Principal:
        return require_principal(auth_service, request, allow_api_token=False)

    @router.get("", response_model=MeResponse)
    def get_me(request: Request) -> MeResponse:
        principal = _current(request)
        return MeResponse(
            user_id=principal.user_id,
            email=principal.email,
            display_name=principal.display_name,
        )

    @router.get("/settings", response_model=UserSettingsPublicResponse)
    def get_settings(request: Request) -> UserSettingsPublicResponse:
        principal = _current(request)
        record = user_settings.get_record(principal.user_id)
        public = user_settings.to_public(record)
        return UserSettingsPublicResponse(**public.__dict__)

    @router.put("/settings", response_model=UserSettingsPublicResponse)
    def update_settings(request: Request, body: UserSettingsUpdateRequest) -> UserSettingsPublicResponse:
        principal = _current(request)
        public = user_settings.upsert(
            principal.user_id,
            llm_api_url=body.llm_api_url,
            llm_model=body.llm_model,
            llm_api_key=body.llm_api_key,
            clear_llm_api_key=body.clear_llm_api_key,
            embedding_api_url=body.embedding_api_url,
            embedding_model=body.embedding_model,
            embedding_api_key=body.embedding_api_key,
            clear_embedding_api_key=body.clear_embedding_api_key,
        )
        return UserSettingsPublicResponse(**public.__dict__)

    @router.post("/settings/test-llm")
    def test_llm_settings(request: Request) -> dict[str, str]:
        principal = _current(request)
        config = user_settings.llm_config_for_chat(principal.user_id)
        sample = LLMClient(config).chat_completion("Reply with the single word OK.")
        return {"status": "ok", "sample": sample[:200]}

    @router.get("/export")
    def export_me(request: Request) -> Response:
        principal = _current(request)
        payload = auth_service.export_user_data(principal.user_id)
        return Response(
            content=payload,
            media_type="application/zip",
            headers={"Content-Disposition": 'attachment; filename="srbs-export.zip"'},
        )

    @router.delete("", status_code=204, response_class=Response)
    def delete_me(request: Request, response: Response) -> Response:
        principal = _current(request)
        auth_service.delete_user_data(principal.user_id)
        auth_service.clear_session_cookie(response)
        return Response(status_code=204)

    return router
