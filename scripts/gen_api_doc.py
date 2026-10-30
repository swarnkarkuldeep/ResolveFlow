"""Generate docs/API.md from the FastAPI app's OpenAPI schema (run from backend/ with the venv)."""

import os
import re
from collections import defaultdict
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://x:x@localhost/x")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from resolveflow.main import app  # noqa: E402

GROUPS = [
    ("Authentication and account", ("/api/auth",)),
    ("Tickets and messages", ("/api/tickets", "/api/customers", "/api/search")),
    ("Public form and email webhooks", ("/api/public", "/api/webhooks", "/api/dev")),
    ("Service levels", ("/api/settings/sla",)),
    ("Automations and teams", ("/api/rules", "/api/teams")),
    ("Notifications", ("/api/notification", )),
    ("Analytics", ("/api/analytics",)),
    ("Settings, people and audit", ("/api/members", "/api/settings", "/api/audit", "/api/workspace", "/api/invitations")),
    ("Health", ("/api/health",)),
]

schema = app.openapi()
rows: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
for path, ops in sorted(schema["paths"].items()):
    for method, op in sorted(ops.items()):
        if method not in {"get", "post", "put", "patch", "delete"}:
            continue
        first = (op.get("description") or "").strip().splitlines()[:1]
        summary = (first[0] if first else op.get("summary") or "").replace("|", "/")
        group = next((g for g, prefixes in GROUPS if path.startswith(prefixes)), "Other")
        rows[group].append((method.upper(), path, summary))

out = [
    "# API reference",
    "",
    "Generated from the running application's OpenAPI schema by `scripts/gen_api_doc.py`. "
    "While the stack is running, the same schema with request and response shapes is served at "
    "`http://localhost:8000/openapi.json`.",
    "",
    "## Conventions",
    "",
    "- **Authentication.** Sign in with `POST /api/auth/login`. The response sets an HTTP-only `rf_session` cookie "
    "and returns a `csrf_token`. Send it as the `X-CSRF-Token` header on every `POST`, `PUT`, `PATCH` and `DELETE`.",
    "- **Errors.** `{\"detail\": {\"code\": \"...\", \"message\": \"...\"}}` with a plain-language message. "
    "Validation errors use the standard `detail` list.",
    "- **Permissions.** Each endpoint requires a permission (for example `ticket:read`, `rule:manage`, `analytics:read`). "
    "Owners and admins have all of them, agents work with tickets, viewers read. See "
    "[the user guide](USER_GUIDE.md#roles-and-permissions).",
    "- **Tenancy.** Every request runs inside the caller's workspace. Another workspace's ids return `404`.",
    "- **Pagination.** Ticket lists use an opaque `cursor` and return `next_cursor`.",
    "",
]
seen = set()
for name, _ in GROUPS + [("Other", ())]:
    if name in seen or not rows.get(name):
        continue
    seen.add(name)
    out += [f"## {name}", "", "| Method | Path | What it does |", "| --- | --- | --- |"]
    out += [f"| `{m}` | `{p}` | {re.sub(r'\s+', ' ', s)} |" for m, p, s in rows[name]]
    out.append("")
Path(__file__).resolve().parent.parent.joinpath("docs", "API.md").write_text("\n".join(out), encoding="utf-8", newline="\n")
print(sum(len(v) for v in rows.values()), "endpoints")
