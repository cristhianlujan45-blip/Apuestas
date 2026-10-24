from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import DATA_DIR, get_settings


class Base(DeclarativeBase):
    pass


_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    global _engine, _SessionLocal
    if _engine is None:
        settings = get_settings()
        kwargs: dict = {"pool_pre_ping": True, "future": True}
        if settings.is_sqlite:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            kwargs["connect_args"] = {"check_same_thread": False}
        _engine = create_engine(settings.database_url, **kwargs)
        if settings.is_sqlite:
            @event.listens_for(_engine, "connect")
            def _sqlite_pragmas(dbapi_conn, _):  # pragma: no cover - trivial
                cur = dbapi_conn.cursor()
                cur.execute("PRAGMA journal_mode=WAL")
                cur.execute("PRAGMA foreign_keys=ON")
                cur.close()
        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def reset_engine(url: str | None = None) -> None:
    """Usado por los tests para apuntar a otra base de datos."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None
    if url is not None:
        get_settings().database_url = url


def SessionLocal() -> Session:
    get_engine()
    assert _SessionLocal is not None
    return _SessionLocal()


@contextmanager
def session_scope() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def init_db() -> None:
    from . import models  # noqa: F401  (registra las tablas)

    engine = get_engine()
    Base.metadata.create_all(engine)
    if engine.dialect.name == "postgresql":
        _postgres_extras(engine)


def _postgres_extras(engine: Engine) -> None:
    """Protecciones adicionales en PostgreSQL.

    * Las predicciones son de solo inserción: un trigger bloquea UPDATE/DELETE
      para que nadie pueda reescribir el historial y aparentar mayor precisión.
    * Si TimescaleDB está disponible, las cotizaciones se guardan en una
      hypertable.
    """
    with engine.begin() as conn:
        conn.execute(text(
            """
            CREATE OR REPLACE FUNCTION forbid_prediction_mutation() RETURNS trigger AS $$
            BEGIN
              RAISE EXCEPTION 'Las predicciones son inmutables (append-only)';
            END; $$ LANGUAGE plpgsql;
            """
        ))
        conn.execute(text("DROP TRIGGER IF EXISTS predictions_immutable ON predictions"))
        conn.execute(text(
            "CREATE TRIGGER predictions_immutable BEFORE UPDATE OR DELETE ON predictions "
            "FOR EACH ROW EXECUTE FUNCTION forbid_prediction_mutation()"
        ))
        has_timescale = conn.execute(text(
            "SELECT 1 FROM pg_available_extensions WHERE name = 'timescaledb'"
        )).first()
    if has_timescale:
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS timescaledb"))
            # Requiere que captured_at forme parte de la clave primaria.
            conn.execute(text(
                "SELECT create_hypertable('odds_quotes', 'captured_at', "
                "if_not_exists => TRUE, migrate_data => TRUE)"
            ))
