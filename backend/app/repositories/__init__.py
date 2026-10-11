"""Database repositories package."""

from backend.app.repositories.session_repository import (
    create_session,
    get_session_by_id,
    list_sessions,
    touch_session,
    update_session,
)
from backend.app.repositories.message_repository import (
    create_message,
    list_messages_by_session,
)
from backend.app.repositories.episode_repository import (
    count_episodes,
    create_episode,
    get_episode_by_id,
    get_episode_by_slug,
    list_episodes,
    update_episode,
)
from backend.app.repositories.chunk_repository import (
    count_chunks,
    count_chunks_for_episode,
    create_chunks,
    delete_chunks_by_episode_id,
    get_chunk_checksum_for_episode,
    get_chunk_checksum_and_fingerprint_for_episode,
    get_chunks_by_episode_id,
)

from backend.app.repositories.embedding_repository import (
    count_embeddings,
    create_or_update_embedding,
    create_or_update_embeddings_batch,
    delete_embeddings_by_chunk_id,
    get_embedding_by_chunk_id,
    get_embedding_metadata_by_chunk_id,
    get_existing_embeddings_metadata_for_chunk_ids,
    get_index_coverage,
    semantic_search,
)

__all__ = [
    "create_session",
    "get_session_by_id",
    "list_sessions",
    "touch_session",
    "update_session",
    "create_message",
    "list_messages_by_session",
    "count_episodes",
    "create_episode",
    "get_episode_by_id",
    "get_episode_by_slug",
    "list_episodes",
    "update_episode",
    "count_chunks",
    "count_chunks_for_episode",
    "create_chunks",
    "delete_chunks_by_episode_id",
    "get_chunk_checksum_for_episode",
    "get_chunk_checksum_and_fingerprint_for_episode",
    "get_chunks_by_episode_id",
    "count_embeddings",
    "create_or_update_embedding",
    "create_or_update_embeddings_batch",
    "delete_embeddings_by_chunk_id",
    "get_embedding_by_chunk_id",
    "get_embedding_metadata_by_chunk_id",
    "get_existing_embeddings_metadata_for_chunk_ids",
    "get_index_coverage",
    "semantic_search",
]
