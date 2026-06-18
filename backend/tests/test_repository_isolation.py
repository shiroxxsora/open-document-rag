import pytest
from psycopg import connect

from app.repository import RAGRepository


def _ensure_user(repo: RAGRepository, user_id: str, email: str) -> None:
    with connect(repo.settings.postgres_dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO users (user_id, email, display_name, provider, provider_sub)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (user_id) DO NOTHING
                """,
                (user_id, email, user_id, "test", user_id),
            )


@pytest.mark.integration
def test_repository_isolates_documents_by_user(test_settings):
    repo = RAGRepository(test_settings)
    repo.ensure_schema()

    user_a = "user-a-isolation"
    user_b = "user-b-isolation"
    _ensure_user(repo, user_a, "a@example.com")
    _ensure_user(repo, user_b, "b@example.com")

    repo.upsert_document(user_a, "doc-a.txt", "Doc A", status="indexed", content_hash="hash-a")
    repo.upsert_document(user_b, "doc-b.txt", "Doc B", status="indexed", content_hash="hash-b")

    docs_a = repo.list_documents(user_a)
    docs_b = repo.list_documents(user_b)

    assert len(docs_a) == 1
    assert docs_a[0].document_id == "doc-a.txt"
    assert len(docs_b) == 1
    assert docs_b[0].document_id == "doc-b.txt"
    assert repo.get_document(user_a, "doc-b.txt") is None
    assert repo.get_document(user_b, "doc-a.txt") is None

    try:
        assert repo.delete_document(user_a, "doc-a.txt")
        assert repo.delete_document(user_b, "doc-b.txt")
    finally:
        repo.delete_document(user_a, "doc-a.txt")
        repo.delete_document(user_b, "doc-b.txt")
