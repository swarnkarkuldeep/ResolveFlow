"""full-text search vectors, notification email delivery state, notification preferences

Revision ID: 0008
Revises: 0007
"""

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

UP = [
    "ALTER TABLE tickets ADD COLUMN search_vec tsvector "
    "GENERATED ALWAYS AS (to_tsvector('english', subject)) STORED",
    "ALTER TABLE messages ADD COLUMN search_vec tsvector "
    "GENERATED ALWAYS AS (to_tsvector('english', body)) STORED",
    "CREATE INDEX tickets_search ON tickets USING gin (search_vec)",
    "CREATE INDEX messages_search ON messages USING gin (search_vec)",
    "ALTER TABLE notifications "
    "ADD COLUMN in_app boolean NOT NULL DEFAULT true, "
    "ADD COLUMN email_status text NOT NULL DEFAULT 'none' "
    "CHECK (email_status IN ('none','queued','sending','sent','dead','skipped')), "
    "ADD COLUMN email_attempts integer NOT NULL DEFAULT 0, "
    "ADD COLUMN email_last_error text, "
    "ADD COLUMN email_sent_at timestamptz, "
    "ADD COLUMN email_next_at timestamptz",
    "CREATE INDEX notifications_email_due ON notifications(email_next_at) "
    "WHERE email_status IN ('queued', 'sending')",
    "CREATE INDEX notifications_email_problems ON notifications(workspace_id, created_at DESC) "
    "WHERE email_status = 'dead' OR email_attempts > 0",
    """CREATE TABLE notification_prefs (
         workspace_id uuid NOT NULL REFERENCES workspaces(id),
         user_id uuid NOT NULL REFERENCES users(id),
         kind text NOT NULL CHECK (kind IN ('assigned','customer_reply','sla','escalation','rule')),
         in_app boolean NOT NULL,
         email boolean NOT NULL,
         PRIMARY KEY (workspace_id, user_id, kind))""",
    "ALTER TABLE notification_prefs ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE notification_prefs FORCE ROW LEVEL SECURITY",
    "CREATE POLICY tenant_isolation ON notification_prefs USING (workspace_id = app_ws()) "
    "WITH CHECK (workspace_id = app_ws())",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON notification_prefs TO rf_app",
    "GRANT ALL ON notification_prefs TO rf_system",
]


def upgrade() -> None:
    for stmt in UP:
        op.execute(stmt)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS notification_prefs")
    op.execute(
        "ALTER TABLE notifications DROP COLUMN in_app, DROP COLUMN email_status, DROP COLUMN email_attempts, "
        "DROP COLUMN email_last_error, DROP COLUMN email_sent_at, DROP COLUMN email_next_at"
    )
    op.execute("ALTER TABLE messages DROP COLUMN search_vec")
    op.execute("ALTER TABLE tickets DROP COLUMN search_vec")
