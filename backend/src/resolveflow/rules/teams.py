import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from resolveflow import audit
from resolveflow.context import ServiceCtx
from resolveflow.errors import err
from resolveflow.textutil import clean_line


def pick_round_robin(
    session: Session, workspace_id: uuid.UUID, team_id: uuid.UUID
) -> uuid.UUID | None:
    """Least recently assigned eligible member (active, not a viewer); stamps the pick atomically."""
    # Lock the team row first: pickers queue up here, so a waiting picker sees the previous stamp.
    team = session.execute(
        text("select id from teams where id = :t and workspace_id = :w for update"),
        {"t": team_id, "w": workspace_id},
    ).first()
    if not team:
        return None
    picked: uuid.UUID | None = session.execute(
        text(
            "select tm.user_id from team_members tm "
            "join memberships m on m.user_id = tm.user_id and m.workspace_id = tm.workspace_id "
            "where tm.team_id = :t and tm.workspace_id = :w and m.active and m.role <> 'viewer' "
            "order by tm.last_assigned_at nulls first, tm.user_id limit 1"
        ),
        {"t": team_id, "w": workspace_id},
    ).scalar()
    if picked:
        session.execute(
            text(
                "update team_members set last_assigned_at = clock_timestamp() where team_id = :t and user_id = :u"
            ),
            {"t": team_id, "u": picked},
        )
    return picked


def _members(ctx: ServiceCtx, team_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[dict[str, Any]]]:
    rows = ctx.session.execute(
        text(
            "select tm.team_id, tm.user_id, u.name, m.role, m.active from team_members tm "
            "join users u on u.id = tm.user_id "
            "join memberships m on m.user_id = tm.user_id and m.workspace_id = tm.workspace_id "
            "where tm.team_id = any(:ids) order by u.name"
        ),
        {"ids": team_ids},
    ).all()
    out: dict[uuid.UUID, list[dict[str, Any]]] = {t: [] for t in team_ids}
    for r in rows:
        out[r.team_id].append(
            {"user_id": str(r.user_id), "name": r.name, "role": r.role, "active": r.active}
        )
    return out


def list_teams(ctx: ServiceCtx) -> list[dict[str, Any]]:
    teams = ctx.session.execute(
        text("select id, name from teams where workspace_id = :w order by name"), {"w": ctx.ws}
    ).all()
    members = _members(ctx, [t.id for t in teams])
    return [{"id": str(t.id), "name": t.name, "members": members[t.id]} for t in teams]


def get_team(ctx: ServiceCtx, team_id: uuid.UUID) -> dict[str, Any]:
    t = ctx.session.execute(
        text("select id, name from teams where id = :t and workspace_id = :w"),
        {"t": team_id, "w": ctx.ws},
    ).first()
    if not t:
        raise err(404, "not_found", "Team not found.")
    return {"id": str(t.id), "name": t.name, "members": _members(ctx, [t.id])[t.id]}


def _clean_name(name: str) -> str:
    cleaned = clean_line(name)
    if not cleaned:
        raise err(422, "bad_name", "A team needs a name.")
    return cleaned[:60]


def create_team(ctx: ServiceCtx, name: str) -> dict[str, Any]:
    name = _clean_name(name)
    try:
        team_id = ctx.session.execute(
            text("insert into teams (workspace_id, name) values (:w, :n) returning id"),
            {"w": ctx.ws, "n": name},
        ).scalar_one()
    except IntegrityError:
        raise err(409, "team_exists", "A team with that name already exists.") from None
    audit.record(
        ctx.session,
        workspace_id=ctx.ws,
        actor_type=ctx.actor_type,
        actor_id=ctx.actor_id,
        action="team.created",
        entity_type="team",
        entity_id=team_id,
        after={"name": name},
        request_id=ctx.request_id,
    )
    return get_team(ctx, team_id)


def rename_team(ctx: ServiceCtx, team_id: uuid.UUID, name: str) -> dict[str, Any]:
    before = get_team(ctx, team_id)
    name = _clean_name(name)
    try:
        ctx.session.execute(
            text("update teams set name = :n where id = :t and workspace_id = :w"),
            {"n": name, "t": team_id, "w": ctx.ws},
        )
        ctx.session.flush()
    except IntegrityError:
        raise err(409, "team_exists", "A team with that name already exists.") from None
    audit.record(
        ctx.session,
        workspace_id=ctx.ws,
        actor_type=ctx.actor_type,
        actor_id=ctx.actor_id,
        action="team.updated",
        entity_type="team",
        entity_id=team_id,
        before={"name": before["name"]},
        after={"name": name},
        request_id=ctx.request_id,
    )
    return get_team(ctx, team_id)


def _referenced_by_rules(ctx: ServiceCtx, team_id: uuid.UUID) -> int:
    n: int = ctx.session.execute(
        text(
            "select count(*) from rules r join rule_versions v on v.rule_id = r.id "
            "and v.version in (r.current_version, coalesce(r.active_version, r.current_version)) "
            "where r.workspace_id = :w and r.status <> 'archived' and v.definition::text like :like"
        ),
        {"w": ctx.ws, "like": f"%{team_id}%"},
    ).scalar_one()
    return n


def delete_team(ctx: ServiceCtx, team_id: uuid.UUID) -> None:
    before = get_team(ctx, team_id)
    used = _referenced_by_rules(ctx, team_id)
    if used:
        raise err(
            409,
            "team_in_use",
            f"This team is used by {used} automation rule(s). Change or archive them first.",
        )
    ctx.session.execute(
        text("delete from teams where id = :t and workspace_id = :w"), {"t": team_id, "w": ctx.ws}
    )
    audit.record(
        ctx.session,
        workspace_id=ctx.ws,
        actor_type=ctx.actor_type,
        actor_id=ctx.actor_id,
        action="team.deleted",
        entity_type="team",
        entity_id=team_id,
        before={"name": before["name"]},
        request_id=ctx.request_id,
    )


def set_members(ctx: ServiceCtx, team_id: uuid.UUID, user_ids: list[uuid.UUID]) -> dict[str, Any]:
    before = get_team(ctx, team_id)
    wanted = list(dict.fromkeys(user_ids))
    if wanted:
        eligible = {
            r.user_id
            for r in ctx.session.execute(
                text(
                    "select user_id from memberships where workspace_id = :w and active "
                    "and role <> 'viewer' and user_id = any(:ids)"
                ),
                {"w": ctx.ws, "ids": wanted},
            )
        }
        bad = [u for u in wanted if u not in eligible]
        if bad:
            raise err(
                422,
                "bad_member",
                "Teams can only include active workspace members who are not viewers.",
            )
    ctx.session.execute(
        text(
            "delete from team_members where team_id = :t and workspace_id = :w and not (user_id = any(:ids))"
        ),
        {"t": team_id, "w": ctx.ws, "ids": wanted},
    )
    for u in wanted:
        ctx.session.execute(
            text(
                "insert into team_members (team_id, workspace_id, user_id) values (:t, :w, :u) "
                "on conflict (team_id, user_id) do nothing"
            ),
            {"t": team_id, "w": ctx.ws, "u": u},
        )
    audit.record(
        ctx.session,
        workspace_id=ctx.ws,
        actor_type=ctx.actor_type,
        actor_id=ctx.actor_id,
        action="team.members_updated",
        entity_type="team",
        entity_id=team_id,
        before={"members": [m["user_id"] for m in before["members"]]},
        after={"members": [str(u) for u in wanted]},
        request_id=ctx.request_id,
    )
    return get_team(ctx, team_id)
