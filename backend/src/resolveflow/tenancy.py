import uuid
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from resolveflow.db import app_engine


@contextmanager
def tenant_session(
    workspace_id: uuid.UUID | None,
    user_id: uuid.UUID | None,
    *,
    engine: Engine | None = None,
) -> Iterator[Session]:
    """One transaction scoped to a tenant: RLS reads `app.workspace_id` / `app.user_id`."""
    with Session(engine or app_engine()) as session, session.begin():
        session.execute(
            text(
                "select set_config('app.workspace_id', :w, true),"
                " set_config('app.user_id', :u, true)"
            ),
            {"w": str(workspace_id) if workspace_id else "", "u": str(user_id) if user_id else ""},
        )
        yield session
