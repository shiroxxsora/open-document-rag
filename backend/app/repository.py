from dataclasses import dataclass

from psycopg import connect

from app.config import Settings
from app.models import RetrievalHit
from app.schemas import DocumentInfo
from app.text_sanitize import sanitize_pg_text


def vector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{value:.8f}" for value in values) + "]"


@dataclass(frozen=True)
class ChunkInsert:
    user_id: str
    document_id: str
    document_name: str
    content_hash: str
    chunk_index: int
    chunk_text: str
    source_page: str | None
    embedding: list[float]


@dataclass(frozen=True)
class ChatMessageRow:
    role: str
    content: str


class RAGRepository:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def ensure_schema(self) -> None:
        dim = int(self.settings.embedding_dim)
        required = ("rag_documents", "rag_chunks", "users")
        with connect(self.settings.postgres_dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                for table in required:
                    cur.execute("SELECT to_regclass(%s)", (f"public.{table}",))
                    row = cur.fetchone()
                    if row is None or row[0] is None:
                        raise RuntimeError(
                            f"Missing table {table}. Apply Liquibase migrations before starting the backend."
                        )
                self._verify_embedding_dimension(cur, dim)

    def _verify_embedding_dimension(self, cur, dim: int) -> None:
        cur.execute(
            """
            SELECT a.atttypmod
            FROM pg_attribute a
            JOIN pg_class c ON a.attrelid = c.oid
            JOIN pg_namespace n ON c.relnamespace = n.oid
            WHERE c.relname = 'rag_chunks' AND a.attname = 'embedding' AND n.nspname = 'public'
            """
        )
        row = cur.fetchone()
        if not row or row[0] in (-1, None):
            return
        current_dim = int(row[0])
        if current_dim <= 0:
            return
        if current_dim != dim:
            raise RuntimeError(
                f"Embedding dimension mismatch: database={current_dim}, EMBEDDING_DIM={dim}. "
                "Run Liquibase changeset 005_embedding_dim_alter.sql."
            )

    def upsert_document(
        self,
        user_id: str,
        document_id: str,
        file_name: str,
        *,
        status: str = "pending",
        content_hash: str | None = None,
        error: str | None = None,
    ) -> None:
        with connect(self.settings.postgres_dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO rag_documents (user_id, document_id, file_name, content_hash, status, error)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (user_id, document_id) DO UPDATE SET
                        file_name = EXCLUDED.file_name,
                        content_hash = COALESCE(EXCLUDED.content_hash, rag_documents.content_hash),
                        status = EXCLUDED.status,
                        error = EXCLUDED.error,
                        updated_at = now()
                    """,
                    (user_id, document_id, sanitize_pg_text(file_name), content_hash, status, sanitize_pg_text(error)),
                )

    def mark_document_error(self, user_id: str, document_id: str, file_name: str, error: str) -> None:
        clean_error = sanitize_pg_text(error) or "Unknown error"
        self.upsert_document(user_id, document_id, file_name, status="error", error=clean_error[:2000])

    def cancel_inflight_documents(self, user_id: str, *, document_id: str | None = None) -> int:
        clauses = ["user_id = %s", "status IN ('pending', 'indexing')"]
        params: list[str] = [user_id]
        if document_id is not None:
            clauses.append("document_id = %s")
            params.append(document_id)
        where_sql = " AND ".join(clauses)
        with connect(self.settings.postgres_dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    UPDATE rag_documents
                    SET status = 'cancelled',
                        error = 'Indexing cancelled by user.',
                        updated_at = now()
                    WHERE {where_sql}
                    RETURNING document_id
                    """,
                    params,
                )
                rows = cur.fetchall()
        return len(rows)

    def document_already_indexed(self, user_id: str, document_id: str, content_hash: str) -> bool:
        with connect(self.settings.postgres_dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 1 FROM rag_documents
                    WHERE user_id = %s AND document_id = %s AND content_hash = %s AND status = 'indexed'
                    LIMIT 1
                    """,
                    (user_id, document_id, content_hash),
                )
                return cur.fetchone() is not None

    def replace_document_chunks(self, user_id: str, document_id: str, rows: list[ChunkInsert]) -> None:
        with connect(self.settings.postgres_dsn, autocommit=False) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM rag_chunks WHERE user_id = %s AND document_id = %s",
                    (user_id, document_id),
                )
                if rows:
                    cur.executemany(
                        """
                        INSERT INTO rag_chunks (
                            user_id, document_id, document_name, content_hash, chunk_index,
                            chunk_text, source_page, embedding
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s::vector)
                        """,
                        [
                            (
                                row.user_id,
                                row.document_id,
                                sanitize_pg_text(row.document_name),
                                row.content_hash,
                                row.chunk_index,
                                sanitize_pg_text(row.chunk_text),
                                sanitize_pg_text(row.source_page),
                                vector_literal(row.embedding),
                            )
                            for row in rows
                        ],
                    )
            conn.commit()

    def clear_all(self, user_id: str) -> None:
        with connect(self.settings.postgres_dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM rag_chunks WHERE user_id = %s", (user_id,))
                cur.execute(
                    """
                    UPDATE rag_documents
                    SET status = 'pending', content_hash = NULL, error = NULL, updated_at = now()
                    WHERE user_id = %s
                    """,
                    (user_id,),
                )

    def search(self, user_id: str, query_embedding: list[float], limit: int) -> list[RetrievalHit]:
        v = vector_literal(query_embedding)
        with connect(self.settings.postgres_dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT document_id, document_name, chunk_text, source_page, chunk_index,
                           (embedding <=> %s::vector) AS distance
                    FROM rag_chunks
                    WHERE user_id = %s
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s
                    """,
                    (v, user_id, v, limit),
                )
                rows = cur.fetchall()
        return [
            RetrievalHit(
                document_id=str(document_id),
                document_name=str(document_name),
                content=str(chunk_text),
                source_page=str(source_page) if source_page is not None else None,
                chunk_index=int(chunk_index),
                distance=float(distance),
            )
            for document_id, document_name, chunk_text, source_page, chunk_index, distance in rows
        ]

    def fetch_chunks_for_doc_indices(
        self, user_id: str, document_id: str, chunk_indices: list[int]
    ) -> list[RetrievalHit]:
        if not chunk_indices:
            return []
        with connect(self.settings.postgres_dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT document_id, document_name, chunk_text, source_page, chunk_index
                    FROM rag_chunks
                    WHERE user_id = %s AND document_id = %s AND chunk_index = ANY(%s)
                    ORDER BY chunk_index ASC
                    """,
                    (user_id, document_id, chunk_indices),
                )
                rows = cur.fetchall()
        return [
            RetrievalHit(
                document_id=str(document_id),
                document_name=str(document_name),
                content=str(chunk_text),
                source_page=str(source_page) if source_page is not None else None,
                chunk_index=int(chunk_index),
                distance=0.0,
            )
            for document_id, document_name, chunk_text, source_page, chunk_index in rows
        ]

    def list_documents(self, user_id: str) -> list[DocumentInfo]:
        with connect(self.settings.postgres_dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT d.document_id, d.file_name, d.content_hash, d.status, d.error,
                           d.created_at::text, d.updated_at::text, COUNT(c.id)::int AS chunk_count
                    FROM rag_documents d
                    LEFT JOIN rag_chunks c
                        ON c.user_id = d.user_id AND c.document_id = d.document_id
                    WHERE d.user_id = %s
                    GROUP BY d.document_id, d.file_name, d.content_hash, d.status, d.error,
                             d.created_at, d.updated_at
                    ORDER BY d.updated_at DESC, d.file_name ASC
                    """,
                    (user_id,),
                )
                rows = cur.fetchall()
        return [
            DocumentInfo(
                document_id=str(document_id),
                file_name=str(file_name),
                content_hash=str(hash_value) if hash_value is not None else None,
                status=str(status),
                error=str(error) if error is not None else None,
                created_at=str(created_at) if created_at is not None else None,
                updated_at=str(updated_at) if updated_at is not None else None,
                chunk_count=int(chunk_count),
            )
            for document_id, file_name, hash_value, status, error, created_at, updated_at, chunk_count in rows
        ]

    def count_chunks(self, user_id: str) -> int:
        with connect(self.settings.postgres_dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM rag_chunks WHERE user_id = %s", (user_id,))
                row = cur.fetchone()
        return int(row[0]) if row else 0

    def count_documents(self, user_id: str) -> int:
        with connect(self.settings.postgres_dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM rag_documents WHERE user_id = %s", (user_id,))
                row = cur.fetchone()
        return int(row[0]) if row else 0

    def count_documents_by_status(self, user_id: str, statuses: list[str]) -> int:
        if not statuses:
            return 0
        with connect(self.settings.postgres_dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM rag_documents WHERE user_id = %s AND status = ANY(%s)",
                    (user_id, statuses),
                )
                row = cur.fetchone()
        return int(row[0]) if row else 0

    def get_document(self, user_id: str, document_id: str) -> DocumentInfo | None:
        docs = [doc for doc in self.list_documents(user_id) if doc.document_id == document_id]
        return docs[0] if docs else None

    def delete_document(self, user_id: str, document_id: str) -> bool:
        with connect(self.settings.postgres_dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM rag_documents
                    WHERE user_id = %s AND document_id = %s
                    RETURNING document_id
                    """,
                    (user_id, document_id),
                )
                return cur.fetchone() is not None

    def create_chat_session(self, user_id: str, session_id: str, title: str | None = None) -> None:
        with connect(self.settings.postgres_dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO chat_sessions (session_id, user_id, title)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (session_id) DO NOTHING
                    """,
                    (session_id, user_id, sanitize_pg_text(title)),
                )

    def get_chat_session(self, user_id: str, session_id: str) -> bool:
        with connect(self.settings.postgres_dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM chat_sessions WHERE session_id = %s AND user_id = %s",
                    (session_id, user_id),
                )
                return cur.fetchone() is not None

    def append_chat_message(self, session_id: str, role: str, content: str) -> None:
        with connect(self.settings.postgres_dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO chat_messages (session_id, role, content)
                    VALUES (%s, %s, %s)
                    """,
                    (session_id, role, sanitize_pg_text(content)),
                )
                cur.execute(
                    "UPDATE chat_sessions SET updated_at = now() WHERE session_id = %s",
                    (session_id,),
                )

    def get_recent_chat_messages(self, session_id: str, limit: int) -> list[ChatMessageRow]:
        with connect(self.settings.postgres_dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT role, content
                    FROM (
                        SELECT role, content, id
                        FROM chat_messages
                        WHERE session_id = %s
                        ORDER BY id DESC
                        LIMIT %s
                    ) recent
                    ORDER BY id ASC
                    """,
                    (session_id, limit),
                )
                rows = cur.fetchall()
        return [ChatMessageRow(role=str(role), content=str(content)) for role, content in rows]

    def list_user_ids_with_documents(self) -> list[str]:
        with connect(self.settings.postgres_dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT DISTINCT user_id FROM rag_documents ORDER BY user_id")
                rows = cur.fetchall()
        return [str(row[0]) for row in rows]
