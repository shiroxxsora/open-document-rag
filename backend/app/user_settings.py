from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException
from psycopg import connect

from app.config import Settings
from app.crypto import decrypt_secret, encrypt_secret, mask_secret
from app.llm_client import LLMConfig


@dataclass(frozen=True)
class UserSettingsRecord:
    user_id: str
    llm_api_url: str | None
    llm_model: str | None
    llm_api_key: str | None
    embedding_api_url: str | None
    embedding_model: str | None
    embedding_api_key: str | None


@dataclass(frozen=True)
class UserSettingsPublic:
    llm_api_url: str | None
    llm_model: str | None
    llm_api_key_masked: str | None
    embedding_api_url: str | None
    embedding_model: str | None
    embedding_api_key_masked: str | None
    has_llm_api_key: bool
    has_embedding_api_key: bool


class UserSettingsService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def get_record(self, user_id: str) -> UserSettingsRecord | None:
        with connect(self.settings.postgres_dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT llm_api_url, llm_model, llm_api_key_encrypted,
                           embedding_api_url, embedding_model, embedding_api_key_encrypted
                    FROM user_settings
                    WHERE user_id = %s
                    """,
                    (user_id,),
                )
                row = cur.fetchone()
        if not row:
            return None
        return UserSettingsRecord(
            user_id=user_id,
            llm_api_url=row[0],
            llm_model=row[1],
            llm_api_key=decrypt_secret(self.settings, row[2]) if row[2] else None,
            embedding_api_url=row[3],
            embedding_model=row[4],
            embedding_api_key=decrypt_secret(self.settings, row[5]) if row[5] else None,
        )

    def to_public(self, record: UserSettingsRecord | None) -> UserSettingsPublic:
        if record is None:
            return UserSettingsPublic(
                llm_api_url=None,
                llm_model=None,
                llm_api_key_masked=None,
                embedding_api_url=None,
                embedding_model=None,
                embedding_api_key_masked=None,
                has_llm_api_key=False,
                has_embedding_api_key=False,
            )
        return UserSettingsPublic(
            llm_api_url=record.llm_api_url,
            llm_model=record.llm_model,
            llm_api_key_masked=mask_secret(record.llm_api_key),
            embedding_api_url=record.embedding_api_url,
            embedding_model=record.embedding_model,
            embedding_api_key_masked=mask_secret(record.embedding_api_key),
            has_llm_api_key=bool(record.llm_api_key),
            has_embedding_api_key=bool(record.embedding_api_key),
        )

    def upsert(
        self,
        user_id: str,
        *,
        llm_api_url: str | None = None,
        llm_model: str | None = None,
        llm_api_key: str | None = None,
        clear_llm_api_key: bool = False,
        embedding_api_url: str | None = None,
        embedding_model: str | None = None,
        embedding_api_key: str | None = None,
        clear_embedding_api_key: bool = False,
    ) -> UserSettingsPublic:
        existing = self.get_record(user_id)
        next_llm_url = llm_api_url if llm_api_url is not None else (existing.llm_api_url if existing else None)
        next_llm_model = llm_model if llm_model is not None else (existing.llm_model if existing else None)
        next_embedding_url = (
            embedding_api_url
            if embedding_api_url is not None
            else (existing.embedding_api_url if existing else None)
        )
        next_embedding_model = (
            embedding_model
            if embedding_model is not None
            else (existing.embedding_model if existing else None)
        )
        next_llm_key_encrypted = None
        next_embedding_key_encrypted = None
        if clear_llm_api_key:
            next_llm_key_encrypted = ""
        elif llm_api_key:
            next_llm_key_encrypted = encrypt_secret(self.settings, llm_api_key)
        elif existing and existing.llm_api_key:
            next_llm_key_encrypted = encrypt_secret(self.settings, existing.llm_api_key)
        if clear_embedding_api_key:
            next_embedding_key_encrypted = ""
        elif embedding_api_key:
            next_embedding_key_encrypted = encrypt_secret(self.settings, embedding_api_key)
        elif existing and existing.embedding_api_key:
            next_embedding_key_encrypted = encrypt_secret(self.settings, existing.embedding_api_key)

        with connect(self.settings.postgres_dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO user_settings (
                        user_id, llm_api_url, llm_model, llm_api_key_encrypted,
                        embedding_api_url, embedding_model, embedding_api_key_encrypted
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (user_id) DO UPDATE SET
                        llm_api_url = EXCLUDED.llm_api_url,
                        llm_model = EXCLUDED.llm_model,
                        embedding_api_url = EXCLUDED.embedding_api_url,
                        embedding_model = EXCLUDED.embedding_model,
                        llm_api_key_encrypted = EXCLUDED.llm_api_key_encrypted,
                        embedding_api_key_encrypted = EXCLUDED.embedding_api_key_encrypted,
                        updated_at = now()
                    """,
                    (
                        user_id,
                        next_llm_url,
                        next_llm_model,
                        next_llm_key_encrypted,
                        next_embedding_url,
                        next_embedding_model,
                        next_embedding_key_encrypted,
                    ),
                )
        return self.to_public(self.get_record(user_id))

    def llm_config_for_chat(self, user_id: str) -> LLMConfig:
        record = self.get_record(user_id)
        if record is None or not record.llm_api_key:
            raise HTTPException(
                status_code=400,
                detail="Configure your LLM API key in Settings before chatting.",
            )
        return LLMConfig(
            llm_api_url=record.llm_api_url or self.settings.llm_api_url,
            llm_api_key=record.llm_api_key,
            llm_model=record.llm_model or self.settings.llm_model,
            llm_timeout_sec=self.settings.llm_timeout_sec,
            embedding_api_url=record.embedding_api_url or self.settings.embedding_api_url,
            embedding_api_key=record.embedding_api_key or record.llm_api_key,
            embedding_model=record.embedding_model or self.settings.embedding_model,
            embedding_dim=self.settings.embedding_dim,
            embedding_timeout_sec=self.settings.embedding_timeout_sec,
            embedding_batch_size=self.settings.embedding_batch_size,
        )

    def llm_config_for_embeddings(self, user_id: str) -> LLMConfig:
        record = self.get_record(user_id)
        embedding_key = None
        embedding_url = self.settings.embedding_api_url
        embedding_model = self.settings.embedding_model
        if record and record.embedding_api_key:
            embedding_key = record.embedding_api_key
            embedding_url = record.embedding_api_url or embedding_url
            embedding_model = record.embedding_model or embedding_model
        elif record and record.llm_api_key:
            embedding_key = record.llm_api_key
            embedding_url = record.embedding_api_url or record.llm_api_url or embedding_url
            embedding_model = record.embedding_model or embedding_model
        elif self.settings.llm_api_key:
            embedding_key = self.settings.llm_api_key
        else:
            raise HTTPException(
                status_code=400,
                detail="No embedding API key configured. Set user or system embedding credentials.",
            )
        return LLMConfig(
            llm_api_url=self.settings.llm_api_url,
            llm_api_key=self.settings.llm_api_key,
            llm_model=self.settings.llm_model,
            llm_timeout_sec=self.settings.llm_timeout_sec,
            embedding_api_url=embedding_url,
            embedding_api_key=embedding_key,
            embedding_model=embedding_model,
            embedding_dim=self.settings.embedding_dim,
            embedding_timeout_sec=self.settings.embedding_timeout_sec,
            embedding_batch_size=self.settings.embedding_batch_size,
        )
