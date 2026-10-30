import uuid
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import text
from sqlalchemy.orm import Session

from resolveflow.db import engine_for, system_engine
from resolveflow.rules.teams import pick_round_robin
from tests.helpers import Actor, ClientFactory, invite_actor, make_owner, team


def new_team(actor: Actor, name: str = "Support") -> dict:  # type: ignore[type-arg]
    r = actor.post("/api/teams", {"name": name})
    assert r.status_code == 200, r.text
    return dict(r.json())


def set_members(actor: Actor, team_id: str, user_ids: list[str]) -> object:
    return actor.client.put(
        f"/api/teams/{team_id}/members",
        json={"user_ids": user_ids},
        headers={"X-CSRF-Token": actor.csrf},
    )


def test_create_rename_list_and_delete_a_team(client_factory: ClientFactory) -> None:
    t = team(client_factory)
    created = new_team(t["owner"], "Support")
    assert created["name"] == "Support" and created["members"] == []
    r = t["owner"].patch(f"/api/teams/{created['id']}", {"name": "Customer care"})
    assert r.status_code == 200 and r.json()["name"] == "Customer care"
    listed = t["agent"].get("/api/teams").json()  # anyone with user:read can list
    assert [x["name"] for x in listed] == ["Customer care"]
    assert t["owner"].delete(f"/api/teams/{created['id']}").status_code == 200
    assert t["owner"].get("/api/teams").json() == []


def test_membership_rules(client_factory: ClientFactory) -> None:
    t = team(client_factory)
    tm = new_team(t["owner"])
    agent, admin, viewer = t["agent"].user_id, t["admin"].user_id, t["viewer"].user_id
    ok = set_members(t["owner"], tm["id"], [agent, admin])
    assert ok.status_code == 200  # type: ignore[attr-defined]
    members = {m["user_id"]: m for m in t["owner"].get("/api/teams").json()[0]["members"]}
    assert set(members) == {agent, admin} and members[agent]["name"] == "Agent Person"
    assert set_members(t["owner"], tm["id"], [viewer]).status_code == 422  # type: ignore[attr-defined]
    stranger = make_owner(client_factory, "Elsewhere")
    assert set_members(t["owner"], tm["id"], [stranger.user_id]).status_code == 422  # type: ignore[attr-defined]
    t["owner"].patch(f"/api/members/{agent}", {"active": False})
    assert set_members(t["owner"], tm["id"], [agent]).status_code == 422  # type: ignore[attr-defined]
    assert set_members(t["owner"], tm["id"], []).status_code == 200  # type: ignore[attr-defined]


def test_names_are_unique_per_workspace_ignoring_case(client_factory: ClientFactory) -> None:
    a, b = make_owner(client_factory, "Alpha"), make_owner(client_factory, "Bravo")
    new_team(a, "Support")
    assert a.post("/api/teams", {"name": "support"}).status_code == 409
    assert a.post("/api/teams", {"name": "  "}).status_code == 422
    assert new_team(b, "Support")["name"] == "Support"  # another workspace may reuse it


def test_foreign_teams_are_404_and_roles_are_enforced(client_factory: ClientFactory) -> None:
    t = team(client_factory)
    other = make_owner(client_factory, "Elsewhere")
    foreign = new_team(other, "Theirs")
    assert t["owner"].patch(f"/api/teams/{foreign['id']}", {"name": "x"}).status_code == 404
    assert t["owner"].delete(f"/api/teams/{foreign['id']}").status_code == 404
    assert set_members(t["owner"], foreign["id"], []).status_code == 404  # type: ignore[attr-defined]
    assert t["agent"].post("/api/teams", {"name": "Nope"}).status_code == 403
    assert t["viewer"].delete(f"/api/teams/{uuid.uuid4()}").status_code == 403
    assert t["admin"].post("/api/teams", {"name": "Admins can"}).status_code == 200


def test_team_changes_are_audited(client_factory: ClientFactory, postgres_url: str) -> None:
    t = team(client_factory)
    tm = new_team(t["owner"])
    t["owner"].patch(f"/api/teams/{tm['id']}", {"name": "Renamed"})
    set_members(t["owner"], tm["id"], [t["agent"].user_id])
    t["owner"].delete(f"/api/teams/{tm['id']}")
    with engine_for(postgres_url).connect() as conn:
        actions = list(
            conn.execute(
                text(
                    "select action from audit_log where workspace_id = :w and entity_type = 'team' order by created_at, id"
                ),
                {"w": uuid.UUID(t["owner"].workspace_id)},
            ).scalars()
        )
    assert actions == ["team.created", "team.updated", "team.members_updated", "team.deleted"]


def _members_of(owner: Actor, team_id: str, ids: list[str]) -> None:
    assert set_members(owner, team_id, ids).status_code == 200  # type: ignore[attr-defined]


def _pick(ws: str, team_id: str) -> str | None:
    with Session(system_engine()) as s, s.begin():
        picked = pick_round_robin(s, uuid.UUID(ws), uuid.UUID(team_id))
    return str(picked) if picked else None


def test_round_robin_rotates_evenly_and_skips_ineligible_people(
    client_factory: ClientFactory,
) -> None:
    owner = make_owner(client_factory)
    a1 = invite_actor(owner, client_factory, "agent", "Alice")
    a2 = invite_actor(owner, client_factory, "agent", "Bea")
    a3 = invite_actor(owner, client_factory, "agent", "Cy")
    tm = new_team(owner)
    _members_of(owner, tm["id"], [a1.user_id, a2.user_id, a3.user_id])
    picks = [_pick(owner.workspace_id, tm["id"]) for _ in range(6)]
    assert picks[:3] == picks[3:] and set(picks[:3]) == {a1.user_id, a2.user_id, a3.user_id}
    owner.patch(f"/api/members/{a2.user_id}", {"active": False})  # deactivated people are skipped
    later = {_pick(owner.workspace_id, tm["id"]) for _ in range(4)}
    assert later == {a1.user_id, a3.user_id}
    owner.patch(f"/api/members/{a3.user_id}", {"role": "viewer"})  # viewers cannot be assigned work
    assert {_pick(owner.workspace_id, tm["id"]) for _ in range(3)} == {a1.user_id}


def test_round_robin_with_an_empty_or_unknown_team_returns_nobody(
    client_factory: ClientFactory,
) -> None:
    owner = make_owner(client_factory)
    tm = new_team(owner)
    assert _pick(owner.workspace_id, tm["id"]) is None
    assert _pick(owner.workspace_id, str(uuid.uuid4())) is None


def test_concurrent_picks_never_choose_the_same_person_twice(client_factory: ClientFactory) -> None:
    owner = make_owner(client_factory)
    agents = [invite_actor(owner, client_factory, "agent", f"Agent {i}") for i in range(4)]
    tm = new_team(owner)
    _members_of(owner, tm["id"], [a.user_id for a in agents])
    with ThreadPoolExecutor(4) as pool:
        picks = list(pool.map(lambda _: _pick(owner.workspace_id, tm["id"]), range(4)))
    assert len(set(picks)) == 4
