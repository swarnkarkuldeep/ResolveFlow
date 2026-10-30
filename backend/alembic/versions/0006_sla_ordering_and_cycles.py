"""SLA: strict event ordering and escalation cycle keys

Revision ID: 0006
Revises: 0005
"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Timestamps can tie (or skew between processes); a monotonic sequence orders events reliably.
    op.execute("ALTER TABLE sla_events ADD COLUMN seq bigint GENERATED ALWAYS AS IDENTITY")
    op.execute("CREATE INDEX sla_events_order ON sla_events(ticket_id, at, seq)")
    # A flag (warned/breached) belongs to one cycle; reopening or re-prioritising starts a new one.
    op.execute("ALTER TABLE ticket_sla ADD COLUMN fr_cycle text, ADD COLUMN res_cycle text")


def downgrade() -> None:
    op.execute(
        "ALTER TABLE ticket_sla DROP COLUMN IF EXISTS fr_cycle, DROP COLUMN IF EXISTS res_cycle"
    )
    op.execute("DROP INDEX IF EXISTS sla_events_order")
    op.execute("ALTER TABLE sla_events DROP COLUMN IF EXISTS seq")
