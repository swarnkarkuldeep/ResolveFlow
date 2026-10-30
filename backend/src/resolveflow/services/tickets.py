import base64
import json
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import text

from resolveflow import audit
from resolveflow.context import ServiceCtx
from resolveflow.errors import err

STATUSES = ("new", "open", "pending", "resolved", "closed")
PRIORITIES = ("low", "normal", "high", "urgent")
SORT_COLUMNS = {"activity": "last_activity_at", "created": "created_at"}

_SELECT = """
select t.id, t.number, t.subject, t.status, t.priority, t.channel, t.last_activity_at,
  t.created_at, t.possible_duplicate_of, t.merged_into_id,
  c.id as req_id, c.email as req_email, c.name as req_name,
  a.id as asg_id, a.name as asg_name,
  coalesce((select array_agg(g.name order by g.name) from ticket_tags tt
            join tags g on g.id = tt.tag_id where tt.ticket_id = t.id), '{}') as tags,
  (select left(m.body, 160) from messages m where m.ticket_id = t.id
   order by m.created_at, m.id limit 1) as snippet
from tickets t
join customers c on c.id = t.requester_id
left join users a on a.id = t.assignee_id
"""


def _item(r: Any) -> dict[str, Any]:
    return {
        "id": str(r.id),
        "number": r.number,
        "subject": r.subject,
        "status": r.status,
        "priority": r.priority,
        "channel": r.channel,
        "requester": {"id": str(r.req_id), "email": r.req_email, "name": r.req_name},
        "assignee": {"id": str(r.asg_id), "name": r.asg_name} if r.asg_id else None,
        "tags": list(r.tags),
        "snippet": r.snippet,
        "last_activity_at": r.last_activity_at.isoformat(),
        "created_at": r.created_at.isoformat(),
        "possible_duplicate_of": str(r.possible_duplicate_of) if r.possible_duplicate_of else None,
        "merged_into_id": str(r.merged_into_id) if r.merged_into_id else None,
    }


def _encode_cursor(ts: datetime, tid: uuid.UUID) -> str:
    return base64.urlsafe_b64encode(
        json.dumps({"t": ts.isoformat(), "i": str(tid)}).encode()
    ).decode()


def _decode_cursor(cursor: str) -> tuple[str, str]:
    try:
        data = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        return str(data["t"]), str(uuid.UUID(data["i"]))
    except Exception:
        raise err(422, "bad_cursor", "That page marker is not valid.") from None


def _upsert_customer(ctx: ServiceCtx, email: str, name: str | None) -> uuid.UUID:
    customer_id: uuid.UUID = ctx.session.execute(
        text(
            "insert into customers (workspace_id, email, name) values (:w, :e, :n) "
            "on conflict (workspace_id, email) do update "
            "set name = coalesce(customers.name, excluded.name) returning id"
        ),
        {"w": ctx.ws, "e": email, "n": name},
    ).scalar_one()
    return customer_id


def create_ticket(
    ctx: ServiceCtx,
    *,
    subject: str,
    body: str,
    requester_email: str,
    requester_name: str | None = None,
    priority: str = "normal",
    channel: str = "manual",
    message_id: str | None = None,
) -> dict[str, Any]:
    customer_id = _upsert_customer(ctx, requester_email, requester_name)
    number = ctx.session.execute(
        text(
            "update workspaces set next_ticket_number = next_ticket_number + 1 "
            "where id = :w returning next_ticket_number - 1"
        ),
        {"w": ctx.ws},
    ).scalar_one()
    ticket_id = ctx.session.execute(
        text(
            "insert into tickets (workspace_id, number, subject, priority, channel, requester_id) "
            "values (:w, :n, :s, :p, :c, :r) returning id"
        ),
        {"w": ctx.ws, "n": number, "s": subject, "p": priority, "c": channel, "r": customer_id},
    ).scalar_one()
    ctx.session.execute(
        text(
            "insert into messages (workspace_id, ticket_id, kind, direction, author_customer_id, "
            "body, message_id) values (:w, :t, 'public', 'inbound', :c, :b, :m)"
        ),
        {"w": ctx.ws, "t": ticket_id, "c": customer_id, "b": body, "m": message_id},
    )
    audit.record(
        ctx.session,
        workspace_id=ctx.ws,
        actor_type=ctx.actor_type,
        actor_id=ctx.actor_id,
        action="ticket.created",
        entity_type="ticket",
        entity_id=ticket_id,
        after={"number": number, "subject": subject, "channel": channel, "priority": priority},
        request_id=ctx.request_id,
    )
    return get_ticket(ctx, ticket_id, with_messages=False)


def get_ticket(ctx: ServiceCtx, ticket_id: uuid.UUID, with_messages: bool = True) -> dict[str, Any]:
    row = ctx.session.execute(
        text(_SELECT + " where t.workspace_id = :w and t.id = :i"), {"w": ctx.ws, "i": ticket_id}
    ).first()
    if not row:
        raise err(404, "not_found", "Ticket not found.")
    out = _item(row)
    if with_messages:
        msgs = ctx.session.execute(
            text(
                "select m.id, m.kind, m.direction, m.body, m.created_at, m.delivery_status, "
                "u.name as user_name, c.name as cust_name, c.email as cust_email "
                "from messages m left join users u on u.id = m.author_user_id "
                "left join customers c on c.id = m.author_customer_id "
                "where m.workspace_id = :w and m.ticket_id = :i order by m.created_at, m.id"
            ),
            {"w": ctx.ws, "i": ticket_id},
        ).all()
        out["messages"] = [
            {
                "id": str(m.id),
                "kind": m.kind,
                "direction": m.direction,
                "body": m.body,
                "created_at": m.created_at.isoformat(),
                "delivery_status": m.delivery_status,
                "author": (
                    {"type": "user", "name": m.user_name}
                    if m.user_name
                    else {"type": "customer", "name": m.cust_name or m.cust_email}
                ),
            }
            for m in msgs
        ]
    return out


def list_tickets(
    ctx: ServiceCtx,
    *,
    me: uuid.UUID,
    statuses: list[str] | None = None,
    priorities: list[str] | None = None,
    assignee: str | None = None,
    tag: str | None = None,
    sort: str = "activity",
    order: str = "desc",
    limit: int = 50,
    cursor: str | None = None,
) -> dict[str, Any]:
    col = SORT_COLUMNS[sort]
    direction = "desc" if order == "desc" else "asc"
    op = "<" if direction == "desc" else ">"
    where = ["t.workspace_id = :w"]
    params: dict[str, Any] = {"w": ctx.ws, "lim": limit + 1}
    if statuses:
        where.append("t.status = any(:statuses)")
        params["statuses"] = statuses
    if priorities:
        where.append("t.priority = any(:priorities)")
        params["priorities"] = priorities
    if assignee == "me":
        where.append("t.assignee_id = :me")
        params["me"] = me
    elif assignee == "none":
        where.append("t.assignee_id is null")
    elif assignee:
        try:
            params["asg"] = uuid.UUID(assignee)
        except ValueError:
            raise err(422, "bad_assignee", "Assignee must be me, none or a user id.") from None
        where.append("t.assignee_id = :asg")
    if tag:
        where.append(
            "exists (select 1 from ticket_tags tt join tags g on g.id = tt.tag_id "
            "where tt.ticket_id = t.id and g.name = :tag)"
        )
        params["tag"] = tag
    if cursor:
        ct, ci = _decode_cursor(cursor)
        where.append(f"(t.{col}, t.id) {op} (cast(:ct as timestamptz), cast(:ci as uuid))")
        params.update(ct=ct, ci=ci)
    sql = (  # col/direction/op come from fixed whitelists above
        _SELECT
        + " where "
        + " and ".join(where)
        + f" order by t.{col} {direction}, t.id {direction} limit :lim"
    )
    rows = ctx.session.execute(text(sql), params).all()
    page = rows[:limit]
    next_cursor = None
    if len(rows) > limit:
        last = page[-1]
        ts = last.last_activity_at if col == "last_activity_at" else last.created_at
        next_cursor = _encode_cursor(ts, last.id)
    return {"items": [_item(r) for r in page], "next_cursor": next_cursor}


def _set_tags(ctx: ServiceCtx, ticket_id: uuid.UUID, names: list[str]) -> None:
    ctx.session.execute(
        text("delete from ticket_tags where ticket_id = :t and workspace_id = :w"),
        {"t": ticket_id, "w": ctx.ws},
    )
    for name in names:
        tag_id = ctx.session.execute(
            text(
                "insert into tags (workspace_id, name) values (:w, :n) "
                "on conflict (workspace_id, name) do update set name = excluded.name returning id"
            ),
            {"w": ctx.ws, "n": name},
        ).scalar_one()
        ctx.session.execute(
            text("insert into ticket_tags (workspace_id, ticket_id, tag_id) values (:w, :t, :g)"),
            {"w": ctx.ws, "t": ticket_id, "g": tag_id},
        )


def _current_tags(ctx: ServiceCtx, ticket_id: uuid.UUID) -> list[str]:
    return list(
        ctx.session.execute(
            text(
                "select g.name from ticket_tags tt join tags g on g.id = tt.tag_id "
                "where tt.ticket_id = :t order by g.name"
            ),
            {"t": ticket_id},
        ).scalars()
    )


def update_ticket(ctx: ServiceCtx, ticket_id: uuid.UUID, fields: dict[str, Any]) -> dict[str, Any]:
    row = ctx.session.execute(
        text(
            "select status, priority, assignee_id from tickets "
            "where workspace_id = :w and id = :i for update"
        ),
        {"w": ctx.ws, "i": ticket_id},
    ).first()
    if not row:
        raise err(404, "not_found", "Ticket not found.")
    before: dict[str, Any] = {}
    after: dict[str, Any] = {}
    sets: dict[str, Any] = {}

    for key in ("status", "priority"):
        if key in fields and fields[key] != getattr(row, key):
            before[key], after[key] = getattr(row, key), fields[key]
            sets[key] = fields[key]
    if "assignee_id" in fields and fields["assignee_id"] != row.assignee_id:
        new_assignee = fields["assignee_id"]
        if new_assignee is not None:
            ok = ctx.session.execute(
                text(
                    "select 1 from memberships where workspace_id = :w and user_id = :u and active"
                ),
                {"w": ctx.ws, "u": new_assignee},
            ).first()
            if not ok:
                raise err(
                    422, "bad_assignee", "That person is not an active member of this workspace."
                )
        before["assignee_id"] = str(row.assignee_id) if row.assignee_id else None
        after["assignee_id"] = str(new_assignee) if new_assignee else None
        sets["assignee_id"] = new_assignee
        if new_assignee is not None and "status" not in sets and row.status == "new":
            before["status"], after["status"] = "new", "open"
            sets["status"] = "open"
    if "tags" in fields:
        current = _current_tags(ctx, ticket_id)
        wanted = sorted(set(fields["tags"]))
        if wanted != current:
            before["tags"], after["tags"] = current, wanted
            _set_tags(ctx, ticket_id, wanted)

    if before or after:
        if sets:
            assignments = ", ".join(f"{k} = :{k}" for k in sets)
            ctx.session.execute(
                text(
                    f"update tickets set {assignments}, last_activity_at = now() "  # noqa: S608
                    "where id = :id and workspace_id = :w"
                ),
                {**sets, "id": ticket_id, "w": ctx.ws},
            )
        else:
            ctx.session.execute(
                text(
                    "update tickets set last_activity_at = now() where id = :id and workspace_id = :w"
                ),
                {"id": ticket_id, "w": ctx.ws},
            )
        audit.record(
            ctx.session,
            workspace_id=ctx.ws,
            actor_type=ctx.actor_type,
            actor_id=ctx.actor_id,
            action="ticket.updated",
            entity_type="ticket",
            entity_id=ticket_id,
            before=before,
            after=after,
            request_id=ctx.request_id,
        )
    return get_ticket(ctx, ticket_id, with_messages=False)


def ticket_activity(ctx: ServiceCtx, ticket_id: uuid.UUID) -> list[dict[str, Any]]:
    exists = ctx.session.execute(
        text("select 1 from tickets where id = :i and workspace_id = :w"),
        {"i": ticket_id, "w": ctx.ws},
    ).first()
    if not exists:
        raise err(404, "not_found", "Ticket not found.")
    rows = ctx.session.execute(
        text(
            "select a.action, a.created_at, a.before, a.after, a.actor_type, u.name as actor_name "
            "from audit_log a left join users u on u.id = a.actor_id "
            "where a.workspace_id = :w and a.entity_type = 'ticket' and a.entity_id = :i "
            "order by a.created_at, a.id"
        ),
        {"w": ctx.ws, "i": ticket_id},
    ).all()
    return [
        {
            "action": r.action,
            "created_at": r.created_at.isoformat(),
            "before": r.before,
            "after": r.after,
            "actor_type": r.actor_type,
            "actor_name": r.actor_name or ("System" if r.actor_type == "system" else None),
        }
        for r in rows
    ]
