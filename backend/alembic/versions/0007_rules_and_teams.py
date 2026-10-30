"""rules, versions, tests, executions, teams and notification intents

Revision ID: 0007
Revises: 0006
"""

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

NEW_TABLES = [
    "teams",
    "team_members",
    "rules",
    "rule_versions",
    "rule_tests",
    "rule_executions",
    "notifications",
]

UP = [
    """CREATE TABLE teams (
         id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
         workspace_id uuid NOT NULL REFERENCES workspaces(id),
         name citext NOT NULL,
         created_at timestamptz NOT NULL DEFAULT now(),
         UNIQUE (workspace_id, name),
         UNIQUE (id, workspace_id))""",
    """CREATE TABLE team_members (
         team_id uuid NOT NULL,
         workspace_id uuid NOT NULL REFERENCES workspaces(id),
         user_id uuid NOT NULL REFERENCES users(id),
         last_assigned_at timestamptz,
         PRIMARY KEY (team_id, user_id),
         FOREIGN KEY (team_id, workspace_id) REFERENCES teams(id, workspace_id) ON DELETE CASCADE)""",
    """CREATE TABLE rules (
         id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
         workspace_id uuid NOT NULL REFERENCES workspaces(id),
         name text NOT NULL,
         position integer NOT NULL,
         status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','active','archived')),
         active_version integer,
         current_version integer NOT NULL DEFAULT 1,
         created_at timestamptz NOT NULL DEFAULT now(),
         updated_at timestamptz NOT NULL DEFAULT now(),
         UNIQUE (id, workspace_id))""",
    "CREATE INDEX rules_order ON rules(workspace_id, position)",
    """CREATE TABLE rule_versions (
         id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
         workspace_id uuid NOT NULL REFERENCES workspaces(id),
         rule_id uuid NOT NULL,
         version integer NOT NULL,
         definition jsonb NOT NULL,
         content_hash text NOT NULL,
         created_by uuid REFERENCES users(id),
         created_at timestamptz NOT NULL DEFAULT now(),
         UNIQUE (rule_id, version),
         FOREIGN KEY (rule_id, workspace_id) REFERENCES rules(id, workspace_id) ON DELETE CASCADE)""",
    """CREATE TABLE rule_tests (
         id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
         workspace_id uuid NOT NULL REFERENCES workspaces(id),
         rule_id uuid NOT NULL,
         version integer NOT NULL,
         content_hash text NOT NULL,
         expectation text NOT NULL CHECK (expectation IN ('match','no_match')),
         matched boolean NOT NULL,
         passed boolean NOT NULL,
         context jsonb NOT NULL,
         result jsonb NOT NULL,
         created_by uuid REFERENCES users(id),
         created_at timestamptz NOT NULL DEFAULT now(),
         FOREIGN KEY (rule_id, workspace_id) REFERENCES rules(id, workspace_id) ON DELETE CASCADE)""",
    "CREATE INDEX rule_tests_lookup ON rule_tests(rule_id, content_hash)",
    """CREATE TABLE rule_executions (
         id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
         workspace_id uuid NOT NULL REFERENCES workspaces(id),
         rule_id uuid NOT NULL,
         rule_version integer NOT NULL,
         ticket_id uuid NOT NULL,
         event text NOT NULL,
         matched boolean NOT NULL,
         actions jsonb NOT NULL DEFAULT '[]',
         depth integer NOT NULL DEFAULT 1,
         created_at timestamptz NOT NULL DEFAULT now(),
         FOREIGN KEY (rule_id, workspace_id) REFERENCES rules(id, workspace_id) ON DELETE CASCADE,
         FOREIGN KEY (ticket_id, workspace_id) REFERENCES tickets(id, workspace_id))""",
    "CREATE INDEX rule_executions_ticket ON rule_executions(ticket_id, created_at DESC)",
    """CREATE TABLE notifications (
         id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
         workspace_id uuid NOT NULL REFERENCES workspaces(id),
         user_id uuid NOT NULL REFERENCES users(id),
         kind text NOT NULL,
         ticket_id uuid,
         title text NOT NULL,
         body text,
         dedupe_key text,
         read_at timestamptz,
         created_at timestamptz NOT NULL DEFAULT now(),
         FOREIGN KEY (ticket_id, workspace_id) REFERENCES tickets(id, workspace_id))""",
    "CREATE UNIQUE INDEX notifications_dedupe ON notifications(workspace_id, dedupe_key) WHERE dedupe_key IS NOT NULL",
    "CREATE INDEX notifications_inbox ON notifications(workspace_id, user_id, created_at DESC)",
    """CREATE TRIGGER rule_versions_immutable BEFORE UPDATE ON rule_versions
       FOR EACH ROW EXECUTE FUNCTION audit_log_immutable()""",
]

RLS = [f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY" for t in NEW_TABLES]
RLS += [f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY" for t in NEW_TABLES]
RLS += [
    f"CREATE POLICY tenant_isolation ON {t} USING (workspace_id = app_ws()) "
    "WITH CHECK (workspace_id = app_ws())"
    for t in NEW_TABLES
]

GRANTS = [
    "GRANT SELECT, INSERT, UPDATE, DELETE ON teams, team_members, rules TO rf_app",
    "GRANT SELECT, INSERT ON rule_versions, rule_tests, rule_executions TO rf_app",
    "GRANT SELECT, INSERT, UPDATE ON notifications TO rf_app",
    "GRANT ALL ON teams, team_members, rules, rule_versions, rule_tests, rule_executions, "
    "notifications TO rf_system",
]


def upgrade() -> None:
    for stmt in UP + RLS + GRANTS:
        op.execute(stmt)


def downgrade() -> None:
    op.execute(
        "DROP TABLE IF EXISTS notifications, rule_executions, rule_tests, rule_versions, rules, "
        "team_members, teams CASCADE"
    )
