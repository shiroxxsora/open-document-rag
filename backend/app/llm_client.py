import json
import os
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterator
from urllib.parse import urlparse, urlunparse

from fastapi import HTTPException

if TYPE_CHECKING:
    from app.config import Settings


@dataclass(frozen=True)
class LLMConfig:
    llm_api_url: str
    llm_api_key: str
    llm_model: str
    llm_timeout_sec: int
    embedding_api_url: str
    embedding_api_key: str
    embedding_model: str
    embedding_dim: int
    embedding_timeout_sec: int
    embedding_batch_size: int

    @classmethod
    def from_settings(cls, settings) -> "LLMConfig":
        from app.config import Settings as SettingsType

        assert isinstance(settings, SettingsType)
        return cls(
            llm_api_url=settings.llm_api_url,
            llm_api_key=settings.llm_api_key,
            llm_model=settings.llm_model,
            llm_timeout_sec=settings.llm_timeout_sec,
            embedding_api_url=settings.embedding_api_url,
            embedding_api_key=settings.llm_api_key,
            embedding_model=settings.embedding_model,
            embedding_dim=settings.embedding_dim,
            embedding_timeout_sec=settings.embedding_timeout_sec,
            embedding_batch_size=settings.embedding_batch_size,
        )


def _url_ipv4_for_host_docker_internal(url: str) -> str:
    parsed = urlparse(url)
    if (parsed.hostname or "").lower() != "host.docker.internal":
        return url
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo("host.docker.internal", port, socket.AF_INET, socket.SOCK_STREAM)
    except OSError:
        return url
    if not infos:
        return url
    ip = infos[0][4][0]
    netloc = f"{ip}:{parsed.port or port}"
    return urlunparse((parsed.scheme, netloc, parsed.path, parsed.params, parsed.query, parsed.fragment))


class LLMClient:
    def __init__(self, config: LLMConfig) -> None:
        self.config = config

    @classmethod
    def from_settings(cls, settings: "Settings") -> "LLMClient":
        return cls(LLMConfig.from_settings(settings))

    def _headers(self, api_key: str) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        if "openrouter.ai" in self.config.llm_api_url or "openrouter.ai" in self.config.embedding_api_url:
            headers["HTTP-Referer"] = "http://localhost:3000"
            headers["X-Title"] = "Universal RAG MVP"
        return headers

    def _post_json(self, url: str, payload: dict, timeout_sec: int, api_key: str) -> dict:
        request = urllib.request.Request(
            url=_url_ipv4_for_host_docker_internal(url),
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers=self._headers(api_key),
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_sec) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            error_text = exc.read().decode("utf-8", errors="ignore")
            raise HTTPException(status_code=502, detail=f"LLM API error: {error_text}") from exc
        except TimeoutError as exc:
            raise HTTPException(status_code=504, detail="LLM API timeout.") from exc
        except OSError as exc:
            raise HTTPException(status_code=502, detail=f"LLM API unavailable: {exc!s}") from exc
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=502, detail="LLM API returned invalid JSON.") from exc

    def get_embeddings(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if os.getenv("LLM_MOCK", "").strip().lower() in {"1", "true", "yes", "on"}:
            from app.mock_llm import mock_embedding

            return [mock_embedding(text, self.config.embedding_dim) for text in texts]
        output: list[list[float]] = []
        for start in range(0, len(texts), self.config.embedding_batch_size):
            batch = texts[start : start + self.config.embedding_batch_size]
            try:
                output.extend(self._get_embedding_batch(batch))
            except HTTPException:
                if len(batch) == 1:
                    raise
                for item in batch:
                    output.extend(self._get_embedding_batch([item]))
        return output

    def get_embedding(self, text: str) -> list[float]:
        return self.get_embeddings([text])[0]

    def _get_embedding_batch(self, texts: list[str]) -> list[list[float]]:
        body = self._post_json(
            self.config.embedding_api_url,
            {"model": self.config.embedding_model, "input": texts if len(texts) > 1 else texts[0]},
            self.config.embedding_timeout_sec,
            self.config.embedding_api_key,
        )
        try:
            rows = body["data"]
            rows = sorted(rows, key=lambda item: item.get("index", 0))
            embeddings = [row["embedding"] for row in rows]
        except (KeyError, TypeError) as exc:
            raise HTTPException(status_code=502, detail="Embedding API response has no data[].embedding.") from exc
        for embedding in embeddings:
            if len(embedding) != self.config.embedding_dim:
                raise HTTPException(
                    status_code=500,
                    detail=(
                        f"Expected embedding dimension {self.config.embedding_dim}, got {len(embedding)}. "
                        "Check EMBEDDING_MODEL and EMBEDDING_DIM."
                    ),
                )
        return embeddings

    def chat_completion(
        self,
        prompt: str,
        *,
        temperature: float = 0.2,
        messages: list[dict[str, str]] | None = None,
    ) -> str:
        if os.getenv("LLM_MOCK", "").strip().lower() in {"1", "true", "yes", "on"}:
            from app.mock_llm import mock_chat_completion

            return mock_chat_completion(prompt, messages=messages)
        payload_messages = messages or [{"role": "user", "content": prompt}]
        body = self._post_json(
            self.config.llm_api_url,
            {
                "model": self.config.llm_model,
                "messages": payload_messages,
                "temperature": temperature,
            },
            self.config.llm_timeout_sec,
            self.config.llm_api_key,
        )
        try:
            return str(body["choices"][0]["message"]["content"]).strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise HTTPException(status_code=502, detail="Chat API response has no choices[0].message.content.") from exc

    def chat_completion_stream(
        self,
        prompt: str,
        *,
        temperature: float = 0.2,
        messages: list[dict[str, str]] | None = None,
    ) -> Iterator[str]:
        if os.getenv("LLM_MOCK", "").strip().lower() in {"1", "true", "yes", "on"}:
            from app.mock_llm import mock_chat_stream

            yield from mock_chat_stream(prompt, messages=messages)
            return
        answer = self.chat_completion(prompt, temperature=temperature, messages=messages)
        for word in answer.split():
            yield word + " "
