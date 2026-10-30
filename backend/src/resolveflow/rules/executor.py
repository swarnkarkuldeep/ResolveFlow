"""Runs active rules inside the transaction of the change that triggered them."""

import json
import logging
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text

from resolveflow.context import RuleContext, ServiceCtx
from resolveflow.rules import notify, service, tester
from resolveflow.rules.engine import PlannedAction, TicketFacts, plan
from resolveflow.rules.teams import pick_round_robin

log = logging.getLogger(__name__)

MAX_DEPTH = 3  # rule-caused changes may trigger further rules this many levels deep


@dataclass
class _Chain:
    depth: int = 0
    fired: set[tuple[str, str]] = field(default_factory=set)  # (rule id, ticket id): once per chain


_chain: ContextVar[_Chain | None] = ContextVar("rule_chain", default=None)


def build_facts(
    ctx: ServiceCtx, ticket_id: uuid.UUID, event: str, level: str | None
) -> TicketFacts:
    t = ctx.session.execute(
        text(
            "select t.subject, t.status, t.priority, t.channel, t.assignee_id, c.email as requester_email "
            "from tickets t join customers c on c.id = t.requester_id "
            "where t.id = :t and t.workspace_id = :w"
        ),
        {"t": ticket_id, "w": ctx.ws},
    ).one()
    tags = frozenset(
        ctx.session.execute(
            text(
                "select g.name from ticket_tags tt join tags g on g.id = tt.tag_id where tt.ticket_id = :t"
            ),
            {"t": ticket_id},
        ).scalars()
    )
    # The newest customer message (a follow-up), or the opening message for every other event.
    newest_first = event == "message.received"
    msg = ctx.session.execute(
        text(
            "select m.body, c.email from messages m left join customers c on c.id = m.author_customer_id "
            "where m.ticket_id = :t and m.direction = 'inbound' "
            "order by (case when :newest then extract(epoch from m.created_at) "
            "else -extract(epoch from m.created_at) end) desc, m.id desc limit 1"
        ),
        {"t": ticket_id, "newest": newest_first},
    ).first()
    email = (msg.email if msg and msg.email else t.requester_email) or ""
    return TicketFacts(
        event=event,
        level=level,
        sender_email=email,
        sender_domain=email.rsplit("@", 1)[-1].lower() if "@" in email else "",
        subject=t.subject,
        body=msg.body if msg else "",
        channel=t.channel,
        priority=t.priority,
        status=t.status,
        tags=tags,
        assignee_id=str(t.assignee_id) if t.assignee_id else None,
    )


def _apply(
    rctx: RuleContext,
    ticket_id: uuid.UUID,
    a: PlannedAction,
    execution_id: uuid.UUID,
) -> None:
    from resolveflow.services import (
        tickets as ticket_svc,
    )  # lazy: tickets calls back into this module

    p = a.params
    if a.type == "assign":
        if p["target"] == "user":
            user_id = uuid.UUID(p["user_id"])
            ok = rctx.session.execute(
                text(
                    "select 1 from memberships where workspace_id = :w and user_id = :u and active and role <> 'viewer'"
                ),
                {"w": rctx.ws, "u": user_id},
            ).first()
            if not ok:
                raise HTTPException(
                    422, {"message": "That person is no longer an active teammate."}
                )
        else:
            picked = pick_round_robin(rctx.session, rctx.ws, uuid.UUID(p["team_id"]))
            if not picked:
                raise HTTPException(422, {"message": "The team has nobody eligible to assign to."})
            user_id = picked
        ticket_svc.update_ticket(rctx, ticket_id, {"assignee_id": user_id})
    elif a.type == "set_priority":
        ticket_svc.update_ticket(rctx, ticket_id, {"priority": p["value"]})
    elif a.type == "set_status":
        ticket_svc.update_ticket(rctx, ticket_id, {"status": p["value"]})
    elif a.type == "add_tag":
        current = ticket_svc._current_tags(rctx, ticket_id)
        ticket_svc.update_ticket(rctx, ticket_id, {"tags": [*current, p["tag"]]})
    elif a.type == "notify":
        notify.create_intents(rctx, ticket_id, p, a.rule_name, execution_id, a.origin == "escalate")


def _reason(exc: Exception) -> str:
    if isinstance(exc, HTTPException):
        d = exc.detail
        return str(d.get("message") if isinstance(d, dict) else d)
    return "Something went wrong while running this action."


def _run(
    ctx: ServiceCtx, ticket_id: uuid.UUID, event: str, level: str | None, chain: _Chain
) -> None:
    rules = service.load_active_rules(ctx)
    candidates = [
        r
        for r in rules
        if r.definition.trigger.event == event
        and (not r.definition.trigger.level or r.definition.trigger.level == level)
        and (r.id, str(ticket_id)) not in chain.fired
    ]
    if not candidates:
        return
    facts = build_facts(ctx, ticket_id, event, level)
    result = plan(candidates, facts)
    matched = [r for r in result.results if r.matched]
    if not matched:
        return
    users, teams = tester._names(ctx, result.actions)
    versions = {r.id: r.version for r in candidates}
    for res in matched:
        chain.fired.add((res.rule_id, str(ticket_id)))
        execution_id = uuid.uuid4()
        rctx = RuleContext(ctx.session, ctx.ws, uuid.UUID(res.rule_id), ctx.request_id)
        outcomes: list[dict[str, Any]] = []
        for a in (x for x in result.actions if x.rule_id == res.rule_id):
            entry = {
                "type": a.type,
                "params": a.params,
                "text": tester.describe(a, users, teams),
                "status": a.status,
                "reason": a.reason,
            }
            if a.status == "apply":
                try:
                    with ctx.session.begin_nested():
                        _apply(rctx, ticket_id, a, execution_id)
                    entry["status"] = "applied"
                except Exception as exc:  # a failing action is recorded, never raised
                    log.warning("rule action failed", exc_info=True)
                    entry["status"], entry["reason"] = "failed", _reason(exc)
            outcomes.append(entry)
        ctx.session.execute(
            text(
                "insert into rule_executions (id, workspace_id, rule_id, rule_version, ticket_id, event, "
                "matched, actions, depth) values (:i, :w, :r, :v, :t, :e, true, cast(:a as jsonb), :d)"
            ),
            {
                "i": execution_id,
                "w": ctx.ws,
                "r": uuid.UUID(res.rule_id),
                "v": versions.get(res.rule_id, 0),
                "t": ticket_id,
                "e": event,
                "a": json.dumps(outcomes),
                "d": chain.depth,
            },
        )


def run_event(ctx: ServiceCtx, ticket_id: uuid.UUID, event: str, level: str | None = None) -> None:
    """Evaluate and apply the active rules for one event on one ticket."""
    chain = _chain.get()
    token = None
    if chain is None:
        chain = _Chain()
        token = _chain.set(chain)
    try:
        if chain.depth >= MAX_DEPTH:
            return
        chain.depth += 1
        try:
            _run(ctx, ticket_id, event, level, chain)
        finally:
            chain.depth -= 1
    finally:
        if token is not None:
            _chain.reset(token)


def on_status_changed(ctx: ServiceCtx, ticket_id: uuid.UUID, old: str, new: str) -> None:
    if old != new:
        run_event(ctx, ticket_id, "status.changed")
