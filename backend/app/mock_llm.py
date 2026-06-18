from __future__ import annotations

import hashlib
import os
from typing import Iterator


def is_mock_enabled() -> bool:
    return os.getenv("LLM_MOCK", "").strip().lower() in {"1", "true", "yes", "on"}


def mock_chat_completion(prompt: str, *, messages: list[dict[str, str]] | None = None) -> str:
    if messages and len(messages) > 2:
        return f"Mock follow-up answer for: {prompt[:80]}"
    return f"Mock answer for: {prompt[:120]}"


def mock_chat_stream(prompt: str, *, messages: list[dict[str, str]] | None = None) -> Iterator[str]:
    text = mock_chat_completion(prompt, messages=messages)
    for word in text.split():
        yield word + " "


def mock_embedding(text: str, dim: int) -> list[float]:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    values: list[float] = []
    while len(values) < dim:
        for byte in digest:
            values.append((byte / 255.0) * 2.0 - 1.0)
            if len(values) >= dim:
                break
        digest = hashlib.sha256(digest).digest()
    return values[:dim]
