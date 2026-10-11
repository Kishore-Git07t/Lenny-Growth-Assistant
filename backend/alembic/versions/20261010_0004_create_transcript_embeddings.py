"""create transcript_embeddings table

Revision ID: 20261010_0004
Revises: 20261010_0003
Create Date: 2026-10-10 00:00:00.000000+00:00

"""
from typing import Any, Sequence, Union

from alembic import op
import sqlalchemy as sa

try:
    from pgvector.sqlalchemy import Vector
except ImportError:
    from sqlalchemy.types import UserDefinedType

    class Vector(UserDefinedType):  # type: ignore
        """Fallback Vector type when pgvector package is not yet installed."""

        def __init__(self, dim: int = 768):
            self.dim = dim

        def get_col_spec(self, **kw: Any) -> str:
            return f"vector({self.dim})" if self.dim else "vector"


# revision identifiers, used by Alembic.
revision: str = "20261010_0004"
down_revision: Union[str, None] = "20261010_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Enable pgvector extension in PostgreSQL if not already present
    bind = op.get_bind()
    if bind and bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # 2. Create transcript_embeddings table
    op.create_table(
        "transcript_embeddings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("chunk_id", sa.Uuid(), nullable=False),
        sa.Column("embedding", Vector(768), nullable=False),
        sa.Column("model_name", sa.String(length=64), nullable=False),
        sa.Column("input_checksum", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["chunk_id"],
            ["transcript_chunks.id"],
            ondelete="CASCADE",
            name="fk_transcript_embeddings_chunk_id",
        ),
        sa.UniqueConstraint("chunk_id", name="uq_transcript_embeddings_chunk_id"),
    )
    op.create_index("idx_transcript_embeddings_chunk_id", "transcript_embeddings", ["chunk_id"])
    op.create_index("idx_transcript_embeddings_model_name", "transcript_embeddings", ["model_name"])
    op.create_index("idx_transcript_embeddings_input_checksum", "transcript_embeddings", ["input_checksum"])
    op.create_index("idx_transcript_embeddings_created_at", "transcript_embeddings", ["created_at"])


def downgrade() -> None:
    op.drop_index("idx_transcript_embeddings_created_at", table_name="transcript_embeddings")
    op.drop_index("idx_transcript_embeddings_input_checksum", table_name="transcript_embeddings")
    op.drop_index("idx_transcript_embeddings_model_name", table_name="transcript_embeddings")
    op.drop_index("idx_transcript_embeddings_chunk_id", table_name="transcript_embeddings")
    op.drop_table("transcript_embeddings")
