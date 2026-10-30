import uuid
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from resolveflow.db import engine_for
from resolveflow.tenancy import tenant_session


@dataclass
class Tenant:
    workspace_id: uuid.UUID
    user_id: uuid.UUID
    ticket_id: uuid.UUID


def _make_tenant(conn, tag: str) -> Tenant:  # type: ignore[no-untyped-def]
    uid = conn.execute(
        text("insert into users (email, name, password_hash) values (:e, :n, 'x') returning id"),
        {"e": f"{tag}-{uuid.uuid4().hex[:6]}@t.test", "n": tag},
    ).scalar_one()
    wid = conn.execute(
        text("insert into workspaces (slug, name, inbound_token) values (:s, :n, :t) returning id"),
        {"s": f"{tag}-{uuid.uuid4().hex[:6]}", "n": tag, "t": uuid.uuid4().hex},
    ).scalar_one()
    conn.execute(
        text("insert into memberships (workspace_id, user_id, role) values (:w, :u, 'owner')"),
        {"w": wid, "u": uid},
    )
    cid = conn.execute(
        text(
            "insert into customers (workspace_id, email, name) "
            "values (:w, 'c@x.test', 'C') returning id"
        ),
        {"w": wid},
    ).scalar_one()
    tid = conn.execute(
        text(
            "insert into tickets (workspace_id, number, subject, requester_id, channel) "
            "values (:w, 1, 'Hello', :c, 'manual') returning id"
        ),
        {"w": wid, "c": cid},
    ).scalar_one()
    conn.execute(
        text(
            "insert into messages (workspace_id, ticket_id, kind, direction, body) "
            "values (:w, :t, 'public', 'inbound', 'hi')"
        ),
        {"w": wid, "t": tid},
    )
    conn.execute(
        text(
            "insert into audit_log (workspace_id, actor_type, action, entity_type) "
            "values (:w, 'system', 'ticket.created', 'ticket')"
        ),
        {"w": wid},
    )
    return Tenant(wid, uid, tid)


@pytest.fixture
def tenants(migrated_env: None, postgres_url: str) -> Iterator[tuple[Tenant, Tenant]]:
    with engine_for(postgres_url).begin() as conn:
        a, b = _make_tenant(conn, "alpha"), _make_tenant(conn, "bravo")
    yield a, b


def test_every_workspace_table_has_forced_rls(migrated_env: None, postgres_url: str) -> None:
    with engine_for(postgres_url).connect() as conn:
        rows = conn.execute(
            text(
                "select c.relname, c.relrowsecurity, c.relforcerowsecurity "
                "from pg_class c join information_schema.columns col "
                "  on col.table_name = c.relname and col.table_schema = 'public' "
                "where col.column_name = 'workspace_id' and c.relkind = 'r'"
            )
        ).all()
    names = {r[0] for r in rows}
    assert {
        "tickets",
        "messages",
        "customers",
        "audit_log",
        "memberships",
        "invitations",
        "business_calendars",
        "sla_policies",
        "ticket_sla",
        "sla_events",
    } <= names
    assert all(r[1] and r[2] for r in rows), [r[0] for r in rows if not (r[1] and r[2])]


def test_cross_tenant_read_returns_nothing(tenants: tuple[Tenant, Tenant]) -> None:
    a, b = tenants
    with tenant_session(a.workspace_id, a.user_id) as s:
        for table in ("tickets", "messages", "customers", "audit_log", "memberships"):
            ws = s.execute(text(f"select distinct workspace_id from {table}")).scalars().all()  # noqa: S608
            assert ws == [a.workspace_id], table
        assert (
            s.execute(
                text("select count(*) from tickets where id = :i"), {"i": b.ticket_id}
            ).scalar_one()
            == 0
        )


def test_no_tenant_context_sees_nothing(tenants: tuple[Tenant, Tenant]) -> None:
    with tenant_session(None, None) as s:
        assert s.execute(text("select count(*) from tickets")).scalar_one() == 0
        assert s.execute(text("select count(*) from workspaces")).scalar_one() == 0


def test_cross_tenant_write_is_rejected(tenants: tuple[Tenant, Tenant]) -> None:
    a, b = tenants
    with pytest.raises(DBAPIError), tenant_session(a.workspace_id, a.user_id) as s:
        s.execute(
            text("insert into customers (workspace_id, email, name) values (:w, 'z@x.test', 'Z')"),
            {"w": b.workspace_id},
        )
    with tenant_session(a.workspace_id, a.user_id) as s:
        upd = s.execute(
            text("update tickets set subject = 'pwned' where id = :i"), {"i": b.ticket_id}
        )
        assert upd.rowcount == 0
        dele = s.execute(
            text("delete from ticket_tags where workspace_id = :w"), {"w": b.workspace_id}
        )
        assert dele.rowcount == 0


def test_cross_tenant_reference_is_rejected_by_composite_fk(tenants: tuple[Tenant, Tenant]) -> None:
    a, b = tenants
    with engine_for_owner() as conn:
        foreign_customer = conn.execute(
            text("select id from customers where workspace_id = :w"), {"w": b.workspace_id}
        ).scalar_one()
    with pytest.raises(DBAPIError), tenant_session(a.workspace_id, a.user_id) as s:
        s.execute(
            text(
                "insert into tickets (workspace_id, number, subject, requester_id, channel) "
                "values (:w, 2, 'x', :c, 'manual')"
            ),
            {"w": a.workspace_id, "c": foreign_customer},
        )


def engine_for_owner():  # type: ignore[no-untyped-def]
    from resolveflow.config import get_settings

    return engine_for(get_settings().database_url).connect()


def test_audit_log_is_append_only(tenants: tuple[Tenant, Tenant], postgres_url: str) -> None:
    a, _ = tenants
    with pytest.raises(DBAPIError), tenant_session(a.workspace_id, a.user_id) as s:
        s.execute(text("update audit_log set action = 'x'"))
    with pytest.raises(DBAPIError), tenant_session(a.workspace_id, a.user_id) as s:
        s.execute(text("delete from audit_log"))
    with pytest.raises(DBAPIError), engine_for(postgres_url).begin() as conn:
        conn.execute(text("delete from audit_log"))
