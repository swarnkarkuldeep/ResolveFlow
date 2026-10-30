import uuid

from sqlalchemy import create_engine, text

from resolveflow.tenancy import tenant_session


def _role(url: str, name: str) -> dict[str, bool]:
    eng = create_engine(url)
    try:
        with eng.connect() as c:
            row = c.execute(
                text("select rolsuper, rolbypassrls from pg_roles where rolname = :n"), {"n": name}
            ).one()
        return {"super": row[0], "bypass": row[1]}
    finally:
        eng.dispose()


def test_app_role_is_not_superuser_and_cannot_bypass_rls(
    migrated_env: None, postgres_url: str
) -> None:
    assert _role(postgres_url, "rf_app") == {"super": False, "bypass": False}
    assert _role(postgres_url, "rf_system") == {"super": False, "bypass": True}


def test_tenant_session_sets_and_scopes_context(migrated_env: None) -> None:
    w, u = uuid.uuid4(), uuid.uuid4()
    with tenant_session(w, u) as s:
        got = s.execute(
            text("select current_setting('app.workspace_id'), current_setting('app.user_id')")
        ).one()
        assert got == (str(w), str(u))
    with tenant_session(None, None) as s:
        assert s.execute(text("select current_setting('app.workspace_id', true)")).scalar() in (
            "",
            None,
        )
        assert s.execute(text("select current_user")).scalar() == "rf_app"
