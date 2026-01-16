from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from pete_dm_clean.db.base import Base
from pete_dm_clean.db.settings import resolve_db_settings


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _is_sqlite_url(url: str) -> bool:
    return url.strip().lower().startswith("sqlite:")


def _install_sqlite_pragmas(engine: Engine) -> None:
    # WAL improves read/write concurrency for a homelab UI + occasional CLI runs.
    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_conn, _conn_record):  # noqa: ANN001
        try:
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL;")
            cursor.execute("PRAGMA synchronous=NORMAL;")
            cursor.execute("PRAGMA foreign_keys=ON;")
            cursor.close()
        except Exception:
            # best-effort; never break app startup due to pragmas
            pass


def create_engine_if_enabled(*, uploads_dir: Path) -> Optional[Engine]:
    settings = resolve_db_settings(uploads_dir=uploads_dir)
    if not settings.enabled:
        return None

    connect_args = {}
    if _is_sqlite_url(settings.url):
        connect_args = {"check_same_thread": False}

    engine = create_engine(
        settings.url,
        future=True,
        pool_pre_ping=True,
        connect_args=connect_args,
    )
    if _is_sqlite_url(settings.url):
        _install_sqlite_pragmas(engine)
    return engine


def get_sessionmaker(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def init_db(engine: Engine) -> None:
    Base.metadata.create_all(engine)


def init_db_if_enabled(*, uploads_dir: Path) -> Optional[Engine]:
    """
    Initialize DB schema if DB is enabled via env vars.
    Returns Engine when enabled, otherwise None.
    """
    engine = create_engine_if_enabled(uploads_dir=uploads_dir)
    if engine is None:
        return None
    init_db(engine)
    # tiny smoke check (keeps failures obvious)
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return engine

