"""add body_photo paths to users

Revision ID: b3c4d5e6f7a8
Revises: d5e6f7a8b9c0
Create Date: 2026-09-20

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b3c4d5e6f7a8"
down_revision: str | None = "d5e6f7a8b9c0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("body_photo_path", sa.String(500), nullable=True))
    op.add_column("users", sa.Column("body_photo_medium_path", sa.String(500), nullable=True))
    op.add_column("users", sa.Column("body_photo_thumbnail_path", sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "body_photo_thumbnail_path")
    op.drop_column("users", "body_photo_medium_path")
    op.drop_column("users", "body_photo_path")
