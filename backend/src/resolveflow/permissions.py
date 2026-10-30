ROLES = ("owner", "admin", "agent", "viewer")

_TICKET = frozenset(
    {
        "ticket:read",
        "ticket:create",
        "ticket:update",
        "ticket:reply",
        "ticket:assign",
        "ticket:merge",
        "ticket:bulk",
    }
)
_ADMIN = frozenset(
    {
        "user:read",
        "user:invite",
        "user:manage",
        "audit:read",
        "settings:read",
        "settings:update",
        "rule:read",
        "rule:manage",
        "team:manage",
        "notification:admin",
        "analytics:read",
    }
)

PERMS: dict[str, frozenset[str]] = {
    "owner": _TICKET | _ADMIN,
    "admin": _TICKET | _ADMIN,
    "agent": _TICKET | {"user:read"},
    "viewer": frozenset({"ticket:read", "user:read"}),
}


def permissions_for(role: str | None) -> list[str]:
    return sorted(PERMS.get(role or "", frozenset()))
