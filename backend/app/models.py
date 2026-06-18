from dataclasses import dataclass


@dataclass(frozen=True)
class TextUnit:
    text: str
    page: str | None


@dataclass(frozen=True)
class IngestDocument:
    document_id: str
    file_name: str
    content: str
    units: list[TextUnit]


@dataclass(frozen=True)
class ChunkRecord:
    text: str
    page: str | None


@dataclass(frozen=True)
class RetrievalHit:
    document_id: str
    document_name: str
    content: str
    source_page: str | None
    chunk_index: int
    distance: float
