"""The one place notifications are created: applies preferences, dedupes, queues email."""

import uuid

from sqlalchemy import text

from resolveflow.context import ServiceCtx
from resolveflow.errors import err

KINDS = ("assigned", "customer_reply", "sla", "escalation", "rule")
EMAIL_BY_DEFAULT = frozenset({"sla", "escalation"})


def default_prefs() -> dict[str, tuple[bool, bool]]:
    return {k: (True, k in EMAIL_BY_DEFAULT) for k in KINDS}


def prefs_for(ctx: ServiceCtx, user_id: uuid.UUID) -> list[dict[str, object]]:
    prefs = default_prefs()
    rows = ctx.session.execute(
        text(
            "select kind, in_app, email from notification_prefs "
            "where workspace_id = :w and user_id = :u"
        ),
        {"w": ctx.ws, "u": user_id},
    )
    for r in rows:
        prefs[r.kind] = (r.in_app, r.email)
    return [{"kind": k, "in_app": v[0], "email": v[1]} for k, v in prefs.items()]


def set_prefs(ctx: ServiceCtx, user_id: uuid.UUID, items: list[dict[str, object]]) -> None:
    for it in items:
        kind = str(it["kind"])
        if kind not in KINDS:
            raise err(422, "bad_kind", f"Unknown notification type: {kind}.")
        ctx.session.execute(
            text(
                "insert into notification_prefs (workspace_id, user_id, kind, in_app, email) "
                "values (:w, :u, :k, :a, :e) on conflict (workspace_id, user_id, kind) "
                "do update set in_app = excluded.in_app, email = excluded.email"
            ),
            {"w": ctx.ws, "u": user_id, "k": kind, "a": bool(it["in_app"]), "e": bool(it["email"])},
        )


def notify(
    ctx: ServiceCtx,
    user_ids: list[uuid.UUID],
    kind: str,
    ticket_id: uuid.UUID | None,
    title: str,
    body: str | None,
    dedupe_base: str,
) -> int:
    """Create one notification per user (skipping the ones who turned this kind off). Idempotent."""
    if kind not in KINDS:
        raise ValueError(f"unknown notification kind {kind}")
    if not user_ids:
        return 0
    overrides = {
        r.user_id: (r.in_app, r.email)
        for r in ctx.session.execute(
            text(
                "select user_id, in_app, email from notification_prefs "
                "where workspace_id = :w and kind = :k and user_id = any(:u)"
            ),
            {"w": ctx.ws, "k": kind, "u": user_ids},
        )
    }
    created = 0
    for uid in dict.fromkeys(user_ids):
        in_app, email = overrides.get(uid, (True, kind in EMAIL_BY_DEFAULT))
        if not in_app and not email:
            continue
        row = ctx.session.execute(
            text(
                "insert into notifications (workspace_id, user_id, kind, ticket_id, title, body, "
                "dedupe_key, in_app, email_status, email_next_at) "
                "values (:w, :u, :k, :t, :ti, :b, :d, :ia, "
                "case when :em then 'queued' else 'none' end, case when :em then now() end) "
                "on conflict (workspace_id, dedupe_key) where dedupe_key is not null "
                "do nothing returning id"
            ),
            {
                "w": ctx.ws,
                "u": uid,
                "k": kind,
                "t": ticket_id,
                "ti": title[:200],
                "b": body[:500] if body else None,
                "d": f"{dedupe_base}:{uid}",
                "ia": in_app,
                "em": email,
            },
        ).first()
        created += 1 if row else 0
    return created


def ticket_label(ctx: ServiceCtx, ticket_id: uuid.UUID) -> tuple[int, str, uuid.UUID | None]:
    r = ctx.session.execute(
        text(
            "select number, subject, assignee_id from tickets where id = :t and workspace_id = :w"
        ),
        {"t": ticket_id, "w": ctx.ws},
    ).one()
    return r.number, r.subject, r.assignee_id


def owners_and_admins(ctx: ServiceCtx) -> list[uuid.UUID]:
    return [
        r.user_id
        for r in ctx.session.execute(
            text(
                "select user_id from memberships where workspace_id = :w and active "
                "and role in ('owner', 'admin')"
            ),
            {"w": ctx.ws},
        )
    ]


def notify_assignee_or_admins(
    ctx: ServiceCtx,
    ticket_id: uuid.UUID,
    kind: str,
    title: str,
    body: str | None,
    dedupe_base: str,
) -> int:
    """Tell the ticket's assignee, or the owners and admins when nobody owns the ticket yet."""
    _, _, assignee = ticket_label(ctx, ticket_id)
    recipients = [assignee] if assignee else owners_and_admins(ctx)
    return notify(ctx, recipients, kind, ticket_id, title, body, dedupe_base)
