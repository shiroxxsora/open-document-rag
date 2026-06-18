from dataclasses import replace
from pathlib import Path

from app.config import load_settings
from app.ingestion import chunk_document, read_document, read_document_content
from app.models import IngestDocument, TextUnit
from app.text_sanitize import sanitize_pg_text


def _settings_for(tmp_path: Path):
    return replace(load_settings(), docs_dir=tmp_path, page_cache_dir=tmp_path / "cache")


def test_sanitize_pg_text_removes_nul_bytes():
    assert sanitize_pg_text("hel\x00lo") == "hello"
    assert sanitize_pg_text(None) is None
    assert sanitize_pg_text("clean") == "clean"


def test_read_document_content_strips_nul_bytes(tmp_path: Path):
    settings = _settings_for(tmp_path)
    path = tmp_path / "bad.txt"
    path.write_bytes(b"before\x00after")
    assert read_document_content(settings, path) == "beforeafter"


def test_chunk_document_strips_nul_bytes(tmp_path: Path):
    settings = _settings_for(tmp_path)
    document = IngestDocument(
        document_id="bad.txt",
        file_name="bad.txt",
        content="line\x00one",
        units=[TextUnit(text="line\x00one", page=None)],
    )
    chunks = chunk_document(settings, document)
    assert chunks
    assert "\x00" not in chunks[0].text


def test_read_document_from_txt_with_nul_bytes(tmp_path: Path):
    settings = _settings_for(tmp_path)
    path = tmp_path / "bad.txt"
    path.write_bytes(b"hello\x00world")
    document = read_document(settings, path)
    assert document is not None
    assert document.content == "helloworld"
    assert "\x00" not in document.content
