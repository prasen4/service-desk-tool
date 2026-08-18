"""Alembic environment for Tech Desk.

Runs either against a connection handed in by ``tech_desk.database.init_db``
(the normal app path — one transaction, one engine already configured with
the right SQLite pragmas / Postgres pool) or, when invoked directly via the
``alembic`` CLI for local development, against a fresh engine built from the
app's own settings.
"""

from __future__ import annotations

from alembic import context

from tech_desk.database import Base

config = context.config
target_metadata = Base.metadata


def _run_migrations(connection) -> None:
    is_sqlite = connection.dialect.name == "sqlite"
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=is_sqlite,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_offline() -> None:
    from tech_desk.config import get_settings

    url = config.get_main_option("sqlalchemy.url") or get_settings().database_url
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        _run_migrations(connection)
        return

    # Standalone invocation (e.g. `alembic upgrade head` from a shell) — build
    # our own short-lived engine from the app's settings.
    from tech_desk.database import get_engine

    engine = get_engine()
    with engine.connect() as conn:
        _run_migrations(conn)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
