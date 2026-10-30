"""SLA: policies, business calendars, per-ticket clock cache and append-only event stream

Revision ID: 0005
Revises: 0004
"""

from alembic import op
from resolveflow.sla.defaults import backfill_defaults

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

NEW_TABLES = ["business_calendars", "sla_policies", "ticket_sla", "sla_events"]

UP = [
    """CREATE TABLE business_calendars (
         id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
         workspace_id uuid NOT NULL UNIQUE REFERENCES workspaces(id),
         timezone text NOT NULL DEFAULT 'UTC',
         weekly jsonb NOT NULL,
         holidays date[] NOT NULL DEFAULT '{}',
         updated_at timestamptz NOT NULL DEFAULT now())""",
    """CREATE TABLE sla_policies (
         id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
         workspace_id uuid NOT NULL UNIQUE REFERENCES workspaces(id),
         name text NOT NULL DEFAULT 'Default',
         enabled boolean NOT NULL DEFAULT true,
         business_hours_only boolean NOT NULL DEFAULT true,
         targets jsonb NOT NULL,
         version integer NOT NULL DEFAULT 1,
         updated_at timestamptz NOT NULL DEFAULT now())""",
    """CREATE TABLE ticket_sla (
         ticket_id uuid PRIMARY KEY,
         workspace_id uuid NOT NULL REFERENCES workspaces(id),
         policy_version integer NOT NULL,
         start_at timestamptz NOT NULL,
         fr_target_min integer,
         res_target_min integer,
         fr_due_at timestamptz,
         res_due_at timestamptz,
         fr_met_at timestamptz,
         res_met_at timestamptz,
         fr_warned_at timestamptz,
         fr_breached_at timestamptz,
         res_warned_at timestamptz,
         res_breached_at timestamptz,
         paused_at timestamptz,
         next_check_at timestamptz,
         updated_at timestamptz NOT NULL DEFAULT now(),
         FOREIGN KEY (ticket_id, workspace_id) REFERENCES tickets(id, workspace_id))""",
    "CREATE INDEX ticket_sla_due ON ticket_sla(next_check_at) WHERE next_check_at IS NOT NULL",
    "CREATE INDEX ticket_sla_workspace ON ticket_sla(workspace_id)",
    """CREATE TABLE sla_events (
         id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
         workspace_id uuid NOT NULL REFERENCES workspaces(id),
         ticket_id uuid NOT NULL,
         kind text NOT NULL CHECK (kind IN ('started','paused','resumed','first_response',
           'resolved','reopened','priority_changed','policy_changed','threshold')),
         detail jsonb,
         dedupe_key text,
         at timestamptz NOT NULL DEFAULT now(),
         FOREIGN KEY (ticket_id, workspace_id) REFERENCES tickets(id, workspace_id))""",
    "CREATE INDEX sla_events_ticket ON sla_events(ticket_id, at)",
    "CREATE UNIQUE INDEX sla_events_dedupe ON sla_events(workspace_id, dedupe_key) WHERE dedupe_key IS NOT NULL",
    """CREATE TRIGGER sla_events_no_change BEFORE UPDATE OR DELETE ON sla_events
       FOR EACH ROW EXECUTE FUNCTION audit_log_immutable()""",
    """CREATE TRIGGER sla_events_no_truncate BEFORE TRUNCATE ON sla_events
       FOR EACH STATEMENT EXECUTE FUNCTION audit_log_immutable()""",
]

RLS = [f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY" for t in NEW_TABLES]
RLS += [f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY" for t in NEW_TABLES]
RLS += [
    f"CREATE POLICY tenant_isolation ON {t} USING (workspace_id = app_ws()) "
    "WITH CHECK (workspace_id = app_ws())"
    for t in NEW_TABLES
]

GRANTS = [
    "GRANT SELECT, INSERT, UPDATE ON business_calendars, sla_policies, ticket_sla TO rf_app",
    "GRANT SELECT, INSERT ON sla_events TO rf_app",
    "GRANT ALL ON business_calendars, sla_policies, ticket_sla, sla_events TO rf_system",
]


def upgrade() -> None:
    for stmt in UP + RLS + GRANTS:
        op.execute(stmt)
    backfill_defaults(op.get_bind())


def downgrade() -> None:
    op.execute(
        "DROP TABLE IF EXISTS sla_events, ticket_sla, sla_policies, business_calendars CASCADE"
    )
