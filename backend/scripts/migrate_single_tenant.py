#!/usr/bin/env python3
from __future__ import annotations

import argparse
import logging
import shutil
from pathlib import Path

from psycopg import connect

from app.auth import SYSTEM_USER_ID
from app.config import load_settings
from app.ingestion import SUPPORTED_EXTENSIONS
from app.service import RAGService

logger = logging.getLogger(__name__)


def migrate_files(settings, user_id: str) -> int:
    legacy_dir = settings.docs_dir
    target_dir = legacy_dir / user_id
    target_dir.mkdir(parents=True, exist_ok=True)
    moved = 0
    if not legacy_dir.exists():
        return 0
    for path in legacy_dir.iterdir():
        if not path.is_file():
            continue
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        destination = target_dir / path.name
        if destination.exists():
            continue
        shutil.move(str(path), str(destination))
        moved += 1
        logger.info("Moved %s -> %s", path.name, destination)
    return moved


def backfill_documents(settings, user_id: str) -> int:
    with connect(settings.postgres_dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE rag_documents
                SET user_id = %s
                WHERE user_id IS NULL OR user_id = ''
                """,
                (user_id,),
            )
            updated_docs = cur.rowcount
            cur.execute(
                """
                UPDATE rag_chunks c
                SET user_id = d.user_id
                FROM rag_documents d
                WHERE c.document_id = d.document_id
                  AND (c.user_id IS NULL OR c.user_id = '')
                """
            )
    return updated_docs


def ensure_system_user(settings, user_id: str) -> None:
    with connect(settings.postgres_dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO users (user_id, email, display_name, provider, provider_sub)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (user_id) DO NOTHING
                """,
                (user_id, "system@localhost", "System", "system", "system"),
            )


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Migrate single-tenant RAG data to system user.")
    parser.add_argument("--user-id", default=SYSTEM_USER_ID)
    parser.add_argument("--move-files", action="store_true", default=True)
    parser.add_argument("--skip-files", action="store_true")
    args = parser.parse_args()
    settings = load_settings()
    user_id = args.user_id
    ensure_system_user(settings, user_id)
    updated = backfill_documents(settings, user_id)
    moved = 0
    if args.move_files and not args.skip_files:
        moved = migrate_files(settings, user_id)
    service = RAGService(settings)
    service.bootstrap()
    logger.info("Backfilled %s documents, moved %s files to %s", updated, moved, settings.docs_dir / user_id)


if __name__ == "__main__":
    main()
