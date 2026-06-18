import os
import subprocess

import pytest
from psycopg import connect

from app.repository import RAGRepository
from tests.conftest import test_settings


def _liquibase_available() -> bool:
    try:
        subprocess.run(["liquibase", "--version"], capture_output=True, check=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


@pytest.mark.integration
def test_schema_tables_exist_after_migrations(test_settings):
    with connect(test_settings.postgres_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_name IN (
                    'rag_documents', 'rag_chunks', 'job_queue', 'usage_daily',
                    'users', 'api_applications', 'api_tokens'
                  )
                """
            )
            tables = {row[0] for row in cur.fetchall()}
    missing = {
        "rag_documents",
        "rag_chunks",
        "job_queue",
        "usage_daily",
        "users",
        "api_applications",
        "api_tokens",
    } - tables
    if missing:
        if _liquibase_available():
            pytest.fail(f"Missing tables after migrations: {sorted(missing)}")
        pytest.skip(f"Database not migrated; missing tables: {sorted(missing)}")


@pytest.mark.integration
def test_repository_starts_without_ddl(test_settings):
    repo = RAGRepository(test_settings)
    repo.ensure_schema()
