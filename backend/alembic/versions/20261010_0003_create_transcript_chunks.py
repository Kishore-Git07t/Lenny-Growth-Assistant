"""create transcript_chunks table

Revision ID: 20261010_0003
Revises: 20261009_0002
Create Date: 2026-10-10 00:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20261010_0003"
down_revision: Union[str, None] = "20261009_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "transcript_chunks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("episode_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("word_count", sa.Integer(), nullable=False),
        sa.Column("char_start", sa.Integer(), nullable=True),
        sa.Column("char_end", sa.Integer(), nullable=True),
        sa.Column("start_seconds", sa.Float(), nullable=True),
        sa.Column("end_seconds", sa.Float(), nullable=True),
        sa.Column("source_checksum", sa.String(length=64), nullable=False),
        sa.Column("config_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["episode_id"],
            ["podcast_episodes.id"],
            ondelete="CASCADE",
            name="fk_transcript_chunks_episode_id",
        ),
        sa.UniqueConstraint("episode_id", "chunk_index", name="uq_transcript_chunks_episode_index"),
    )
    op.create_index("idx_transcript_chunks_episode_id", "transcript_chunks", ["episode_id"])
    op.create_index("idx_transcript_chunks_checksum", "transcript_chunks", ["source_checksum"])
    op.create_index("idx_transcript_chunks_config_fingerprint", "transcript_chunks", ["config_fingerprint"])
    op.create_index("idx_transcript_chunks_start_seconds", "transcript_chunks", ["start_seconds"])
    op.create_index("idx_transcript_chunks_created_at", "transcript_chunks", ["created_at"])


def downgrade() -> None:
    op.drop_index("idx_transcript_chunks_created_at", table_name="transcript_chunks")
    op.drop_index("idx_transcript_chunks_start_seconds", table_name="transcript_chunks")
    op.drop_index("idx_transcript_chunks_config_fingerprint", table_name="transcript_chunks")
    op.drop_index("idx_transcript_chunks_checksum", table_name="transcript_chunks")
    op.drop_index("idx_transcript_chunks_episode_id", table_name="transcript_chunks")
    op.drop_table("transcript_chunks")
