"""create podcast_episodes table

Revision ID: 20261009_0002
Revises: 20261009_0001
Create Date: 2026-10-09 21:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20261009_0002"
down_revision: Union[str, None] = "20261009_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "podcast_episodes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("guest_name", sa.String(length=255), nullable=True),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("publish_date", sa.Date(), nullable=True),
        sa.Column("youtube_url", sa.String(length=1024), nullable=True),
        sa.Column("video_id", sa.String(length=64), nullable=True),
        sa.Column("source_path", sa.String(length=1024), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("transcript_text", sa.Text(), nullable=False),
        sa.Column("content_checksum", sa.String(length=64), nullable=False),
        sa.Column(
            "raw_metadata",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug", name="uq_podcast_episodes_slug"),
    )
    op.create_index("idx_podcast_episodes_slug", "podcast_episodes", ["slug"])
    op.create_index("idx_podcast_episodes_guest_name", "podcast_episodes", ["guest_name"])
    op.create_index("idx_podcast_episodes_publish_date", "podcast_episodes", ["publish_date"])
    op.create_index("idx_podcast_episodes_video_id", "podcast_episodes", ["video_id"])
    op.create_index("idx_podcast_episodes_checksum", "podcast_episodes", ["content_checksum"])
    op.create_index("idx_podcast_episodes_created_at", "podcast_episodes", ["created_at"])


def downgrade() -> None:
    op.drop_index("idx_podcast_episodes_created_at", table_name="podcast_episodes")
    op.drop_index("idx_podcast_episodes_checksum", table_name="podcast_episodes")
    op.drop_index("idx_podcast_episodes_video_id", table_name="podcast_episodes")
    op.drop_index("idx_podcast_episodes_publish_date", table_name="podcast_episodes")
    op.drop_index("idx_podcast_episodes_guest_name", table_name="podcast_episodes")
    op.drop_index("idx_podcast_episodes_slug", table_name="podcast_episodes")
    op.drop_table("podcast_episodes")
