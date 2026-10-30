"""baseline: scheduler heartbeat

Revision ID: 0001
Revises:
"""
import sqlalchemy as sa

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "system_heartbeat",
        sa.Column("id", sa.SmallInteger, primary_key=True),
        sa.Column("beat_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("id = 1", name="system_heartbeat_singleton"),
    )


def downgrade() -> None:
    op.drop_table("system_heartbeat")
