"""Vector embedding package for Lenny's Podcast transcript chunks."""

from backend.app.embeddings.client import (
    DEFAULT_DOC_PREFIX,
    DEFAULT_QUERY_PREFIX,
    EXPECTED_EMBEDDING_DIMENSIONS,
    EmbeddingDimensionError,
    EmbeddingError,
    OllamaConnectionError,
    OllamaEmbeddingClient,
    OllamaResponseError,
    OllamaTimeoutError,
)
from backend.app.embeddings.service import (
    DEFAULT_BATCH_SIZE,
    MAX_ALLOWED_BATCH_SIZE,
    EmbeddingReport,
    TranscriptEmbeddingService,
    compute_embedding_input_checksum,
)

__all__ = [
    "DEFAULT_BATCH_SIZE",
    "DEFAULT_DOC_PREFIX",
    "DEFAULT_QUERY_PREFIX",
    "EXPECTED_EMBEDDING_DIMENSIONS",
    "MAX_ALLOWED_BATCH_SIZE",
    "EmbeddingDimensionError",
    "EmbeddingError",
    "EmbeddingReport",
    "OllamaConnectionError",
    "OllamaEmbeddingClient",
    "OllamaResponseError",
    "OllamaTimeoutError",
    "TranscriptEmbeddingService",
    "compute_embedding_input_checksum",
]
