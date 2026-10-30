"""core schema: identity, tenancy, tickets, messages, audit; forced RLS and grants

Revision ID: 0003
Revises: 0002
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

TENANT_TABLES = [
    "memberships",
    "invitations",
    "customers",
    "tickets",
    "messages",
    "tags",
    "ticket_tags",
    "audit_log",
]


UP = [
    "CREATE EXTENSION IF NOT EXISTS citext",
    """CREATE FUNCTION app_ws() RETURNS uuid LANGUAGE sql STABLE AS
       $$ SELECT nullif(current_setting('app.workspace_id', true), '')::uuid $$""",
    """CREATE FUNCTION app_uid() RETURNS uuid LANGUAGE sql STABLE AS
       $$ SELECT nullif(current_setting('app.user_id', true), '')::uuid $$""",
    """CREATE TABLE users (
         id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
         email citext NOT NULL UNIQUE,
         name text NOT NULL,
         password_hash text NOT NULL,
         active boolean NOT NULL DEFAULT true,
         created_at timestamptz NOT NULL DEFAULT now())""",
    """CREATE TABLE workspaces (
         id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
         slug text NOT NULL UNIQUE,
         name text NOT NULL,
         inbound_token text NOT NULL UNIQUE,
         next_ticket_number integer NOT NULL DEFAULT 1,
         created_at timestamptz NOT NULL DEFAULT now())""",
    """CREATE TABLE sessions (
         id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
         token_hash text NOT NULL UNIQUE,
         user_id uuid NOT NULL REFERENCES users(id),
         active_workspace_id uuid REFERENCES workspaces(id),
         csrf_token text NOT NULL,
         expires_at timestamptz NOT NULL,
         revoked_at timestamptz,
         created_at timestamptz NOT NULL DEFAULT now())""",
    "CREATE INDEX sessions_user ON sessions(user_id)",
    """CREATE TABLE memberships (
         id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
         workspace_id uuid NOT NULL REFERENCES workspaces(id),
         user_id uuid NOT NULL REFERENCES users(id),
         role text NOT NULL CHECK (role IN ('owner','admin','agent','viewer')),
         active boolean NOT NULL DEFAULT true,
         created_at timestamptz NOT NULL DEFAULT now(),
         UNIQUE (workspace_id, user_id))""",
    """CREATE TABLE invitations (
         id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
         workspace_id uuid NOT NULL REFERENCES workspaces(id),
         email citext NOT NULL,
         role text NOT NULL CHECK (role IN ('owner','admin','agent','viewer')),
         token_hash text NOT NULL UNIQUE,
         invited_by uuid REFERENCES users(id),
         expires_at timestamptz NOT NULL,
         accepted_at timestamptz,
         created_at timestamptz NOT NULL DEFAULT now())""",
    """CREATE TABLE customers (
         id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
         workspace_id uuid NOT NULL REFERENCES workspaces(id),
         email citext NOT NULL,
         name text,
         created_at timestamptz NOT NULL DEFAULT now(),
         UNIQUE (workspace_id, email),
         UNIQUE (id, workspace_id))""",
    """CREATE TABLE tickets (
         id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
         workspace_id uuid NOT NULL REFERENCES workspaces(id),
         number integer NOT NULL,
         subject text NOT NULL,
         status text NOT NULL DEFAULT 'new'
           CHECK (status IN ('new','open','pending','resolved','closed')),
         priority text NOT NULL DEFAULT 'normal'
           CHECK (priority IN ('low','normal','high','urgent')),
         channel text NOT NULL CHECK (channel IN ('email','form','manual')),
         requester_id uuid NOT NULL,
         assignee_id uuid REFERENCES users(id),
         merged_into_id uuid,
         possible_duplicate_of uuid,
         last_activity_at timestamptz NOT NULL DEFAULT now(),
         created_at timestamptz NOT NULL DEFAULT now(),
         UNIQUE (workspace_id, number),
         UNIQUE (id, workspace_id),
         FOREIGN KEY (requester_id, workspace_id) REFERENCES customers(id, workspace_id),
         FOREIGN KEY (merged_into_id, workspace_id) REFERENCES tickets(id, workspace_id),
         FOREIGN KEY (possible_duplicate_of, workspace_id) REFERENCES tickets(id, workspace_id))""",
    "CREATE INDEX tickets_queue ON tickets(workspace_id, status, last_activity_at DESC)",
    "CREATE INDEX tickets_assignee ON tickets(workspace_id, assignee_id)",
    """CREATE TABLE messages (
         id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
         workspace_id uuid NOT NULL REFERENCES workspaces(id),
         ticket_id uuid NOT NULL,
         kind text NOT NULL CHECK (kind IN ('public','note')),
         direction text NOT NULL CHECK (direction IN ('inbound','outbound','internal')),
         author_user_id uuid REFERENCES users(id),
         author_customer_id uuid,
         body text NOT NULL,
         message_id text,
         in_reply_to text,
         delivery_status text NOT NULL DEFAULT 'none'
           CHECK (delivery_status IN ('none','queued','sent','failed')),
         delivery_attempts integer NOT NULL DEFAULT 0,
         created_at timestamptz NOT NULL DEFAULT now(),
         FOREIGN KEY (ticket_id, workspace_id) REFERENCES tickets(id, workspace_id),
         FOREIGN KEY (author_customer_id, workspace_id) REFERENCES customers(id, workspace_id))""",
    "CREATE INDEX messages_ticket ON messages(ticket_id, created_at)",
    "CREATE UNIQUE INDEX messages_ws_message_id ON messages(workspace_id, message_id) WHERE message_id IS NOT NULL",
    "CREATE INDEX messages_outbound_queue ON messages(delivery_status, created_at) WHERE delivery_status = 'queued'",
    """CREATE TABLE tags (
         id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
         workspace_id uuid NOT NULL REFERENCES workspaces(id),
         name text NOT NULL,
         UNIQUE (workspace_id, name),
         UNIQUE (id, workspace_id))""",
    """CREATE TABLE ticket_tags (
         workspace_id uuid NOT NULL REFERENCES workspaces(id),
         ticket_id uuid NOT NULL,
         tag_id uuid NOT NULL,
         PRIMARY KEY (ticket_id, tag_id),
         FOREIGN KEY (ticket_id, workspace_id) REFERENCES tickets(id, workspace_id),
         FOREIGN KEY (tag_id, workspace_id) REFERENCES tags(id, workspace_id))""",
    """CREATE TABLE audit_log (
         id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
         workspace_id uuid NOT NULL REFERENCES workspaces(id),
         actor_type text NOT NULL CHECK (actor_type IN ('user','system','rule')),
         actor_id uuid,
         action text NOT NULL,
         entity_type text NOT NULL,
         entity_id uuid,
         before jsonb,
         after jsonb,
         request_id text,
         created_at timestamptz NOT NULL DEFAULT now())""",
    "CREATE INDEX audit_ws_time ON audit_log(workspace_id, created_at DESC)",
    "CREATE INDEX audit_entity ON audit_log(workspace_id, entity_type, entity_id)",
    """CREATE FUNCTION audit_log_immutable() RETURNS trigger LANGUAGE plpgsql AS
       $$ BEGIN RAISE EXCEPTION 'audit_log is append-only'; END $$""",
    """CREATE TRIGGER audit_log_no_change BEFORE UPDATE OR DELETE ON audit_log
       FOR EACH ROW EXECUTE FUNCTION audit_log_immutable()""",
    """CREATE TRIGGER audit_log_no_truncate BEFORE TRUNCATE ON audit_log
       FOR EACH STATEMENT EXECUTE FUNCTION audit_log_immutable()""",
]

RLS = [f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY" for t in TENANT_TABLES + ["workspaces"]]
RLS += [f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY" for t in TENANT_TABLES + ["workspaces"]]
RLS += [
    f"CREATE POLICY tenant_isolation ON {t} USING (workspace_id = app_ws()) "
    "WITH CHECK (workspace_id = app_ws())"
    for t in TENANT_TABLES
    if t != "memberships"
]
RLS += [
    # A user can see their own memberships (to list workspaces) plus the active workspace's.
    "CREATE POLICY membership_read ON memberships FOR SELECT "
    "USING (workspace_id = app_ws() OR user_id = app_uid())",
    "CREATE POLICY membership_insert ON memberships FOR INSERT WITH CHECK (workspace_id = app_ws())",
    "CREATE POLICY membership_update ON memberships FOR UPDATE "
    "USING (workspace_id = app_ws()) WITH CHECK (workspace_id = app_ws())",
    """CREATE POLICY workspace_read ON workspaces FOR SELECT USING (
         id = app_ws() OR EXISTS (
           SELECT 1 FROM memberships m
           WHERE m.workspace_id = workspaces.id AND m.user_id = app_uid() AND m.active))""",
    "CREATE POLICY workspace_update ON workspaces FOR UPDATE "
    "USING (id = app_ws()) WITH CHECK (id = app_ws())",
]

GRANTS = [
    "GRANT SELECT ON users TO rf_app",
    "GRANT SELECT, INSERT, UPDATE ON sessions TO rf_app",
    "GRANT SELECT, UPDATE ON workspaces TO rf_app",
    "GRANT SELECT, INSERT, UPDATE ON memberships, tickets, messages, customers TO rf_app",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON invitations, tags, ticket_tags TO rf_app",
    "GRANT SELECT, INSERT ON audit_log TO rf_app",
    # rf_system is BYPASSRLS and runs bootstrap/sweeper flows (signup, invite accept, ingest).
    "GRANT ALL ON ALL TABLES IN SCHEMA public TO rf_system",
]

DOWN = [
    "DROP TABLE IF EXISTS audit_log, ticket_tags, tags, messages, tickets, customers, "
    "invitations, memberships, sessions, workspaces, users CASCADE",
    "DROP FUNCTION IF EXISTS audit_log_immutable()",
    "DROP FUNCTION IF EXISTS app_uid()",
    "DROP FUNCTION IF EXISTS app_ws()",
]


def upgrade() -> None:
    for stmt in UP + RLS + GRANTS:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in DOWN:
        op.execute(stmt)
