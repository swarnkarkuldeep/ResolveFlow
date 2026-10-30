"""rf_app can no longer read password hashes (login lookup runs as rf_system)

Revision ID: 0004
Revises: 0003
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("REVOKE SELECT ON users FROM rf_app")
    op.execute("GRANT SELECT (id, email, name, active, created_at) ON users TO rf_app")


def downgrade() -> None:
    op.execute("REVOKE SELECT ON users FROM rf_app")
    op.execute("GRANT SELECT ON users TO rf_app")
