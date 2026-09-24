"""Embedding provider strategy — abstract base and concrete implementations.

Supports:
  - VoyageEmbeddingProvider: Real voyage-code-4 API via urllib.request (stdlib).
  - OpenRouterEmbeddingProvider: OpenRouter embeddings API via urllib.request (stdlib).
  - FakeEmbeddingProvider: Deterministic fake for tests.

Each provider produces embeddings as lists of floats with a configurable
dimension.
"""

from __future__ import annotations

import json
import os
import shutil
import struct
import subprocess
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from typing import Any


class EmbeddingProvider(ABC):
    """Abstract base for embedding providers."""

    @abstractmethod
    def embed_documents(self, texts: list[str], *, input_type: str = "document") -> list[list[float]]:
        """Embed a list of document texts.

        Returns a list of embedding vectors (list of floats).
        """
        ...

    @abstractmethod
    def embed_query(self, text: str, *, input_type: str = "query") -> list[float]:
        """Embed a single query string.

        Returns an embedding vector (list of floats).
        """
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Return the model identifier (e.g. 'voyage-code-4')."""
        ...

    @property
    @abstractmethod
    def dimensions(self) -> int:
        """Return the embedding dimension."""
        ...

    def raw_bytes(self, vector: list[float]) -> bytes:
        """Serialize a float vector to raw bytes (float32 little-endian)."""
        return struct.pack(f"<{len(vector)}f", *vector)

    def from_bytes(self, data: bytes) -> list[float]:
        """Deserialize raw bytes back to a float vector."""
        n = len(data) // 4
        return list(struct.unpack(f"<{n}f", data))


class VoyageEmbeddingProvider(EmbeddingProvider):
    """Real voyage-code-4 embedding provider via the Voyage API.

    Uses the official Voyage AI embeddings API:
      POST https://api.voyageai.com/v1/embeddings
    """

    API_URL = "https://api.voyageai.com/v1/embeddings"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        dimensions: int = 512,
        timeout: int = 60,
        batch_size: int = 128,
    ):
        if not api_key:
            api_key = os.environ.get("VOYAGE_API_KEY", "")
        if not api_key or not api_key.strip():
            raise ValueError(
                "VOYAGE_API_KEY is required. Set the environment variable or pass api_key."
            )
        self._api_key = api_key
        self._model = model or os.environ.get("VOYAGE_MODEL", "voyage-code-4")
        self._dimensions = dimensions
        self._timeout = timeout
        if not 1 <= batch_size <= 128:
            raise ValueError("batch_size must be between 1 and 128")
        self._batch_size = batch_size

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def embed_documents(
        self, texts: list[str], *, input_type: str = "document"
    ) -> list[list[float]]:
        """Embed documents in Voyage batches while preserving input order."""
        result: list[list[float]] = []
        for offset in range(0, len(texts), self._batch_size):
            batch = texts[offset:offset + self._batch_size]
            try:
                result.extend(self._call_api(batch, input_type=input_type))
            except (RuntimeError, OSError, ValueError) as exc:
                batch_number = offset // self._batch_size + 1
                raise RuntimeError(
                    f"Voyage embedding batch {batch_number} failed: {exc}"
                ) from exc
        return result

    def embed_query(self, text: str, *, input_type: str = "query") -> list[float]:
        """Embed a query using voyage-code-4 with input_type='query'."""
        result = self._call_api([text], input_type=input_type)
        return result[0]

    def _call_api(
        self, texts: list[str], *, input_type: str
    ) -> list[list[float]]:
        """Make the actual API call to Voyage AI via stdlib urllib.request.

        Empty texts are filtered out before the API call; the returned list
        is mapped back to the original text order (empty lists for skipped
        texts).
        """
        # Track which original indices are non-empty
        valid_indices: list[int] = []
        valid_texts: list[str] = []
        for i, t in enumerate(texts):
            if t.strip():
                valid_indices.append(i)
                valid_texts.append(t)

        if not valid_texts:
            return [[] for _ in texts]

        payload: dict[str, Any] = {
            "model": self._model,
            "input": valid_texts,
            "input_type": input_type,
        }
        if self._dimensions:
            payload["output_dimension"] = self._dimensions

        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.API_URL,
            data=body,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            # Read minimal error info — never include response body (may
            # echo sensitive content).
            raise RuntimeError(
                f"Voyage API error {exc.code}: {exc.reason}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"Voyage API connection error: {exc.reason}"
            ) from exc
        except OSError as exc:
            raise RuntimeError(
                f"Voyage API request failed: {exc}"
            ) from exc
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise RuntimeError("Voyage API returned malformed JSON") from exc

        try:
            items = data["data"]
            if not isinstance(items, list) or len(items) != len(valid_texts):
                raise ValueError("embedding count mismatch")
            by_index: dict[int, list[float]] = {}
            for item in items:
                if not isinstance(item, dict):
                    raise ValueError("malformed embedding item")
                index = item.get("index")
                embedding = item.get("embedding")
                if not isinstance(index, int) or isinstance(index, bool):
                    raise ValueError("invalid embedding index")
                if index < 0 or index >= len(valid_texts) or index in by_index:
                    raise ValueError("duplicate or out-of-range embedding index")
                if not isinstance(embedding, list) or len(embedding) != self._dimensions:
                    raise ValueError("embedding dimension mismatch")
                if not all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in embedding):
                    raise ValueError("malformed embedding vector")
                by_index[index] = [float(value) for value in embedding]
            valid_embeddings = [by_index[index] for index in range(len(valid_texts))]
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError(f"Voyage API response validation failed: {exc}") from exc

        # Map back to original text order
        result: list[list[float] | None] = [None] * len(texts)
        for orig_idx, emb in zip(valid_indices, valid_embeddings):
            result[orig_idx] = emb
        # Fill in empty lists for skipped texts
        return [r if r is not None else [] for r in result]


class FakeEmbeddingProvider(EmbeddingProvider):
    """Deterministic fake embedding provider for testing.

    Produces embedding vectors where each dimension is a deterministic
    function of the text content and dimension index.
    """

    def __init__(self, dimensions: int = 512, model: str = "fake-embedding-v1"):
        self._dimensions = dimensions
        self._model = model

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def _derive(self, text: str, seed: int = 0) -> list[float]:
        """Deterministic embedding from text content."""
        import hashlib

        h = hashlib.sha256(f"{text}:{seed}".encode("utf-8")).hexdigest()
        # Use the hash to seed a deterministic pseudo-random sequence
        vals: list[float] = []
        for i in range(self._dimensions):
            # Mix hash bytes with position
            h2 = hashlib.sha256(f"{h}:{i}:{seed}".encode("utf-8")).hexdigest()
            # Convert first 8 hex chars to a float in [0, 1)
            chunk = int(h2[:8], 16) / 0xFFFFFFFF
            vals.append(chunk)
        return vals

    def embed_documents(
        self, texts: list[str], *, input_type: str = "document"
    ) -> list[list[float]]:
        seed = 1 if input_type == "document" else 2
        return [self._derive(t, seed) for t in texts]

    def embed_query(self, text: str, *, input_type: str = "query") -> list[float]:
        return self._derive(text, 2 if input_type == "query" else 1)


class OpenRouterEmbeddingProvider(EmbeddingProvider):
    """OpenRouter OpenAI-compatible embedding provider via OpenRouter API.

    Uses the OpenRouter embeddings API:
      POST https://openrouter.ai/api/v1/embeddings
    """

    API_URL = "https://openrouter.ai/api/v1/embeddings"
    DEFAULT_MODEL = "voyage-4"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        dimensions: int = 512,
        timeout: int = 60,
        batch_size: int = 128,
        base_url: str | None = None,
    ):
        if not api_key:
            api_key = os.environ.get("OPENROUTER_API_KEY", "")
        if not api_key or not api_key.strip():
            raise ValueError(
                "OPENROUTER_API_KEY is required. Set the environment variable or pass api_key."
            )
        self._api_key = api_key
        self._model = model or os.environ.get("OPENROUTER_MODEL", self.DEFAULT_MODEL)
        self._dimensions = dimensions
        self._timeout = timeout
        if not 1 <= batch_size <= 2048:
            raise ValueError("batch_size must be between 1 and 2048")
        self._batch_size = batch_size

        url = base_url or os.environ.get("OPENROUTER_BASE_URL", self.API_URL)
        if not url.endswith("/embeddings"):
            url = url.rstrip("/") + "/embeddings"
        self._api_url = url

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def embed_documents(
        self, texts: list[str], *, input_type: str = "document"
    ) -> list[list[float]]:
        """Embed documents in OpenRouter batches while preserving input order."""
        result: list[list[float]] = []
        for offset in range(0, len(texts), self._batch_size):
            batch = texts[offset:offset + self._batch_size]
            try:
                result.extend(self._call_api(batch, input_type=input_type))
            except (RuntimeError, OSError, ValueError) as exc:
                batch_number = offset // self._batch_size + 1
                raise RuntimeError(
                    f"OpenRouter embedding batch {batch_number} failed: {exc}"
                ) from exc
        return result

    def embed_query(self, text: str, *, input_type: str = "query") -> list[float]:
        """Embed a query using OpenRouter."""
        result = self._call_api([text], input_type=input_type)
        return result[0]

    def _call_api(
        self, texts: list[str], *, input_type: str | None = None
    ) -> list[list[float]]:
        """Make the actual API call to OpenRouter via stdlib urllib.request.

        Empty texts are filtered out before the API call; the returned list
        is mapped back to the original text order (empty lists for skipped
        texts).
        """
        valid_indices: list[int] = []
        valid_texts: list[str] = []
        for i, t in enumerate(texts):
            if t.strip():
                valid_indices.append(i)
                valid_texts.append(t)

        if not valid_texts:
            return [[] for _ in texts]

        payload: dict[str, Any] = {
            "model": self._model,
            "input": valid_texts,
        }
        if self._dimensions:
            payload["dimensions"] = self._dimensions
        if input_type:
            payload["input_type"] = input_type

        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self._api_url,
            data=body,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/delorenj/codegraph-voyage",
                "X-Title": "codegraph-voyage",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            err_detail = ""
            try:
                raw_err = exc.read().decode("utf-8", errors="replace")
                parsed_err = json.loads(raw_err)
                if isinstance(parsed_err, dict) and "error" in parsed_err:
                    err_obj = parsed_err["error"]
                    if isinstance(err_obj, dict):
                        err_detail = f": {err_obj.get('message', '')}"
                    else:
                        err_detail = f": {err_obj}"
            except Exception:
                pass
            raise RuntimeError(
                f"OpenRouter API error {exc.code}: {exc.reason}{err_detail}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"OpenRouter API connection error: {exc.reason}"
            ) from exc
        except OSError as exc:
            raise RuntimeError(
                f"OpenRouter API request failed: {exc}"
            ) from exc
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise RuntimeError("OpenRouter API returned malformed JSON") from exc

        if isinstance(data, dict) and "error" in data:
            err_msg = data["error"]
            if isinstance(err_msg, dict):
                err_msg = err_msg.get("message", str(err_msg))
            raise RuntimeError(f"OpenRouter API error: {err_msg}")

        try:
            items = data["data"]
            if not isinstance(items, list) or len(items) != len(valid_texts):
                raise ValueError("embedding count mismatch")
            by_index: dict[int, list[float]] = {}
            for item in items:
                if not isinstance(item, dict):
                    raise ValueError("malformed embedding item")
                index = item.get("index")
                embedding = item.get("embedding")
                if not isinstance(index, int) or isinstance(index, bool):
                    raise ValueError("invalid embedding index")
                if index < 0 or index >= len(valid_texts) or index in by_index:
                    raise ValueError("duplicate or out-of-range embedding index")
                if not isinstance(embedding, list):
                    raise ValueError("malformed embedding vector")
                if self._dimensions and len(embedding) != self._dimensions:
                    raise ValueError("embedding dimension mismatch")
                if not all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in embedding):
                    raise ValueError("malformed embedding vector")
                by_index[index] = [float(value) for value in embedding]
            valid_embeddings = [by_index[index] for index in range(len(valid_texts))]
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError(f"OpenRouter API response validation failed: {exc}") from exc

        # If dimensions was not specified, infer from first result
        if not self._dimensions and valid_embeddings:
            self._dimensions = len(valid_embeddings[0])

        # Map back to original text order
        result: list[list[float] | None] = [None] * len(texts)
        for orig_idx, emb in zip(valid_indices, valid_embeddings):
            result[orig_idx] = emb
        return [r if r is not None else [] for r in result]


class AutomaticAIEmbeddingProvider(EmbeddingProvider):
    """AutomaticAI gateway OpenAI-compatible embedding provider.

    Proxies embedding requests via the private NewAPI gateway:
      POST https://api.automaticai.io/v1/embeddings
    """

    API_URL = "https://api.automaticai.io/v1/embeddings"
    DEFAULT_MODEL = "voyage-4"
    DEFAULT_USER_AGENT = "automaticai-client/1.0 (+codegraph-voyage)"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        dimensions: int = 512,
        timeout: int = 60,
        batch_size: int = 128,
        base_url: str | None = None,
    ):
        if not api_key:
            api_key = (
                os.environ.get("AUTOMATICAI_API_KEY", "")
                or os.environ.get("NEWAPI_API_KEY", "")
            )
        if not api_key or not api_key.strip():
            # Transparent fallback to 1Password if `op` CLI is available
            if shutil.which("op"):
                try:
                    res = subprocess.run(
                        ["op", "read", "op://DeLoSecrets/NewAPI Virtual Keys/codegraph-voyage"],
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    if res.returncode == 0 and res.stdout.strip():
                        api_key = res.stdout.strip()
                except Exception:
                    pass
        if not api_key or not api_key.strip():
            raise ValueError(
                "AUTOMATICAI_API_KEY is required. Set the environment variable, "
                "pass api_key, or provision op://DeLoSecrets/NewAPI Virtual Keys/codegraph-voyage."
            )
        self._api_key = api_key
        self._model = model or os.environ.get("AUTOMATICAI_MODEL", self.DEFAULT_MODEL)
        self._dimensions = dimensions
        self._timeout = timeout
        if not 1 <= batch_size <= 2048:
            raise ValueError("batch_size must be between 1 and 2048")
        self._batch_size = batch_size

        url = base_url or os.environ.get("AUTOMATICAI_BASE_URL", self.API_URL)
        if not url.endswith("/embeddings"):
            url = url.rstrip("/") + "/embeddings"
        self._api_url = url

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def embed_documents(
        self, texts: list[str], *, input_type: str = "document"
    ) -> list[list[float]]:
        """Embed documents in AutomaticAI batches while preserving input order."""
        result: list[list[float]] = []
        for offset in range(0, len(texts), self._batch_size):
            batch = texts[offset : offset + self._batch_size]
            try:
                result.extend(self._call_api(batch, input_type=input_type))
            except (RuntimeError, OSError, ValueError) as exc:
                batch_number = offset // self._batch_size + 1
                raise RuntimeError(
                    f"AutomaticAI embedding batch {batch_number} failed: {exc}"
                ) from exc
        return result

    def embed_query(self, text: str, *, input_type: str = "query") -> list[float]:
        """Embed a query using AutomaticAI gateway."""
        result = self._call_api([text], input_type=input_type)
        return result[0]

    def _call_api(
        self, texts: list[str], *, input_type: str | None = None
    ) -> list[list[float]]:
        valid_indices: list[int] = []
        valid_texts: list[str] = []
        for i, t in enumerate(texts):
            if t.strip():
                valid_indices.append(i)
                valid_texts.append(t)

        if not valid_texts:
            return [[] for _ in texts]

        payload: dict[str, Any] = {
            "model": self._model,
            "input": valid_texts,
        }
        if self._dimensions:
            payload["dimensions"] = self._dimensions
        if input_type:
            payload["input_type"] = input_type

        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self._api_url,
            data=body,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "User-Agent": self.DEFAULT_USER_AGENT,
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            err_detail = ""
            try:
                raw_err = exc.read().decode("utf-8", errors="replace")
                parsed_err = json.loads(raw_err)
                if isinstance(parsed_err, dict) and "error" in parsed_err:
                    err_obj = parsed_err["error"]
                    if isinstance(err_obj, dict):
                        err_detail = f": {err_obj.get('message', '')}"
                    else:
                        err_detail = f": {err_obj}"
            except Exception:
                pass
            raise RuntimeError(
                f"AutomaticAI API error {exc.code}: {exc.reason}{err_detail}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"AutomaticAI API connection error: {exc.reason}"
            ) from exc
        except OSError as exc:
            raise RuntimeError(
                f"AutomaticAI API request failed: {exc}"
            ) from exc
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise RuntimeError("AutomaticAI API returned malformed JSON") from exc

        if isinstance(data, dict) and "error" in data:
            err_msg = data["error"]
            if isinstance(err_msg, dict):
                err_msg = err_msg.get("message", str(err_msg))
            raise RuntimeError(f"AutomaticAI API error: {err_msg}")

        try:
            items = data["data"]
            if not isinstance(items, list) or len(items) != len(valid_texts):
                raise ValueError("embedding count mismatch")
            by_index: dict[int, list[float]] = {}
            for item in items:
                if not isinstance(item, dict):
                    raise ValueError("malformed embedding item")
                index = item.get("index")
                embedding = item.get("embedding")
                if not isinstance(index, int) or isinstance(index, bool):
                    raise ValueError("invalid embedding index")
                if index < 0 or index >= len(valid_texts) or index in by_index:
                    raise ValueError("duplicate or out-of-range embedding index")
                if not isinstance(embedding, list):
                    raise ValueError("malformed embedding vector")
                if self._dimensions and len(embedding) != self._dimensions:
                    raise ValueError("embedding dimension mismatch")
                if not all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in embedding):
                    raise ValueError("malformed embedding vector")
                by_index[index] = [float(value) for value in embedding]
            valid_embeddings = [by_index[index] for index in range(len(valid_texts))]
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError(f"AutomaticAI API response validation failed: {exc}") from exc

        if not self._dimensions and valid_embeddings:
            self._dimensions = len(valid_embeddings[0])

        result: list[list[float] | None] = [None] * len(texts)
        for orig_idx, emb in zip(valid_indices, valid_embeddings):
            result[orig_idx] = emb
        return [r if r is not None else [] for r in result]


def create_provider(
    provider_name: str = "voyage",
    *,
    api_key: str | None = None,
    model: str | None = None,
    dimensions: int = 512,
    base_url: str | None = None,
    timeout: int = 60,
    batch_size: int = 128,
) -> EmbeddingProvider:
    """Factory: create an embedding provider by name.

    Supports:
      - 'automaticai' (or 'automatic_ai', 'aai'): AutomaticAI LLM gateway.
      - 'voyage': Voyage AI embeddings API.
      - 'openrouter' (or 'open_router'): OpenRouter OpenAI-compatible embeddings API.
      - 'fake': Deterministic fake for tests.
    """
    normalized = provider_name.lower().replace("-", "_")
    if normalized in ("automaticai", "automatic_ai", "aai"):
        return AutomaticAIEmbeddingProvider(
            api_key=api_key,
            model=model,
            dimensions=dimensions,
            timeout=timeout,
            batch_size=batch_size,
            base_url=base_url,
        )
    elif normalized == "voyage":
        return VoyageEmbeddingProvider(
            api_key=api_key,
            model=model,
            dimensions=dimensions,
            timeout=timeout,
            batch_size=batch_size,
        )
    elif normalized in ("openrouter", "open_router"):
        return OpenRouterEmbeddingProvider(
            api_key=api_key,
            model=model,
            dimensions=dimensions,
            timeout=timeout,
            batch_size=batch_size,
            base_url=base_url,
        )
    elif normalized == "fake":
        return FakeEmbeddingProvider(dimensions=dimensions)
    else:
        raise ValueError(
            f"Unknown provider: {provider_name}. Use 'automaticai', 'voyage', 'openrouter', or 'fake'."
        )

