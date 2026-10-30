"""configurable data retention: workspace policy and per-ticket redaction marker

Revision ID: 0009
Revises: 0008
"""

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE workspaces ADD COLUMN retention_days integer "
        "CHECK (retention_days IS NULL OR retention_days BETWEEN 30 AND 3650)"
    )
    op.execute("ALTER TABLE tickets ADD COLUMN redacted_at timestamptz")
    op.execute("GRANT DELETE ON notifications TO rf_app")


def downgrade() -> None:
    op.execute("ALTER TABLE tickets DROP COLUMN redacted_at")
    op.execute("ALTER TABLE workspaces DROP COLUMN retention_days")
