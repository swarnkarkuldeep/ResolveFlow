"""application roles: rf_app (RLS enforced) and rf_system (BYPASSRLS)

Revision ID: 0002
Revises: 0001
"""

from alembic import op
from resolveflow.config import get_settings

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def _lit(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def upgrade() -> None:
    s = get_settings()
    for role, pw, bypass in (
        ("rf_app", s.app_db_password, "NOBYPASSRLS"),
        ("rf_system", s.system_db_password, "BYPASSRLS"),
    ):
        op.execute(
            f"""
            DO $$ BEGIN
              IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
                CREATE ROLE {role} LOGIN PASSWORD {_lit(pw)} NOSUPERUSER NOCREATEDB NOCREATEROLE {bypass};
              END IF;
            END $$;
            """
        )
    op.execute("GRANT SELECT, INSERT, UPDATE ON system_heartbeat TO rf_app, rf_system")


def downgrade() -> None:
    # Roles are cluster-wide and shared by other databases; intentionally not dropped.
    op.execute("REVOKE ALL ON system_heartbeat FROM rf_app, rf_system")
