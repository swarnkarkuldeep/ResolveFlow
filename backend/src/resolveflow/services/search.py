"""Full-text ticket search over subjects and message bodies (Postgres tsvector, tenant-scoped)."""

import html
import re
import uuid
from typing import Any

from sqlalchemy import text

from resolveflow.context import ServiceCtx
from resolveflow.errors import err
from resolveflow.services import tickets as tk

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_START, _STOP = "", ""  # private-use markers, swapped for <mark> after escaping
_HEADLINE = f"StartSel={_START}, StopSel={_STOP}, MaxFragments=1, MaxWords=24, MinWords=8"

_SEARCH_SELECT = tk._SELECT.replace(
    "\nfrom tickets t\n",
    ",\n  rk.rank, rk.subj_hit,\n"
    "  ts_headline('english', coalesce(rk.body, t.subject), rk.tq, :hl) as hl\nfrom tickets t\n",
    1,
)
_RANK_JOIN = """
join lateral (
  select x.tq, (t.search_vec @@ x.tq) as subj_hit, mm.body,
    case when t.search_vec @@ x.tq then 1 + ts_rank(t.search_vec, x.tq)
         else coalesce(mm.rank, 0) end as rank
  from (select websearch_to_tsquery('english', :q) as tq) x
  left join lateral (
    select m.body, ts_rank(m.search_vec, x.tq) as rank from messages m
    where m.ticket_id = t.id and m.workspace_id = t.workspace_id and m.search_vec @@ x.tq
    order by rank desc limit 1) mm on true
) rk on true
"""


def _mark(snippet: str) -> str:
    return html.escape(snippet).replace(_START, "<mark>").replace(_STOP, "</mark>")


def search_tickets(
    ctx: ServiceCtx,
    q: str,
    *,
    me: uuid.UUID,
    statuses: list[str] | None = None,
    priorities: list[str] | None = None,
    assignee: str | None = None,
    tag: str | None = None,
    limit: int = 25,
) -> list[dict[str, Any]]:
    q = _CONTROL.sub("", q).strip()[:200]
    tag = _CONTROL.sub("", tag) if tag else tag
    if not q:
        raise err(422, "empty_query", "Type something to search for.")
    where = ["t.workspace_id = :w", "(rk.subj_hit or rk.body is not null)"]
    params: dict[str, Any] = {"w": ctx.ws, "q": q, "hl": _HEADLINE, "lim": limit}
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
    sql = (  # fragments are fixed strings; every value is a bound parameter
        _SEARCH_SELECT
        + _RANK_JOIN
        + " where "
        + " and ".join(where)
        + " order by rk.rank desc, t.last_activity_at desc, t.id limit :lim"
    )
    out = []
    for r in ctx.session.execute(text(sql), params).all():
        item = tk._item(r)
        item["match"] = "subject" if r.subj_hit else "message"
        item["snippet_html"] = _mark(r.hl or "")
        item["rank"] = float(r.rank)
        out.append(item)
    return out
