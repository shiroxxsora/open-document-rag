import logging
import re
import uuid
from dataclasses import replace
from pathlib import Path

from fastapi import HTTPException

from app.auth import SYSTEM_USER_ID
from app.config import Settings
from app.ingestion import SUPPORTED_EXTENSIONS, chunk_document, content_hash, read_document, read_documents
from app.llm_client import LLMClient
from app.models import RetrievalHit
from app.repository import ChunkInsert, RAGRepository
from app.schemas import DocumentInfo, RAGMatch
from app.usage import UsageService
from app.user_settings import UserSettingsService

logger = logging.getLogger(__name__)

INDEXING_ACTIVE_STATUSES = frozenset({"pending", "indexing"})


class IndexingCancelledError(Exception):
    """Raised when indexing was cancelled while a worker job was still running."""


def _tokenize(text: str) -> set[str]:
    return {token.lower() for token in re.findall(r"[A-Za-zА-Яа-яЁё0-9]{3,}", text)}


def _safe_file_name(name: str) -> str:
    cleaned = re.sub(r"[^\w.\- а-яА-ЯёЁ]+", "_", Path(name).name, flags=re.UNICODE).strip("._ ")
    return cleaned or "document.txt"


def _resolve_document_path(docs_dir: Path, document_id: str) -> Path:
    base = docs_dir.resolve()
    target = (base / document_id).resolve()
    if not str(target).startswith(str(base)):
        raise HTTPException(status_code=400, detail="Invalid document path.")
    return target


class RAGService:
    def __init__(self, settings: Settings, usage: UsageService | None = None) -> None:
        self.settings = settings
        self.repo = RAGRepository(settings)
        self.usage = usage
        self.user_settings = UserSettingsService(settings)

    def docs_dir_for(self, user_id: str) -> Path:
        return self.settings.docs_dir / user_id

    def bootstrap(self) -> None:
        self.settings.docs_dir.mkdir(parents=True, exist_ok=True)
        self.settings.page_cache_dir.mkdir(parents=True, exist_ok=True)
        self.repo.ensure_schema()

    def save_upload(self, user_id: str, file_name: str, payload: bytes) -> DocumentInfo:
        safe_name = _safe_file_name(file_name)
        suffix = Path(safe_name).suffix.lower()
        if suffix not in SUPPORTED_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type {suffix or '(none)'}. Use .pdf, .txt or .docx.",
            )
        max_bytes = self.settings.max_upload_mb * 1024 * 1024
        if len(payload) > max_bytes:
            raise HTTPException(status_code=413, detail=f"File is larger than {self.settings.max_upload_mb} MB.")
        docs_dir = self.docs_dir_for(user_id)
        docs_dir.mkdir(parents=True, exist_ok=True)
        target = docs_dir / safe_name
        target.write_bytes(payload)
        document_id = target.relative_to(docs_dir).as_posix()
        self.repo.upsert_document(user_id, document_id, safe_name, status="pending", error=None)
        doc = self.repo.get_document(user_id, document_id)
        return doc or DocumentInfo(document_id=document_id, file_name=safe_name, status="pending")

    def list_documents(self, user_id: str) -> list[DocumentInfo]:
        return self.repo.list_documents(user_id)

    def delete_document(self, user_id: str, document_id: str) -> None:
        self.bootstrap()
        if not self.repo.get_document(user_id, document_id):
            raise HTTPException(status_code=404, detail="Document not found.")
        path = _resolve_document_path(self.docs_dir_for(user_id), document_id)
        if path.exists():
            path.unlink()
        self.repo.delete_document(user_id, document_id)

    def reindex_document(self, user_id: str, document_id: str) -> DocumentInfo:
        self.bootstrap()
        doc = self.repo.get_document(user_id, document_id)
        if doc is None:
            raise HTTPException(status_code=404, detail="Document not found.")
        path = _resolve_document_path(self.docs_dir_for(user_id), document_id)
        if not path.exists():
            raise HTTPException(status_code=404, detail="Document file missing on disk.")
        self.repo.upsert_document(user_id, document_id, doc.file_name, status="pending", error=None)
        return doc

    def cancel_document_indexing(self, user_id: str, document_id: str, job_queue) -> int:
        self.bootstrap()
        doc = self.repo.get_document(user_id, document_id)
        if doc is None:
            raise HTTPException(status_code=404, detail="Document not found.")
        if doc.status not in INDEXING_ACTIVE_STATUSES:
            raise HTTPException(status_code=400, detail="Document is not being indexed.")
        cancelled_jobs = job_queue.cancel_indexing_jobs(user_id, document_id=document_id)
        self.repo.cancel_inflight_documents(user_id, document_id=document_id)
        return cancelled_jobs

    def cancel_all_indexing(self, user_id: str, job_queue) -> tuple[int, int]:
        self.bootstrap()
        cancelled_jobs = job_queue.cancel_indexing_jobs(user_id, include_full_reindex=True)
        cancelled_docs = self.repo.cancel_inflight_documents(user_id)
        return cancelled_jobs, cancelled_docs

    def _is_indexing_cancelled(self, user_id: str, document_id: str) -> bool:
        doc = self.repo.get_document(user_id, document_id)
        return doc is not None and doc.status == "cancelled"

    def indexing_stats(self, user_id: str) -> tuple[int, int]:
        indexing = self.repo.count_documents_by_status(user_id, ["indexing", "pending"])
        pending = self.repo.count_documents_by_status(user_id, ["pending"])
        return indexing, pending

    def index_documents(self, user_id: str, *, full_resync: bool = False) -> None:
        self.bootstrap()
        docs_dir = self.docs_dir_for(user_id)
        docs_dir.mkdir(parents=True, exist_ok=True)
        if full_resync:
            self.repo.clear_all(user_id)
        settings_copy = self._settings_with_docs_dir(user_id)
        for document in read_documents(settings_copy):
            self._index_document(user_id, document, full_resync=full_resync)

    def index_uploaded_document(self, user_id: str, document_id: str) -> None:
        self.bootstrap()
        if self._is_indexing_cancelled(user_id, document_id):
            raise IndexingCancelledError()
        path = self.docs_dir_for(user_id) / document_id
        settings_copy = self._settings_with_docs_dir(user_id)
        document = read_document(settings_copy, path)
        if document is None:
            self.repo.mark_document_error(
                user_id,
                document_id,
                Path(document_id).name,
                "Document is empty or unsupported.",
            )
            return
        self._index_document(user_id, document, full_resync=False)

    def _settings_with_docs_dir(self, user_id: str) -> Settings:
        return replace(self.settings, docs_dir=self.docs_dir_for(user_id))

    def _index_document(self, user_id: str, document, *, full_resync: bool) -> None:
        if self._is_indexing_cancelled(user_id, document.document_id):
            raise IndexingCancelledError()
        llm = LLMClient(self.user_settings.llm_config_for_embeddings(user_id))
        hash_value = content_hash(document.content)
        self.repo.upsert_document(user_id, document.document_id, document.file_name, status="indexing", error=None)
        if not full_resync and self.repo.document_already_indexed(user_id, document.document_id, hash_value):
            self.repo.upsert_document(
                user_id,
                document.document_id,
                document.file_name,
                status="indexed",
                content_hash=hash_value,
                error=None,
            )
            return
        try:
            chunks = chunk_document(self._settings_with_docs_dir(user_id), document)
            embeddings = llm.get_embeddings([chunk.text for chunk in chunks])
            if self._is_indexing_cancelled(user_id, document.document_id):
                raise IndexingCancelledError()
            if self.usage is not None:
                self.usage.increment(user_id, embedding_calls=len(embeddings))
            rows = [
                ChunkInsert(
                    user_id=user_id,
                    document_id=document.document_id,
                    document_name=document.file_name,
                    content_hash=hash_value,
                    chunk_index=index,
                    chunk_text=chunk.text,
                    source_page=chunk.page,
                    embedding=embedding,
                )
                for index, (chunk, embedding) in enumerate(zip(chunks, embeddings, strict=True))
            ]
            if self._is_indexing_cancelled(user_id, document.document_id):
                raise IndexingCancelledError()
            self.repo.replace_document_chunks(user_id, document.document_id, rows)
            self.repo.upsert_document(
                user_id,
                document.document_id,
                document.file_name,
                status="indexed",
                content_hash=hash_value,
                error=None,
            )
            logger.info("Indexed %s chunks for %s/%s", len(rows), user_id, document.document_id)
        except Exception as exc:  # noqa: BLE001
            self.repo.mark_document_error(user_id, document.document_id, document.file_name, str(exc))
            raise

    def retrieve_context(self, user_id: str, query: str) -> list[RetrievalHit]:
        llm = LLMClient(self.user_settings.llm_config_for_embeddings(user_id))
        k = self.settings.rag_top_k
        search_limit = max(self.settings.rag_search_limit, k * 10)
        query_embedding = llm.get_embedding(query)
        raw = self.repo.search(user_id, query_embedding, search_limit)
        ranked = self._rerank(query, raw)
        selected = ranked[:k]
        if len(selected) < k and self.settings.rag_fallback_on_empty:
            selected = self._fallback_hits(raw, selected, k)
        return self._expand_neighbors(user_id, selected)

    def _fallback_hits(
        self, raw: list[RetrievalHit], selected: list[RetrievalHit], k: int
    ) -> list[RetrievalHit]:
        seen = {(hit.document_id, hit.chunk_index) for hit in selected}
        fb_max = self.settings.rag_fallback_max_distance
        loose = sorted(
            [hit for hit in raw if hit.distance <= fb_max],
            key=lambda hit: hit.distance,
        )
        merged = list(selected)
        for hit in loose:
            key = (hit.document_id, hit.chunk_index)
            if key in seen:
                continue
            merged.append(hit)
            seen.add(key)
            if len(merged) >= k:
                break
        if len(merged) < k:
            for hit in sorted(raw, key=lambda row: row.distance):
                key = (hit.document_id, hit.chunk_index)
                if key in seen:
                    continue
                merged.append(hit)
                seen.add(key)
                if len(merged) >= k:
                    break
        return merged[:k]

    def _expand_neighbors(self, user_id: str, hits: list[RetrievalHit]) -> list[RetrievalHit]:
        window = self.settings.rag_neighbor_window
        if window <= 0:
            return hits
        expanded: list[RetrievalHit] = []
        seen: set[tuple[str, int]] = set()
        for hit in hits:
            indices = list(range(max(0, hit.chunk_index - window), hit.chunk_index + window + 1))
            neighbors = self.repo.fetch_chunks_for_doc_indices(user_id, hit.document_id, indices)
            neighbor_map = {row.chunk_index: row for row in neighbors}
            for idx in indices:
                key = (hit.document_id, idx)
                if key in seen:
                    continue
                row = neighbor_map.get(idx)
                if row is None:
                    continue
                seen.add(key)
                distance = hit.distance if idx == hit.chunk_index else hit.distance + 0.02
                expanded.append(
                    RetrievalHit(
                        document_id=row.document_id,
                        document_name=row.document_name,
                        content=row.content,
                        source_page=row.source_page,
                        chunk_index=row.chunk_index,
                        distance=distance,
                    )
                )
        expanded.sort(key=lambda row: row.distance)
        return expanded

    def _rerank(self, query: str, hits: list[RetrievalHit]) -> list[RetrievalHit]:
        query_terms = _tokenize(query)
        rescored: list[tuple[RetrievalHit, float]] = []
        min_overlap = self.settings.rerank_min_lexical_overlap

        for hit in hits:
            if hit.distance > self.settings.rag_max_distance:
                continue
            lexical_overlap = 0.0
            if query_terms:
                content_terms = _tokenize(hit.content)
                if content_terms:
                    lexical_overlap = len(query_terms & content_terms) / min(len(query_terms), 48)
            if lexical_overlap < min_overlap:
                continue
            vector_score = 1.0 - min(max(hit.distance, 0.0), 1.0)
            combined = (
                self.settings.rerank_vector_weight * vector_score
                + self.settings.rerank_lexical_weight * lexical_overlap
            )
            rescored.append((hit, combined))

        rescored.sort(key=lambda row: row[1], reverse=True)
        if rescored:
            return [hit for hit, _ in rescored]
        return sorted(hits, key=lambda row: row.distance)

    def ask_text(
        self,
        user_id: str,
        question: str,
        *,
        session_id: str | None = None,
    ) -> tuple[str, list[RetrievalHit], str]:
        llm, context, active_session, messages, prompt = self.prepare_chat(
            user_id, question, session_id=session_id
        )
        answer = llm.chat_completion(prompt, messages=messages, temperature=0.2)
        self.repo.append_chat_message(active_session, "user", question)
        self.repo.append_chat_message(active_session, "assistant", answer)
        return answer, context, active_session

    def prepare_chat(
        self,
        user_id: str,
        question: str,
        *,
        session_id: str | None = None,
    ) -> tuple[LLMClient, list[RetrievalHit], str, list[dict[str, str]], str]:
        llm = LLMClient(self.user_settings.llm_config_for_chat(user_id))
        context = self.retrieve_context(user_id, question)
        history_messages: list[dict[str, str]] = []
        active_session = session_id or str(uuid.uuid4())
        if session_id:
            if not self.repo.get_chat_session(user_id, session_id):
                raise HTTPException(status_code=404, detail="Chat session not found.")
        else:
            title = question.strip()[:120] or "New chat"
            self.repo.create_chat_session(user_id, active_session, title)
        prior = self.repo.get_recent_chat_messages(active_session, self.settings.chat_history_limit)
        for row in prior:
            history_messages.append({"role": row.role, "content": row.content})
        prompt = self.build_prompt(question, context)
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a universal contextual assistant. Answer in the user's language. "
                    "Use the RAG context as the primary source of facts."
                ),
            },
            *history_messages,
            {"role": "user", "content": prompt},
        ]
        return llm, context, active_session, messages, prompt

    def ask_stream(
        self,
        user_id: str,
        question: str,
        *,
        session_id: str | None = None,
    ):
        llm, context, active_session, messages, prompt = self.prepare_chat(
            user_id, question, session_id=session_id
        )
        chunks: list[str] = []
        for token in llm.chat_completion_stream(prompt, messages=messages, temperature=0.2):
            chunks.append(token)
            yield {"type": "token", "text": token}
        answer = "".join(chunks).strip()
        self.repo.append_chat_message(active_session, "user", question)
        self.repo.append_chat_message(active_session, "assistant", answer)
        yield {
            "type": "done",
            "answer": answer,
            "session_id": active_session,
            "matches": [match.model_dump() for match in self.to_matches(context)],
        }

    def build_prompt(self, question: str, hits: list[RetrievalHit]) -> str:
        context = self._format_context(hits)
        return (
            "Use the RAG context below as the primary source of facts.\n"
            "Give a detailed, well-structured answer and synthesize information across all relevant fragments.\n"
            "If fragments overlap, merge them instead of repeating. Cite document names and page numbers when useful.\n"
            "If the context is insufficient, say so clearly.\n\n"
            f"RAG context:\n{context}\n\n"
            f"User question: {question}"
        )

    def _format_context(self, hits: list[RetrievalHit]) -> str:
        if not hits:
            return "No relevant context found."
        remaining = self.settings.rag_context_budget_chars
        blocks: list[str] = []
        for hit in hits:
            if remaining <= 0:
                break
            page = f", page {hit.source_page}" if hit.source_page else ""
            header = f"[{hit.document_name}{page}, chunk {hit.chunk_index}]"
            max_len = min(len(hit.content), self.settings.rag_prompt_max_chunk_chars, remaining)
            blocks.append(f"{header}\n{hit.content[:max_len]}")
            remaining -= max_len
        return "\n\n".join(blocks)

    @staticmethod
    def to_matches(hits: list[RetrievalHit]) -> list[RAGMatch]:
        best: dict[tuple[str, int], RetrievalHit] = {}
        for hit in hits:
            key = (hit.document_id, hit.chunk_index)
            if key not in best or hit.distance < best[key].distance:
                best[key] = hit
        ordered = sorted(best.values(), key=lambda row: row.distance)
        return [
            RAGMatch(
                document_id=hit.document_id,
                document_name=hit.document_name,
                content=hit.content[:3500],
                source_page=hit.source_page,
                chunk_index=hit.chunk_index,
                score=max(0.0, min(1.0, 1.0 - hit.distance)),
            )
            for hit in ordered
        ]

    def migrate_legacy_docs_to_user(self, user_id: str = SYSTEM_USER_ID) -> int:
        legacy_dir = self.settings.docs_dir
        target_dir = self.docs_dir_for(user_id)
        if legacy_dir.resolve() == target_dir.resolve():
            return 0
        moved = 0
        if not legacy_dir.exists():
            return 0
        target_dir.mkdir(parents=True, exist_ok=True)
        for path in legacy_dir.iterdir():
            if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
                destination = target_dir / path.name
                if not destination.exists():
                    destination.write_bytes(path.read_bytes())
                    path.unlink(missing_ok=True)
                    moved += 1
        return moved
