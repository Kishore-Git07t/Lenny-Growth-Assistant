"""Ollama vector embedding client for nomic-embed-text."""

import logging
import math
import time
from typing import Any, Dict, List, Optional, Union

import httpx

logger = logging.getLogger(__name__)

# Standard prefixes for nomic-embed-text asymmetric retrieval
DEFAULT_DOC_PREFIX: str = "search_document: "
DEFAULT_QUERY_PREFIX: str = "search_query: "
EXPECTED_EMBEDDING_DIMENSIONS: int = 768


class EmbeddingError(Exception):
    """Base exception for all embedding generation and validation errors."""
    pass


class OllamaConnectionError(EmbeddingError):
    """Raised when the Ollama server cannot be reached."""
    pass


class OllamaTimeoutError(EmbeddingError):
    """Raised when an embedding request to Ollama times out."""
    pass


class OllamaResponseError(EmbeddingError):
    """Raised when Ollama returns an unexpected status code or malformed JSON payload."""
    pass


class EmbeddingDimensionError(EmbeddingError):
    """Raised when an embedding vector does not match the expected dimensionality or contains non-finite values."""
    pass


class OllamaEmbeddingClient:
    """Client for generating 768-D vector embeddings via Ollama's /api/embed endpoint."""

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "nomic-embed-text",
        dimensions: int = EXPECTED_EMBEDDING_DIMENSIONS,
        timeout_seconds: float = 60.0,
        max_retries: int = 3,
        backoff_factor: float = 0.5,
        http_client: Optional[httpx.Client] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.dimensions = dimensions
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self._http_client = http_client
        self._endpoint = f"{self.base_url}/api/embed"

    def _get_client(self) -> httpx.Client:
        """Return the injected HTTP client or create a new one."""
        if self._http_client is not None:
            return self._http_client
        return httpx.Client(timeout=self.timeout_seconds)

    def validate_vector(self, vector: Any, index: int = 0) -> List[float]:
        """Validate that an individual vector has exactly the expected dimensions and finite values.

        Raises:
            EmbeddingDimensionError: If vector length differs from expected dimensions
                                    or if any element is NaN, Inf, or non-numeric.
        """
        if not isinstance(vector, (list, tuple)):
            raise EmbeddingDimensionError(
                f"Embedding at index {index} is of type {type(vector).__name__}, expected list."
            )

        actual_len = len(vector)
        if actual_len != self.dimensions:
            raise EmbeddingDimensionError(
                f"Embedding at index {index} has {actual_len} dimensions; expected exactly {self.dimensions}."
            )

        clean_vector: List[float] = []
        for elem_idx, val in enumerate(vector):
            try:
                f_val = float(val)
            except (ValueError, TypeError) as conv_err:
                raise EmbeddingDimensionError(
                    f"Embedding at index {index}, dimension {elem_idx} cannot be converted to float: {conv_err}"
                )

            if not math.isfinite(f_val):
                raise EmbeddingDimensionError(
                    f"Embedding at index {index}, dimension {elem_idx} contains non-finite value: {f_val}"
                )
            clean_vector.append(f_val)

        return clean_vector

    def embed_texts(
        self,
        texts: List[str],
        prefix: str = DEFAULT_DOC_PREFIX,
    ) -> List[List[float]]:
        """Generate validated vector embeddings for a list of input texts.

        Args:
            texts: List of text strings to embed.
            prefix: Prefix to prepend to each text (e.g. 'search_document: ').

        Returns:
            List of 768-D float lists corresponding 1:1 with input texts.

        Raises:
            ValueError: If texts list is empty.
            OllamaConnectionError: If Ollama server is unreachable.
            OllamaTimeoutError: If request times out.
            OllamaResponseError: If Ollama returns an error or malformed response.
            EmbeddingDimensionError: If returned vectors have invalid dimensions or non-finite numbers.
        """
        if not texts:
            raise ValueError("Input texts list cannot be empty.")

        # Prepend prefix to each text input
        prepared_inputs = [f"{prefix}{t}" if not t.startswith(prefix) else t for t in texts]

        payload: Dict[str, Any] = {
            "model": self.model,
            "input": prepared_inputs,
        }

        client = self._get_client()
        should_close_client = self._http_client is None

        attempt = 0
        last_exception: Optional[Exception] = None

        while attempt < self.max_retries:
            attempt += 1
            try:
                response = client.post(
                    self._endpoint,
                    json=payload,
                    timeout=self.timeout_seconds,
                )

                if response.status_code == 404:
                    # Model not found or endpoint missing — not transient
                    raise OllamaResponseError(
                        f"Ollama returned 404 for model '{self.model}'. Ensure model is pulled: ollama pull {self.model}"
                    )

                if response.status_code != 200:
                    err_text = response.text[:200]
                    if response.status_code >= 500 and attempt < self.max_retries:
                        # Server error, transient retry
                        time.sleep(self.backoff_factor * (2 ** (attempt - 1)))
                        continue
                    raise OllamaResponseError(
                        f"Ollama returned HTTP {response.status_code}: {err_text}"
                    )

                try:
                    data = response.json()
                except Exception as json_err:
                    raise OllamaResponseError(f"Failed to parse Ollama JSON response: {json_err}")

                if not isinstance(data, dict) or "embeddings" not in data:
                    raise OllamaResponseError(
                        f"Ollama response missing 'embeddings' field. Keys returned: {list(data.keys()) if isinstance(data, dict) else type(data)}"
                    )

                raw_embeddings = data["embeddings"]
                if not isinstance(raw_embeddings, list):
                    raise OllamaResponseError(
                        f"Expected 'embeddings' to be a list, got {type(raw_embeddings).__name__}."
                    )

                if len(raw_embeddings) != len(texts):
                    raise OllamaResponseError(
                        f"Ollama returned {len(raw_embeddings)} embeddings for {len(texts)} input texts."
                    )

                # Validate dimensions and numeric integrity for each vector
                validated_vectors: List[List[float]] = [
                    self.validate_vector(vec, idx)
                    for idx, vec in enumerate(raw_embeddings)
                ]

                return validated_vectors

            except httpx.ConnectError as conn_err:
                last_exception = OllamaConnectionError(
                    f"Unable to connect to Ollama at {self._endpoint}. Is Ollama running? Error: {conn_err}"
                )
            except httpx.TimeoutException as timeout_err:
                last_exception = OllamaTimeoutError(
                    f"Ollama embedding request timed out after {self.timeout_seconds}s: {timeout_err}"
                )
            except (OllamaResponseError, EmbeddingDimensionError):
                # Non-transient validation/response errors are raised immediately
                if should_close_client:
                    client.close()
                raise
            except Exception as unhandled_err:
                last_exception = EmbeddingError(f"Unexpected error communicating with Ollama: {unhandled_err}")

            # Transient backoff delay
            if attempt < self.max_retries:
                sleep_time = self.backoff_factor * (2 ** (attempt - 1))
                logger.warning(
                    "Ollama request attempt %d/%d failed; retrying in %.2fs. (Inputs: %d)",
                    attempt,
                    self.max_retries,
                    sleep_time,
                    len(texts),
                )
                time.sleep(sleep_time)

        if should_close_client:
            client.close()

        if last_exception:
            raise last_exception
        raise EmbeddingError(f"Failed to generate embeddings after {self.max_retries} attempts.")

    def embed_single(
        self,
        text: str,
        prefix: str = DEFAULT_DOC_PREFIX,
    ) -> List[float]:
        """Convenience method to generate a validated embedding for a single text."""
        vectors = self.embed_texts([text], prefix=prefix)
        return vectors[0]

    def embed_query(
        self,
        query: str,
    ) -> List[float]:
        """Generate a validated 768-D embedding vector for a search query.

        Uses the standard 'search_query: ' prefix required for nomic-embed-text
        asymmetric document retrieval.

        Args:
            query: User search query or question text.

        Returns:
            Validated 768-D float vector.

        Raises:
            ValueError: If query is empty or whitespace-only.
            EmbeddingError: If Ollama fails or returns invalid dimensions.
        """
        if not query or not query.strip():
            raise ValueError("Search query cannot be empty or whitespace-only.")

        cleaned_query = query.strip()
        vectors = self.embed_texts([cleaned_query], prefix=DEFAULT_QUERY_PREFIX)
        return vectors[0]
