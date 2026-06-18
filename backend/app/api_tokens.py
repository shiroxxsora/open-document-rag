from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import HTTPException
from psycopg import connect

from app.config import Settings
from app.crypto import generate_api_token, hash_token

VALID_SCOPES = frozenset(
    {"chat:write", "documents:read", "documents:write", "settings:read"}
)


@dataclass(frozen=True)
class ApiApplication:
    app_id: str
    user_id: str
    name: str
    description: str | None
    webhook_url: str | None
    created_at: str


@dataclass(frozen=True)
class ApiTokenRecord:
    token_id: str
    app_id: str
    user_id: str
    token_prefix: str
    scopes: list[str]
    label: str | None
    expires_at: str | None
    revoked_at: str | None
    created_at: str
    last_used_at: str | None


@dataclass(frozen=True)
class ApiTokenCreated:
    token_id: str
    app_id: str
    token_prefix: str
    scopes: list[str]
    label: str | None
    raw_token: str
    created_at: str


@dataclass(frozen=True)
class ApiTokenPrincipal:
    token_id: str
    app_id: str
    user_id: str
    scopes: list[str]


class ApiTokenService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def create_application(
        self,
        user_id: str,
        *,
        name: str,
        description: str | None = None,
        webhook_url: str | None = None,
    ) -> ApiApplication:
        app_id = str(uuid.uuid4())
        with connect(self.settings.postgres_dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO api_applications (app_id, user_id, name, description, webhook_url)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING created_at::text
                    """,
                    (app_id, user_id, name.strip(), description, webhook_url),
                )
                created_at = str(cur.fetchone()[0])
        return ApiApplication(
            app_id=app_id,
            user_id=user_id,
            name=name.strip(),
            description=description,
            webhook_url=webhook_url,
            created_at=created_at,
        )

    def list_applications(self, user_id: str) -> list[ApiApplication]:
        with connect(self.settings.postgres_dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT app_id, user_id, name, description, webhook_url, created_at::text
                    FROM api_applications
                    WHERE user_id = %s
                    ORDER BY created_at DESC
                    """,
                    (user_id,),
                )
                rows = cur.fetchall()
        return [
            ApiApplication(
                app_id=str(row[0]),
                user_id=str(row[1]),
                name=str(row[2]),
                description=str(row[3]) if row[3] is not None else None,
                webhook_url=str(row[4]) if row[4] is not None else None,
                created_at=str(row[5]),
            )
            for row in rows
        ]

    def delete_application(self, user_id: str, app_id: str) -> bool:
        with connect(self.settings.postgres_dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM api_applications
                    WHERE app_id = %s AND user_id = %s
                    RETURNING app_id
                    """,
                    (app_id, user_id),
                )
                return cur.fetchone() is not None

    def create_token(
        self,
        user_id: str,
        app_id: str,
        *,
        scopes: list[str],
        label: str | None = None,
        expires_at: datetime | None = None,
    ) -> ApiTokenCreated:
        invalid = [scope for scope in scopes if scope not in VALID_SCOPES]
        if invalid:
            raise HTTPException(status_code=400, detail=f"Invalid scopes: {', '.join(invalid)}")
        if not scopes:
            raise HTTPException(status_code=400, detail="At least one scope is required.")
        with connect(self.settings.postgres_dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM api_applications WHERE app_id = %s AND user_id = %s",
                    (app_id, user_id),
                )
                if cur.fetchone() is None:
                    raise HTTPException(status_code=404, detail="Application not found.")
        raw_token, token_hash, token_prefix = generate_api_token()
        token_id = str(uuid.uuid4())
        with connect(self.settings.postgres_dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO api_tokens (
                        token_id, app_id, user_id, token_hash, token_prefix, scopes, label, expires_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING created_at::text
                    """,
                    (
                        token_id,
                        app_id,
                        user_id,
                        token_hash,
                        token_prefix,
                        scopes,
                        label,
                        expires_at,
                    ),
                )
                created_at = str(cur.fetchone()[0])
        return ApiTokenCreated(
            token_id=token_id,
            app_id=app_id,
            token_prefix=token_prefix,
            scopes=scopes,
            label=label,
            raw_token=raw_token,
            created_at=created_at,
        )

    def list_tokens(self, user_id: str, app_id: str) -> list[ApiTokenRecord]:
        with connect(self.settings.postgres_dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT token_id, app_id, user_id, token_prefix, scopes, label,
                           expires_at::text, revoked_at::text, created_at::text, last_used_at::text
                    FROM api_tokens
                    WHERE user_id = %s AND app_id = %s
                    ORDER BY created_at DESC
                    """,
                    (user_id, app_id),
                )
                rows = cur.fetchall()
        return [
            ApiTokenRecord(
                token_id=str(row[0]),
                app_id=str(row[1]),
                user_id=str(row[2]),
                token_prefix=str(row[3]),
                scopes=list(row[4] or []),
                label=str(row[5]) if row[5] is not None else None,
                expires_at=str(row[6]) if row[6] is not None else None,
                revoked_at=str(row[7]) if row[7] is not None else None,
                created_at=str(row[8]),
                last_used_at=str(row[9]) if row[9] is not None else None,
            )
            for row in rows
        ]

    def revoke_token(self, user_id: str, token_id: str) -> bool:
        with connect(self.settings.postgres_dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE api_tokens
                    SET revoked_at = now()
                    WHERE token_id = %s AND user_id = %s AND revoked_at IS NULL
                    RETURNING token_id
                    """,
                    (token_id, user_id),
                )
                return cur.fetchone() is not None

    def authenticate(self, raw_token: str) -> ApiTokenPrincipal | None:
        if not raw_token.startswith("srbs_live_"):
            return None
        token_hash = hash_token(raw_token)
        with connect(self.settings.postgres_dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT token_id, app_id, user_id, scopes, expires_at, revoked_at
                    FROM api_tokens
                    WHERE token_hash = %s
                    """,
                    (token_hash,),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                expires_at = row[4]
                revoked_at = row[5]
                if revoked_at is not None:
                    return None
                if expires_at is not None and expires_at < datetime.now(timezone.utc):
                    return None
                cur.execute(
                    "UPDATE api_tokens SET last_used_at = now() WHERE token_hash = %s",
                    (token_hash,),
                )
            conn.commit()
        return ApiTokenPrincipal(
            token_id=str(row[0]),
            app_id=str(row[1]),
            user_id=str(row[2]),
            scopes=list(row[3] or []),
        )

    @staticmethod
    def require_scope(principal: ApiTokenPrincipal, scope: str) -> None:
        if scope not in principal.scopes:
            raise HTTPException(status_code=403, detail=f"Missing required scope: {scope}")
